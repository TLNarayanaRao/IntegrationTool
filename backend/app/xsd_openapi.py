"""Project self-contained XSDs into OpenAPI schemas and wire XML examples."""
from __future__ import annotations

from copy import deepcopy

from lxml import etree

from .data_formats import DataFormats

XSD = 'http://www.w3.org/2001/XMLSchema'
XS = '{' + XSD + '}'
INTEGERS = set('integer long int short byte nonNegativeInteger positiveInteger nonPositiveInteger negativeInteger unsignedLong unsignedInt unsignedShort unsignedByte'.split())
FORMATS = {'date': 'date', 'dateTime': 'date-time', 'time': 'time', 'anyURI': 'uri', 'base64Binary': 'byte'}
EXAMPLES = {'date': '2026-01-01', 'dateTime': '2026-01-01T00:00:00Z', 'time': '00:00:00Z',
            'anyURI': 'https://example.com/', 'base64Binary': 'ZXhhbXBsZQ==', 'hexBinary': '6578616D706C65',
            'negativeInteger': '-1', 'nonPositiveInteger': '0', 'boolean': 'true'}


def describe_xsd(source):
    if len(source) > 8 * 1024**2:
        return None
    try:
        raw = DataFormats.safe_xml(source)
        if len(raw) > 8 * 1024**2:
            return None
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
        document = etree.fromstring(raw, parser)
        if document.tag != XS + 'schema':
            return None
        return XsdProjection(document).describe()
    except (ValueError, etree.Error):
        return None


