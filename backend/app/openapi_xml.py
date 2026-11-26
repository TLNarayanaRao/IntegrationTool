"""Render mapped values according to OpenAPI XML names and structure."""
from __future__ import annotations

from lxml import etree


def mapped_response_xml(value, schema):
    """Return the wire XML and its logical value, or None for other mappings."""
    if not isinstance(value, (dict, list)) or not isinstance(schema, dict):
        return None
    root_xml = schema.get('xml') or {}
    name = root_xml.get('name')
    if not name:
        return None

    def resolved(definition):
        annotations = []
        seen = set()
        while isinstance(definition, dict) and '$ref' in definition:
            reference = definition['$ref']
            if not isinstance(reference, str) or not reference.startswith('#/') or reference in seen:
                raise ValueError('Invalid XML schema reference')
            seen.add(reference)
            annotations.append({key: item for key, item in definition.items() if key != '$ref'})
            definition = schema
            for part in reference[2:].split('/'):
                definition = definition[part.replace('~1', '/').replace('~0', '~')]
        result = definition if isinstance(definition, dict) else {}
        for annotation in reversed(annotations):
            result = {**result, **annotation}
        return result

    def names(field, xml):
        local = xml.get('name', field)
        namespace = xml.get('namespace')
        if xml.get('prefix') and not namespace:
            raise ValueError('An XML prefix requires a namespace')
        return (etree.QName(namespace, local) if namespace else etree.QName(local),
                {xml.get('prefix') or None: namespace} if namespace else None)

    def text(item):
        return str(item).lower() if isinstance(item, bool) else str(item)

    def element(parent, field, item, definition, depth=0):
        if depth > 128:
            raise ValueError('Mapped OpenAPI XML nesting limit exceeded')
        definition = resolved(definition)
        xml = definition.get('xml') or {}
        if xml.get('attribute'):
            if parent is None or isinstance(item, (dict, list)):
                raise ValueError('An XML attribute requires a parent and a scalar value')
            if item is not None:
                qualified, _ = names(field, xml)
                if qualified.text in parent.attrib:
                    raise ValueError('Multiple mapped fields use the same XML attribute name')
                parent.set(qualified, text(item))
            return None

        if parent is not None and isinstance(item, list) and not xml.get('wrapped'):
            for entry in item:
                element(parent, field, entry, definition.get('items', {}), depth + 1)
            return None

        qualified, namespaces = names(field, xml)
        if parent is not None and parent.nsmap.get(None) and not qualified.namespace:
            namespaces = {None: ''}
        properties = definition.get('properties') or {}
        additional = definition.get('additionalProperties', {})
        if isinstance(item, dict):
            namespaces = namespaces or {}
            for key, child in item.items():
                annotation = resolved(properties.get(key, additional)).get('xml') or {}
                prefix = annotation.get('prefix')
                if child is not None and annotation.get('attribute') and prefix:
                    namespace = annotation.get('namespace')
                    if not namespace or namespaces.get(prefix, namespace) != namespace:
                        raise ValueError('Conflicting XML attribute namespace prefix')
                    namespaces[prefix] = namespace
        node = (etree.Element(qualified, nsmap=namespaces) if parent is None
                else etree.SubElement(parent, qualified, nsmap=namespaces))
        if isinstance(item, dict):
            for key, child in item.items():
                element(node, key, child, properties.get(key, additional), depth + 1)
        elif isinstance(item, list):
            for entry in item:
                element(node, field, entry, definition.get('items', {}), depth + 1)
        elif item is not None:
            node.text = text(item)
        return node

    # A wrapped mapping from Studio and an object supplied directly both work.
    if (isinstance(value, dict) and set(value) == {name}
            and name not in (schema.get('properties') or {})
            and isinstance(value[name], (dict, list))):
        value = value[name]
    return etree.tostring(element(None, name, value, schema), encoding='unicode'), value