class XsdProjection:
    def __init__(self, document, graph=None):
        self.scopes = {}
        self.globals = {}
        self.roots = []
        scopes = graph.scopes.items() if graph else [((None, document.get('targetNamespace')), document)]
        for scope, source in scopes:
            _, namespace = scope
            root = deepcopy(source) if graph else source
            self.scopes[root] = namespace
            for node in root:
                if not isinstance(node.tag, str) or not node.tag.startswith(XS) or not node.get('name'): continue
                kind = etree.QName(node).localname
                self.globals.setdefault((namespace, kind, node.get('name')), node)
                if kind == 'element' and (not graph or scope in graph.roots): self.roots.append(node)
        self.nodes_left = 16000
        self.examples_left = 512

    def describe(self):
        roots = self.roots
        if not roots:
            return None
        schema, example = self.element(roots[0], global_element=True)
        alternatives = [self.element(root, global_element=True, example=False)[0] for root in roots[1:32]]
        if alternatives:
            schema = {'oneOf': [schema, *alternatives]}
        xml = etree.tostring(example, encoding='utf-8', xml_declaration=True, pretty_print=True).decode() if example is not None else None
        return schema, xml

    def lookup(self, node, value, *kinds):
        if not value:
            return None
        prefix, colon, name = value.rpartition(':')
        namespace = node.nsmap.get(prefix if colon else None)
        if colon and namespace is None: return None
        scope = self.scopes[node.getroottree().getroot()]
        spaces = (namespace,) if namespace is not None else (None, scope)
        return next((self.globals[space, kind, name] for space in spaces for kind in kinds
                     if (space, kind, name) in self.globals), None)

    def primitive(self, node, kind, active):
        restriction = node.find(XS + 'restriction')
        if restriction is not None:
            base = restriction.get('base', 'string')
            named = self.lookup(restriction, base, 'simpleType')
            if named is not None and named not in active and len(active) < 32:
                schema, value = self.primitive(named, 'string', (*active, named))
            else:
                schema, value = self.primitive(restriction, base.split(':')[-1], active)
            values = [item.get('value') for item in restriction.findall(XS + 'enumeration') if item.get('value') is not None]
            if values:
                value = values[0]
                if schema.get('type') == 'string':
                    schema['enum'] = values
            for facet, keyword in [('minLength', 'minLength'), ('maxLength', 'maxLength'), ('length', 'minLength'), ('length', 'maxLength')]:
                limit = restriction.find(XS + facet)
                if limit is not None and (limit.get('value') or '').isdigit():
                    schema[keyword] = int(limit.get('value'))
            minimum = restriction.find(XS + 'minInclusive')
            if minimum is not None and schema.get('type') in ('number', 'integer'):
                value = minimum.get('value', value)
            if schema.get('type') == 'string' and not values:
                value = value[:schema.get('maxLength', len(value))]
                value = value.ljust(min(schema.get('minLength', 0), 256), 'x')
            return schema, value
        schema_type = 'integer' if kind in INTEGERS else 'number' if kind in ('decimal', 'float', 'double') else 'boolean' if kind == 'boolean' else 'string'
        schema = {'type': schema_type}
        if kind in FORMATS:
            schema['format'] = FORMATS[kind]
        return schema, EXAMPLES.get(kind, '1' if schema_type in ('number', 'integer') else 'example')

    def members(self, container, active=(), required=True, example=True):
        if container in active or len(active) >= 32 or self.nodes_left <= 0:
            return
        self.nodes_left -= 1
        active = (*active, container)
        choice = container.tag == XS + 'choice'
        first_choice = next((child for child in container if child.tag in
                             (XS + 'element', XS + 'sequence', XS + 'choice', XS + 'group')), None) if choice else None
        for child in container:
            if self.nodes_left <= 0:
                return
            include = example and (not choice or child is first_choice)
            if child.tag in (XS + 'element', XS + 'attribute'):
                yield child, required and not choice, include
            elif child.tag in (XS + 'sequence', XS + 'all', XS + 'choice', XS + 'complexContent', XS + 'simpleContent'):
                yield from self.members(child, active, required and not choice and child.get('minOccurs') != '0',
                                        include)
            elif child.tag in (XS + 'extension', XS + 'restriction'):
                base = self.lookup(child, child.get('base'), 'complexType')
                if base is not None and child.tag == XS + 'extension':
                    yield from self.members(base, active, required, example)
                yield from self.members(child, active, required, example)
            elif child.tag in (XS + 'group', XS + 'attributeGroup'):
                group = self.lookup(child, child.get('ref'), etree.QName(child).localname)
                if group is not None:
                    yield from self.members(group, active, required and not choice and child.get('minOccurs') != '0',
                                            include)

    def element(self, occurrence, active=(), *, global_element=False, example=True):
        kind = etree.QName(occurrence).localname
        declaration = self.lookup(occurrence, occurrence.get('ref'), kind)
        qualified = declaration is not None or global_element or occurrence.get('form', occurrence.getroottree().getroot().get(kind + 'FormDefault')) == 'qualified'
        if declaration is None:
            declaration = occurrence
        name = declaration.get('name') or (occurrence.get('ref') or '').split(':')[-1]
        xml = {'name': name}
        namespace = self.scopes[declaration.getroottree().getroot()] if qualified else None
        if namespace:
            xml['namespace'] = namespace
        if kind == 'attribute':
            xml['attribute'] = True
        if self.nodes_left <= 0 or len(active) >= 32:
            return {'xml': xml, 'description': 'Nested XML type exceeds the documentation expansion limit.'}, None
        self.nodes_left -= 1
        content = declaration.find(XS + 'complexType')
        if content is None:
            content = declaration.find(XS + 'simpleType')
        if content is None:
            content = self.lookup(declaration, declaration.get('type'), 'complexType', 'simpleType')
        if content is not None and content in active:
            return {'type': 'object', 'xml': xml, 'description': 'Recursive XML type.'}, None

        qname = '{' + namespace + '}' + name if namespace else name
        node = None
        if example and self.examples_left > 0:
            self.examples_left -= 1
            node = etree.Element(qname)
        if content is not None and content.tag == XS + 'complexType':
            properties, required = {}, []
            for child, mandatory, include in self.members(content):
                if child.get('use') == 'prohibited' or child.get('maxOccurs') == '0':
                    continue
                field, child_xml = self.element(child, (*active, content), example=node is not None and include)
                attribute = field['xml'].get('attribute', False)
                key = ('@' if attribute else '') + field['xml']['name']
                minimum = int(child.get('minOccurs', '1'))
                maximum = child.get('maxOccurs', '1')
                if not attribute and maximum != '1':
                    field = {'type': 'array', 'items': field, 'minItems': minimum, 'xml': {'wrapped': False}}
                    if maximum != 'unbounded':
                        field['maxItems'] = int(maximum)
                properties[key] = field
                if mandatory and (child.get('use') == 'required' if attribute else minimum > 0):
                    required.append(key)
                if child_xml is not None:
                    if attribute:
                        node.set(child_xml.tag, child_xml.text or '')
                    else:
                        node.append(child_xml)
                        size = sum(1 for _ in child_xml.iter())
                        copies = min(max(minimum - 1, 0), 3, self.examples_left // size)
                        for _ in range(copies):
                            node.append(deepcopy(child_xml))
                        self.examples_left -= copies * size
            schema = {'type': 'object', 'properties': properties}
            if required:
                schema['required'] = list(dict.fromkeys(required))
        else:
            primitive = content if content is not None else declaration
            schema, value = self.primitive(primitive, (declaration.get('type') or 'string').split(':')[-1], active)
            if node is not None:
                node.text = declaration.get('fixed', declaration.get('default', value))
        schema['xml'] = xml
        return schema, node
