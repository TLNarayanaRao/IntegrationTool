"""Shared XML, JSON and delimited/fixed data activities for every runtime."""
import base64, codecs, csv, io, json, re, math
from itertools import islice, takewhile
import threading
from functools import lru_cache
from pathlib import Path
from lxml import etree
from .faults import MinaFault
from .mapper import validate_output

@lru_cache(maxsize=8)
def compiled_xsd(schema, bundle=()):
    from .xsd_catalog import SchemaGraph
    path, assets = bundle or ('', ())
    return SchemaGraph(schema, path, assets, DataFormats.safe_xml).compile(), threading.Lock()


@lru_cache(maxsize=16)
def xsd_shape(schema, name='', bundle=()):
    from .xsd_catalog import SchemaGraph
    from .xsd_openapi import XsdProjection
    path, assets = bundle or ('', ())
    try:
        graph = SchemaGraph(schema, path, assets, DataFormats.safe_xml)
        projection = XsdProjection(graph.root, graph).describe()
    except (ValueError, etree.Error) as error:
        raise MinaFault('XSD dependency resolution failed: ' + str(error), fault_type='ValidationException') from error
    if not projection:
        raise MinaFault('A valid XSD with a global root element is required', fault_type='ValidationException')
    shape = projection[0]
    roots = shape.get('oneOf', [shape])
    if not name:
        return roots[0]
    local = name.rsplit('}', 1)[-1]
    for root in roots:
        xml = root.get('xml', {})
        if xml.get('name') == local and (not name.startswith('{') or xml.get('namespace') == name[1:].partition('}')[0]):
            return root
    raise MinaFault(f'XSD has no global root named {local}', fault_type='ValidationException')


def xml_document(value):
    from lxml import etree
    return etree.fromstring(DataFormats.safe_xml(value), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, strip_cdata=False))


def format_xml(content, pretty, default_namespace, cdata_paths):
    from lxml import etree
    root = xml_document(content)
    paths = set(part.strip().strip('/').replace('/', '.') for part in
                (cdata_paths.split(',') if isinstance(cdata_paths, str) else cdata_paths or []) if part.strip())
    if default_namespace and etree.QName(root).namespace:
        ns = etree.QName(root).namespace
        def clone(node, inherited=None, is_root=False):
            uri = etree.QName(node).namespace
            default = ns if is_root else None if uri is None else ns if uri == ns else inherited
            nsmap = ({None: default or ''} if default != inherited else {})
            result = etree.Element(node.tag, nsmap=nsmap)
            result.attrib.update(node.attrib)
            result.text, result.tail = node.text, node.tail
            for child in node:
                if isinstance(child.tag, str): result.append(clone(child, default))
                else:
                    from copy import deepcopy
                    result.append(deepcopy(child))
            return result
        root = clone(root, is_root=True)
    def cdata(node, parent=''):
        path = parent + etree.QName(node).localname
        if path in paths and node.text is not None:
            node.text = etree.CDATA(node.text)
        for child in node:
            if isinstance(child.tag, str): cdata(child, path + '.')
    if paths: cdata(root)
    return etree.tostring(root, encoding='unicode', pretty_print=pretty).rstrip('\n') if pretty else etree.tostring(root, encoding='unicode')


XSI_NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'
JSON_KIND = '{urn:mina:json-conversion}kind'
FORMAT_FIELDS = frozenset('format delimiter separatorRule lineSeparator lineEnding header fields fieldTypes widths fieldOffsets lineLength fillCharacter strictColumns trimValues skipBlankLines blankLinePolicy includeFinalLineSeparator rootElement recordElement schemaId fileEncoding'.split())
FORMAT_INPUT_OPTIONS = FORMAT_FIELDS - {'schemaId'} | frozenset(
    'forceEncoding encoding cdataElements validateInput validateOutput suppressXmlDeclaration prettyPrint disablePrettyPrint '
    'formatUsingDefaultNamespacePrefix jsonStyle rootStyle badgerfish useNullForEmptyValues useEmptyValuesForNull '
    'emptyToNull inferPrimitiveTypes ignoreAdditionalJsonFields duplicateKeyPolicy omitNulls indent asciiOnly '
    'manualStartRecord continueOnError'.split())


def xml_from_value(name, value, shape=None, *, badger=False, ignore=False, namespaces=None, tree_input=False, generic=False):
    from lxml import etree
    namespaces = dict(namespaces or {})
    declarations = (value.get('@xmlns') or {}) if badger and isinstance(value, dict) else {}
    if not isinstance(declarations, dict): raise ValueError('Badgerfish @xmlns must be an object')
    local_ns = {(None if key == '$' else key): uri for key, uri in declarations.items()}
    namespaces.update(local_ns)
    xml = (shape or {}).get('xml', {})
    def tag(key, definition=None, attribute=False):
        if key.startswith('{'): return key
        prefix, sep, local = key.partition(':')
        if sep:
            if prefix not in namespaces: raise ValueError(f'Undeclared XML namespace prefix: {prefix}')
            return '{' + namespaces[prefix] + '}' + local
        uri = definition.get('namespace') if definition is not None else (None if attribute else namespaces.get(None))
        return '{' + uri + '}' + key if uri else key
    element = etree.Element(tag(name, xml if shape else None), nsmap=local_ns or None)
    if value is None:
        element.set(XSI_NIL, 'true')
    elif isinstance(value, dict):
        fields = (shape or {}).get('properties', {})
        ranks = {field: rank for rank, field in enumerate(fields)}
        if generic and not value: element.set(JSON_KIND, 'object')
        entries = []
        for key, item in value.items():
            if key == '@xmlns' and badger: continue
            if key in ('#text', '$') and (tree_input or badger or key == '$'):
                if item is not None: element.text = str(item).lower() if isinstance(item, bool) else str(item)
                continue
            if key == '#content' and tree_input:
                last = None
                for part in item:
                    for child, text in part.items():
                        if child == '#text':
                            if last is None: element.text = (element.text or '') + str(text)
                            else: last.tail = (last.tail or '') + str(text)
                        else:
                            last = xml_from_value(child, text, tree_input=True)
                            element.append(last)
                continue
            local = key.rsplit(':', 1)[-1]
            field = fields.get(key, fields.get(local))
            attr = key.startswith('@') and (badger or tree_input)
            if field is None and not attr: field = fields.get('@' + local)
            if shape and field is None and ignore: continue
            attr = attr or bool((field or {}).get('xml', {}).get('attribute'))
            if attr:
                if item is not None:
                    element.set(tag(key.removeprefix('@'), field.get('xml') if field else None, attribute=True), str(item).lower() if isinstance(item, bool) else str(item))
                continue
            rank = ranks.get(local, len(fields))
            entries.append((rank, key, item, field))
        if '#content' in value and tree_input:
            return element
        for _, key, item, field in sorted(entries, key=lambda entry: entry[0]):
            is_array = isinstance(item, list)
            if generic and is_array and not item:
                child = xml_from_value(key, '', field, badger=badger, namespaces=namespaces, generic=True)
                child.set(JSON_KIND, 'empty-array')
                element.append(child)
            for entry in item if is_array else [item]:
                child_shape = field.get('items') if field and field.get('type') == 'array' else field
                child = xml_from_value(key, entry, child_shape, badger=badger, ignore=ignore, namespaces=namespaces, tree_input=tree_input, generic=generic)
                if generic and is_array and len(item) == 1: child.set(JSON_KIND, 'array-item')
                element.append(child)
    elif isinstance(value, list):
        element.set(JSON_KIND, 'array')
        for item in value: element.append(xml_from_value('item', item, badger=badger, namespaces=namespaces, generic=True))
    else:
        element.text = str(value).lower() if isinstance(value, bool) else str(value)
    return element


def json_from_xml(element, shape=None, *, badger=False, infer=False, empty=None, inherited=None):
    from lxml import etree
    def cast(text, field=None):
        kind = (field or {}).get('type')
        if kind == 'integer': return int(text)
        if kind == 'number': return float(text)
        if kind == 'boolean':
            if text not in ('true','false','1','0'): raise ValueError('Invalid XML boolean: ' + text)
            return text in ('true','1')
        if infer and not field:
            try: value = json.loads(text)
            except ValueError: return text
            if isinstance(value, (bool, int, float)) and (not isinstance(value, float) or math.isfinite(value)): return value
        return text
    def name(node):
        local = etree.QName(node).localname
        return f'{node.prefix}:{local}' if badger and node.prefix else local
    if element.get(XSI_NIL) in ('true', '1'): return empty
    fields = (shape or {}).get('properties', {})
    result = {}
    if badger:
        declared = {prefix or '$': uri for prefix, uri in element.nsmap.items()
                    if prefix != 'xml' and uri != 'urn:mina:json-conversion' and (inherited or {}).get(prefix) != uri}
        if declared: result['@xmlns'] = declared
    for key, item in element.attrib.items():
        if key in (JSON_KIND, XSI_NIL): continue
        qname = etree.QName(key)
        local = qname.localname
        prefix = next((prefix for prefix, uri in element.nsmap.items() if prefix and uri == qname.namespace), None)
        result[('@' if badger else '') + (f'{prefix}:{local}' if badger and prefix else local)] = cast(item, fields.get('@' + local))
    children = [child for child in element if isinstance(child.tag, str)]
    def convert(child, field=None):
        return json_from_xml(child, field, badger=badger, infer=infer, empty=empty, inherited=element.nsmap)
    if element.get(JSON_KIND) == 'array': return [convert(child) for child in children]
    counts = {}
    for child in children:
        key = name(child)
        counts[key] = counts.get(key, 0) + 1
    for child in children:
        key = name(child)
        field = fields.get(etree.QName(child).localname, {})
        array = counts[key] > 1 or field.get('type') == 'array' or child.get(JSON_KIND) in ('array-item','empty-array')
        item = convert(child, field.get('items') if field.get('type') == 'array' else field)
        if array:
            if key in result and not isinstance(result[key], list): result[key] = [result[key]]
            if child.get(JSON_KIND) == 'empty-array': result.setdefault(key, [])
            else: result.setdefault(key, []).append(item)
        elif key in result: result[key] = [result[key], item]
        else: result[key] = item
    if not children and not result and not (shape or {}).get('type') == 'object' and element.get(JSON_KIND) != 'object' and not badger:
        return cast(element.text or '', shape)
    value = ''.join(element.itertext()) if not children else (element.text or '') + ''.join(child.tail or '' for child in children)
    if value.strip() or badger and not children and not result: result['$'] = cast(value)
    return result


class DataFormats:
    def run_format(self,kind,operation,cfg,ctx):
        try:
            options = cfg.get('formatOptions')
            if options is not None:
                if not isinstance(options, dict): raise ValueError('Format options must be an object')
                cfg = {**cfg, **{key: value for key, value in options.items() if key in FORMAT_INPUT_OPTIONS and value is not None}}
            if kind=='json':return self.json_activity(cfg,ctx)
            if kind=='flat':return self.flat_data(cfg,ctx)
            return self.parse_xml_activity(cfg,ctx) if operation=='parse' else self.render_xml_activity(cfg,ctx)
        except MinaFault:raise
        except (ValueError,TypeError,SyntaxError,UnicodeError,LookupError,OSError,csv.Error,etree.Error,OverflowError,RecursionError) as error:
            names={'xml':('XMLParseException','XMLRenderException'),'json':('JSONParserException','JSONRenderException'),'flat':('ParseDataException','RenderDataException')}
            raise MinaFault(str(error),fault_type=names[kind][operation!='parse'],cause=type(error).__name__) from error

    @staticmethod
    def safe_xml(value):
        if isinstance(value, str):
            # A decoded string already has an encoding. Its declaration only applies to bytes.
            value = re.sub(r"""^(\ufeff?<\?xml\s+[^?]*?\bencoding\s*=\s*)(['"])[^'"]+\2""",
                           r'\1"UTF-8"', value, count=1)
            raw = value.encode('utf-8')
        elif isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
        else:
            raise ValueError('XML input must be text or bytes')
        if len(raw)>64*1024**2:raise ValueError('XML exceeds the 64 MiB input limit')
        if re.search(br'<!\s*(DOCTYPE|ENTITY)\b',raw.replace(b'\x00',b''),re.I):raise ValueError('XML DTDs and entity declarations are disabled')
        return raw

    @staticmethod
    def validate_xml_document(value,schema,bundle=()):
        from lxml import etree
        from .xsd_catalog import schema_selection
        try:
            validator,lock=compiled_xsd(schema,bundle)
            parser=etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=False)
            document=etree.fromstring(DataFormats.safe_xml(value),parser)
            _,selected=schema_selection(schema)
            if selected and document.tag!=(selected[2:] if selected.startswith('{}') else selected):
                raise ValueError('Expected selected XSD root '+selected+'; found '+document.tag)
            with lock:
                if not validator.validate(document):raise ValueError('; '.join(str(error.message) for error in list(validator.error_log)[:10]))
        except (ValueError,etree.Error) as error:raise MinaFault('XSD validation failed: '+str(error),fault_type='ValidationException') from error
    @staticmethod
    def as_bool(value,default=False):
        return default if value is None else str(value).lower() in ('true','1','yes','on')

    @staticmethod
    def delimited_rows(text,delimiter,any_character=False):
        row=[];field=[];quoted=False;closed=False;index=0
        while index<len(text):
            char=text[index]
            if quoted:
                if char=='"':
                    if index+1<len(text) and text[index+1]=='"':field.append('"');index+=2;continue
                    quoted=False;closed=True
                else:field.append(char)
                index+=1;continue
            width=1 if any_character and char in delimiter else len(delimiter) if not any_character and text.startswith(delimiter,index) else 0
            if width:row.append(''.join(field));field=[];closed=False;index+=width;continue
            if char in '\r\n':
                blank=not row and not field and not closed
                row.append(''.join(field));yield [] if blank else row;row=[];field=[];closed=False
                index+=2 if char=='\r' and text[index:index+2]=='\r\n' else 1;continue
            if closed:raise ValueError('Unexpected data after a quoted field')
            if char=='"' and not field:quoted=True
            else:field.append(char)
            index+=1
        if quoted:raise ValueError('Unterminated quoted field')
        if row or field or closed:row.append(''.join(field));yield row

    @staticmethod
    def schema_content(schema_id, ctx):
        project = ctx.get('project')
        schema = next((item for item in getattr(project, 'schemas', []) if item.id == schema_id or item.name == schema_id), None) if project and schema_id else None
        return schema.content if schema else ''

    def configured_schema(self, cfg, ctx):
        source = self.schema_content(cfg.get('schemaId'),ctx)
        if source:
            from .xsd_catalog import inherit_schema_selection
            schema=inherit_schema_selection(source,cfg.get('schemaText'))
        else:schema=cfg.get('schemaText') or ''
        if cfg.get('schemaId') and not schema:
            raise MinaFault('Selected project schema was not found', fault_type='ValidationException')
        return schema

    @staticmethod
    def schema_bundle(cfg, ctx, schema):
        if not isinstance(schema, str) or not re.search(r'<(?:[\w.-]+:)?(?:import|include|redefine|override)\b', schema):
            return ()
        project = ctx.get('project')
        assets = getattr(project, 'schemas', ())
        selected = next((asset for asset in assets if cfg.get('schemaId') in (asset.id, asset.name)), None)
        path = cfg.get('_formatSchemaPath') or ((selected.source_path or selected.name) if selected else '')
        documents = cfg.get('_formatSchemaAssets')
        if documents is None:
            documents = [(asset.source_path or asset.name, asset.content) for asset in assets if (asset.source_path or asset.name).lower().endswith('.xsd')]
        return path, tuple((name, text) for name, text in documents)

    @staticmethod
    def schema_root_name(schema, bundle=()):
        if not schema: return ''
        if isinstance(schema,str) and schema.lstrip().startswith('<'):
            from .xsd_catalog import schema_selection
            _,selected=schema_selection(schema)
            if selected:return selected.rsplit('}',1)[-1]
        try:
            document = schema if isinstance(schema,dict) else json.loads(schema)
            return document.get('title') or next(iter((document.get('properties') or {}).keys()), '')
        except (ValueError, TypeError):
            pass
        from xml.etree import ElementTree
        try: root = ElementTree.fromstring(schema)
        except (ElementTree.ParseError, TypeError): return ''
        name = next((item.attrib.get('name') for item in list(root) if item.tag.rsplit('}', 1)[-1] == 'element' and item.attrib.get('name')), '')
        return name or (xsd_shape(schema, bundle=bundle)['xml']['name'] if bundle else '')

    @staticmethod
    def schema_leaf_fields(schema, bundle=(), root_name=''):
        if not schema: return [], []
        try:
            document = schema if isinstance(schema,dict) else json.loads(schema); fields = []
            def walk(node):
                if isinstance(node, dict) and node.get('type') == 'array':
                    walk(node.get('items'))
                    return
                properties = node.get('properties', {}) if isinstance(node, dict) else {}
                for name, child in properties.items():
                    if isinstance(child, dict) and (child.get('properties') or child.get('type') == 'array' and isinstance(child.get('items'), dict) and child['items'].get('properties')): walk(child)
                    else: fields.append((name, child.get('type', 'string') if isinstance(child, dict) else 'string'))
            walk(document)
            return [item[0] for item in fields], [item[1] for item in fields]
        except (ValueError, TypeError):
            pass
        fields = {}
        def walk(shape, name=''):
            if shape.get('type') == 'array': walk(shape.get('items', {}), name)
            elif shape.get('properties'):
                for child, definition in shape['properties'].items(): walk(definition, child)
            elif name: fields.setdefault(name, shape.get('type', 'string'))
        shape = xsd_shape(schema, root_name, bundle)
        walk(shape, shape.get('xml', {}).get('name', ''))
        return list(fields), list(fields.values())

    def parse_xml_activity(self, cfg, ctx):
        style = str(cfg.get('inputStyle', 'Text')).lower()
        payload = cfg.get('source', ctx['last'])
        inputs = payload if isinstance(payload, dict) else {}
        binary = cfg.get('xmlBinary', inputs.get('xmlBinary'))
        encoding = cfg.get('forceEncoding') or cfg.get('encoding')
        source = cfg.get('xmlString', inputs.get('xmlString', payload))
        is_binary = style == 'binary' or (style == 'dynamic' and binary is not None)
        if is_binary:
            source = binary if binary is not None else payload
            if isinstance(source, dict):
                encoding = source.get('forceEncoding') or encoding
                count = source.get('byteCount')
                source = source.get('bytes', source.get('binaryContent'))
            else: count = None
            if isinstance(source, str): source = base64.b64decode(source, validate=True)
            if count is not None and (not isinstance(source, (bytes, bytearray)) or int(count) != len(source)):
                raise MinaFault('XML byte count does not match the supplied bytes', fault_type='MissingByteCountException')
        if isinstance(source, (bytes, bytearray)) and encoding:
            try: source = bytes(source).decode(encoding)
            except LookupError as error: raise MinaFault(str(error), fault_type='UnsupportedEncodingException') from error
        schema = self.configured_schema(cfg, ctx)
        bundle = self.schema_bundle(cfg, ctx, schema)
        if self.as_bool(cfg.get('validateOutput', False)):
            if not schema: raise MinaFault('Validate Output requires a project or inline XSD in Output Editor', fault_type='ValidationException')
            self.validate_xml_document(source,schema,bundle)
        result = self.parse_xml(source, schema=schema, bundle=bundle)
        if cfg.get('rootElement') and result['root'] != cfg['rootElement']:
            raise MinaFault(f'Expected XML root {cfg["rootElement"]}; found {result["root"]}', fault_type='ValidationException')
        return result

    def render_xml_activity(self, cfg, ctx):
        schema = self.configured_schema(cfg, ctx)
        bundle = self.schema_bundle(cfg, ctx, schema)
        root_name = cfg.get('rootElement') or self.schema_root_name(schema, bundle) or 'root'
        source = cfg.get(root_name, cfg.get('value', cfg.get('source', ctx['last'])))
        if isinstance(source, dict) and root_name in source and not ('root' in source and 'value' in source): source = source[root_name]
        if self.as_bool(cfg.get('validateInput', False)):
            if not schema: raise MinaFault('Validate Input requires a project or inline XSD in Input Editor', fault_type='ValidationException')
        binary = str(cfg.get('outputStyle', 'Text')).lower() == 'binary'
        encoding = str((cfg.get('byteEncoding') if binary else None) or cfg.get('encoding') or 'UTF-8')
        try:
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9._-]*', encoding): raise LookupError(f'Invalid XML encoding: {encoding}')
            codecs.lookup(encoding)
        except LookupError as error: raise MinaFault(str(error), fault_type='UnsupportedEncodingException') from error
        pretty = not self.as_bool(cfg.get('disablePrettyPrint')) if 'disablePrettyPrint' in cfg else self.as_bool(cfg.get('prettyPrint', False))
        if cfg.get('xmlString') is not None:
            document = xml_document(cfg['xmlString'])
            if cfg.get('rootElement') and document.tag != cfg['rootElement']:
                raise MinaFault(f'Expected XML root {cfg["rootElement"]}; found {document.tag}', fault_type='ValidationException')
            content = etree.tostring(document, encoding='unicode')
        elif schema and not (isinstance(source, dict) and 'root' in source and 'value' in source):
            shape = xsd_shape(schema, root_name, bundle)
            source = xml_from_value(root_name, source, shape, tree_input=True)
            content = etree.tostring(source, encoding='unicode')
        else:
            content = self.render_xml(source, root_name)
        if self.as_bool(cfg.get('validateInput', False)):self.validate_xml_document(content,schema,bundle)
        content = format_xml(content, pretty, self.as_bool(cfg.get('formatUsingDefaultNamespacePrefix')), cfg.get('cdataElements'))
        if not self.as_bool(cfg.get('suppressXmlDeclaration', False)): content = f'<?xml version="1.0" encoding="{encoding}"?>\n{content}'
        if binary:
            raw = content.encode(encoding)
            data = {'bytes': base64.b64encode(raw).decode(), 'byteCount': len(raw)}
            result = {**data, 'binaryContent': data['bytes'], 'xmlBytes': data['bytes'], 'xmlBinary': data, 'encoding': encoding, 'content': None}
            if cfg.get('bwOutputEnvelope'): result['bwXml'] = self.render_xml({'xmlBytes': data['bytes']}, 'Output')
            return result
        result = {'content': content, 'xmlString': content, 'encoding': encoding}
        if cfg.get('bwOutputEnvelope'): result['bwXml'] = self.render_xml({'xmlString': content}, 'Output')
        return result

    @staticmethod
    def validate_xml_root(root_name, schema):
        from xml.etree import ElementTree
        try: schema_root = ElementTree.fromstring(schema)
        except ElementTree.ParseError as exc: raise MinaFault(f'Selected XSD is invalid: {exc}', fault_type='ValidationException') from exc
        expected = next((item.attrib.get('name') for item in list(schema_root) if item.tag.rsplit('}',1)[-1] == 'element' and item.attrib.get('name')), None)
        actual = str(root_name or '').rsplit('}',1)[-1]
        if expected and actual != expected: raise MinaFault(f'XML root {actual!r} does not match XSD root {expected!r}', fault_type='ValidationException', details={'expectedRoot':expected,'actualRoot':actual})

    @staticmethod
    def xml_element_value(root, *, local_names=False, shape=None):
        def field_name(name):
            return name.rsplit('}', 1)[-1] if local_names else name

        def convert(element, current):
            children = list(element); result = {'@' + field_name(key): value for key, value in element.attrib.items()}
            if not children:
                text = element.text or ''
                if result or (current or {}).get('type') == 'object':
                    if text: result['#text'] = text
                    return result
                return text
            mixed=bool(element.text and element.text.strip() or any(child.tail and child.tail.strip() for child in children))
            ordered=[{'#text':element.text}] if mixed and element.text else []
            for child in children:
                name = field_name(child.tag)
                definition = (current or {}).get('properties', {}).get(child.tag.rsplit('}', 1)[-1], {})
                repeated = definition.get('type') == 'array'
                value = convert(child, definition.get('items') if repeated else definition)
                if mixed:
                    ordered.append({name:value})
                    if child.tail:ordered.append({'#text':child.tail})
                if name in result:
                    if not isinstance(result[name], list): result[name] = [result[name]]
                    result[name].append(value)
                else:
                    result[name] = [value] if repeated else value
            if element.text and element.text.strip(): result['#text'] = element.text.strip()
            if mixed:result['#content']=ordered
            return result
        return convert(root, shape)

    def parse_xml(self, source, *, schema=None, bundle=()):
        from xml.etree import ElementTree
        if isinstance(source, dict): source = source.get('content') or source.get('body') or ''
        root = ElementTree.fromstring(self.safe_xml(source))
        shape = xsd_shape(schema, root.tag, bundle) if schema else None
        value = self.xml_element_value(root, shape=shape)
        xml = ElementTree.tostring(root, encoding='unicode')
        result = {
            'mediaType': 'application/xml',
            'xml': xml,
            'xmlString': xml,
            'root': root.tag,
            'value': value,
        }
        alias = root.tag.rsplit('}', 1)[-1]
        if alias not in result:
            result[alias] = self.xml_element_value(root, local_names=True, shape=shape) if schema else value
        return result

    def render_xml(self, source, root_name='root', encoding='unicode', pretty=False):
        from xml.etree import ElementTree
        if isinstance(source, dict) and 'root' in source and 'value' in source: root_name, source = source['root'], source['value']
        def build(name, value):
            element = ElementTree.Element(name)
            if isinstance(value, dict):
                if '#content' in value:
                    for key,item in value.items():
                        if key.startswith('@'):element.set(key[1:],str(item))
                    last=None
                    for part in value['#content']:
                        for key,item in part.items():
                            if key=='#text':
                                if last is None:element.text=(element.text or '')+str(item)
                                else:last.tail=(last.tail or '')+str(item)
                            else:last=build(key,item);element.append(last)
                    return element
                for key, item in value.items():
                    if key.startswith('@'): element.set(key[1:], str(item).lower() if isinstance(item,bool) else str(item))
                    elif key == '#text': element.text = str(item)
                    elif isinstance(item, list):
                        for entry in item: element.append(build(key, entry))
                    else: element.append(build(key, item))
            elif value is not None: element.text = str(value).lower() if isinstance(value,bool) else str(value)
            return element
        root = build(root_name, source)
        ElementTree.fromstring(ElementTree.tostring(root,encoding='utf-8'))
        if pretty: ElementTree.indent(root, space='  ')
        return ElementTree.tostring(root, encoding=encoding).decode(encoding) if encoding != 'unicode' else ElementTree.tostring(root, encoding='unicode')

    def json_activity(self, cfg, ctx):
        operation = cfg.get('operation', 'parse')
        mode = str(cfg.get('schemaType') or 'Native JSON').lower()
        if mode not in ('native json', 'generic', 'xsd'): raise ValueError('Unknown JSON schema type')
        source=cfg.get('jsonString',cfg.get('value',cfg.get('source',ctx['last']))) if operation=='parse' else cfg.get('xmlString',cfg.get('value',cfg.get('source',ctx['last'])))
        if isinstance(source, dict) and operation == 'parse': source = next((source[key] for key in ('jsonString','content','body') if key in source and source[key] is not None),source)
        if operation == 'parse':
            if not isinstance(source, (str, bytes, bytearray)): value = source
            else:
                policy = str(cfg.get('duplicateKeyPolicy', 'Last wins')).lower()
                if policy not in ('last wins','first wins','error'):raise ValueError('Unknown duplicate key policy')
                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result and policy == 'error': raise ValueError(f'Duplicate JSON key: {key}')
                        if key not in result or policy != 'first wins': result[key] = value
                    return result
                def invalid_number(value):raise ValueError('Non-finite JSON numbers are not permitted')
                def finite_float(value):
                    number = float(value)
                    return number if math.isfinite(number) else invalid_number(value)
                value = json.loads(source, object_pairs_hook=pairs,parse_constant=invalid_number,parse_float=finite_float)
            if mode != 'native json': return self.parse_bw_json(value, cfg, ctx, mode)
            self.validate_json_if_requested(value, cfg, ctx, 'validateOutput')
            return value
        if mode != 'native json':
            value = self.render_bw_json(source, cfg, ctx, mode)
            return self.serialize_json(value, cfg, pretty_default=False)
        schema = self.configured_schema(cfg, ctx); root_name = self.schema_root_name(schema)
        if cfg.get('_mappedInput') and not any(key in cfg['_mappedInput'] for key in ('value', 'source')):
            source = cfg['_mappedInput']
            if str(cfg.get('rootStyle', 'With root')).lower() == 'anonymous' and len(source) == 1:
                source = next(iter(source.values()))
        elif root_name and root_name in cfg:
            source = {root_name: cfg[root_name]} if str(cfg.get('rootStyle', 'With root')).lower() != 'anonymous' else cfg[root_name]
        self.validate_json_if_requested(source, cfg, ctx, 'validateInput')
        if self.as_bool(cfg.get('omitNulls', False)):
            def without_nulls(value):
                if isinstance(value, dict): return {key: without_nulls(item) for key, item in value.items() if item is not None}
                if isinstance(value, list): return [without_nulls(item) for item in value]
                return value
            source = without_nulls(source)
        return self.serialize_json(source, cfg)

    def serialize_json(self, source, cfg, pretty_default=True):
        indent = int(cfg.get('indent', 2)) if self.as_bool(cfg.get('prettyPrint'), pretty_default) else None
        if indent is not None and not 0<=indent<=16:raise ValueError('JSON indent must be between 0 and 16')
        content = json.dumps(source, indent=indent, allow_nan=False,ensure_ascii=self.as_bool(cfg.get('asciiOnly', False)), separators=None if indent is not None else (',', ':'))
        result = {'content': content, 'jsonString': content}
        if cfg.get('bwOutputEnvelope'): result['bwXml'] = self.render_xml({'jsonString': content}, 'Output')
        return result

    @staticmethod
    def json_root_style(cfg):
        style = str(cfg.get('jsonStyle') or cfg.get('rootStyle') or 'None').lower()
        if style not in ('none', 'with root', 'json with root', 'anonymous', 'anonymous array'): raise ValueError('Unknown JSON root style')
        return style

    @staticmethod
    def array_field(shape):
        fields = {name: field for name, field in shape.get('properties', {}).items() if not name.startswith('@')}
        if len(fields) != 1 or next(iter(fields.values())).get('type') != 'array':
            raise ValueError('Anonymous Array requires exactly one repeating child in the XSD root')
        return next(iter(fields))

    def parse_bw_json(self, value, cfg, ctx, mode):
        from lxml import etree
        schema = self.configured_schema(cfg, ctx) if mode == 'xsd' else None
        bundle = self.schema_bundle(cfg, ctx, schema)
        if mode == 'xsd' and not schema: raise MinaFault('XSD mode requires an output XSD', fault_type='ValidationException')
        style = self.json_root_style(cfg)
        root_name = cfg.get('rootElement') or self.schema_root_name(schema, bundle) or 'root'
        if style in ('with root','json with root'):
            if not isinstance(value, dict) or len(value) != 1: raise ValueError('JSON with Root requires a single root property')
            incoming, value = next(iter(value.items()))
            if schema and cfg.get('rootElement') and not self.as_bool(cfg.get('badgerfish')):
                if incoming != etree.QName(root_name).localname: raise ValueError(f'Unexpected JSON root {incoming!r}')
            else:
                root_name = incoming
        shape = xsd_shape(schema, root_name, bundle) if schema else None
        if style in ('anonymous','anonymous array'):
            if not isinstance(value, list): raise ValueError('Anonymous Array requires a JSON array')
            if shape: value = {self.array_field(shape): value}
        if self.as_bool(cfg.get('useNullForEmptyValues')):
            def null_empty(item, field=None):
                if item == {}: return None
                if isinstance(item, dict):
                    fields = (field or {}).get('properties', {})
                    return {key: null_empty(entry, fields.get(key)) for key, entry in item.items()}
                if isinstance(item, list):
                    # Unwrapped XSD arrays have no distinct container to mark nil.
                    if not item and not field: return None
                    return [null_empty(entry, (field or {}).get('items')) for entry in item]
                return item
            value = null_empty(value, shape)
        validate = bool(schema) and self.as_bool(cfg.get('validateOutput'), True)
        badger = self.as_bool(cfg.get('badgerfish'))
        root = xml_from_value(root_name, value, shape, badger=badger, generic=not schema,
                              ignore=validate and self.as_bool(cfg.get('ignoreAdditionalJsonFields')))
        xml = etree.tostring(root, encoding='unicode')
        if validate: self.validate_xml_document(xml, schema, bundle)
        if mode == 'generic':
            return {'xmlString': xml, 'xml': xml, 'root': root.tag, 'value': value}
        tree = json_from_xml(root, shape)
        result = self.parse_xml(xml)
        result['value'] = tree
        alias = etree.QName(root).localname
        if alias not in {'mediaType', 'xml', 'xmlString', 'root', 'value'}: result[alias] = tree
        return result

    def render_bw_json(self, source, cfg, ctx, mode):
        from lxml import etree
        schema = self.configured_schema(cfg, ctx) if mode == 'xsd' else None
        bundle = self.schema_bundle(cfg, ctx, schema)
        if mode == 'xsd' and not schema: raise MinaFault('XSD mode requires an input XSD', fault_type='ValidationException')
        shape = None
        if isinstance(source, dict) and any(key in source for key in ('xmlString','xml')):
            source = source.get('xmlString') or source.get('xml')
        if isinstance(source, (str, bytes, bytearray)):
            root = xml_document(source)
        else:
            mapped = cfg.get('_mappedInput') or {}
            if mapped and not any(key in mapped for key in ('xmlString','value','source')): source = mapped
            root_name = cfg.get('rootElement') or self.schema_root_name(schema, bundle) or 'root'
            if isinstance(source, dict) and 'root' in source and 'value' in source:
                root_name, source = source['root'], source['value']
            elif isinstance(source, dict) and root_name in source:
                source = source[root_name]
            shape = xsd_shape(schema, root_name, bundle) if schema else None
            root = xml_from_value(root_name, source, shape, tree_input=True, generic=not schema)
        if schema:
            shape = shape or xsd_shape(schema, root.tag, bundle)
            if self.as_bool(cfg.get('validateInput'), True): self.validate_xml_document(etree.tostring(root), schema, bundle)
        badger = self.as_bool(cfg.get('badgerfish'))
        empty = '' if self.as_bool(cfg.get('useEmptyValuesForNull')) else None
        value = json_from_xml(root, shape, badger=badger, infer=not schema and self.as_bool(cfg.get('inferPrimitiveTypes')), empty=empty)
        if self.as_bool(cfg.get('emptyToNull')):
            def empty_to_null(item):
                if item == '' or item == {}: return None
                if isinstance(item, dict): return {key: empty_to_null(entry) for key, entry in item.items()}
                if isinstance(item, list): return [empty_to_null(entry) for entry in item]
                return item
            value = empty_to_null(value)
        style = self.json_root_style(cfg)
        if style in ('with root','json with root'):
            local = etree.QName(root).localname
            return {f'{root.prefix}:{local}' if badger and root.prefix else local: value}
        if style in ('anonymous','anonymous array'):
            if isinstance(value, list) and not shape: return value
            key = self.array_field(shape) if shape else next(iter(value), None) if isinstance(value, dict) and len(value) == 1 else None
            if key is None or not isinstance(value, dict) or not isinstance(value.get(key, []), list):
                raise ValueError('Anonymous Array requires one repeating child or an array')
            return value.get(key, [])
        return value

    def validate_json_if_requested(self, value, cfg, ctx, flag):
        if not self.as_bool(cfg.get(flag, False)): return
        content = self.configured_schema(cfg, ctx)
        if not content: raise MinaFault(f'{flag} requires a project or inline schema in the schema editor', fault_type='ValidationException')
        from .schema_validation import schema_errors
        try:schema=json.loads(content) if isinstance(content,str) else content
        except ValueError as error:raise MinaFault('A valid JSON Schema is required',fault_type='ValidationException') from error
        errors=schema_errors(value,schema)
        if errors: raise MinaFault('JSON schema validation failed: ' + '; '.join(errors), fault_type='ValidationException', details={'errors': errors})

    def flat_data(self, cfg, ctx):
        if cfg.get('dataFormatId'):
            resource = cfg.get('_dataFormatText') or self.schema_content(cfg['dataFormatId'], ctx)
            try:
                shared = json.loads(resource)['dataFormat']
                if not isinstance(shared, dict): raise ValueError()
            except (ValueError, TypeError, KeyError) as error:
                raise MinaFault('Select a Data Format JSON asset with a dataFormat object', fault_type='BadDataFormatException') from error
            cfg = {**{key: value for key, value in shared.items() if key in FORMAT_FIELDS}, **cfg}
        source, delimiter = cfg.get('text', cfg.get('Text', cfg.get('records', cfg.get('Rows', cfg.get('source', ctx['last']))))), str(cfg.get('delimiter', ','))
        parsing = cfg.get('operation') == 'parse'
        fixed = str(cfg.get('format', 'delimited')).lower() in ('fixed', 'fixed width')
        if not fixed and (not delimiter or any(char in delimiter for char in '\r\n"')): raise ValueError('Invalid column separator')
        fields = [item.strip() for item in str(cfg.get('fields') or '').split(',') if item.strip()]
        schema = self.configured_schema(cfg, ctx)
        bundle = self.schema_bundle(cfg, ctx, schema)
        types = [item.strip().lower() for item in str(cfg.get('fieldTypes', '')).split(',') if item.strip()]
        if schema and (not fields or not types):
            schema_fields, schema_types = self.schema_leaf_fields(schema, bundle, cfg.get('rootElement') or '')
            fields = fields or schema_fields
            if not types and schema_types:
                lookup = dict(zip(schema_fields, schema_types))
                types = [lookup.get(field, 'string').lower() for field in fields]
        line_ending = {'lf':'\n','crlf':'\r\n','cr':'\r','auto':'\n'}.get(str(cfg.get('lineSeparator', cfg.get('lineEnding', 'Auto'))).lower(), str(cfg.get('lineEnding', '\n')))
        def typed(value, index):
            value = value.strip() if self.as_bool(cfg.get('trimValues', True)) else value
            kind = types[index] if index < len(types) else 'string'
            if value == '': return None if kind not in ('string','text') else ''
            if kind in ('integer','int','long'): return int(value)
            if kind in ('decimal','number','float','double'):
                number=float(value)
                if not math.isfinite(number):raise ValueError('Non-finite numeric field')
                return number
            if kind in ('boolean','bool'):
                if value.lower() not in ('true','1','yes','y','false','0','no','n'):raise ValueError('Invalid boolean field: '+value)
                return value.lower() in ('true','1','yes','y')
            return value
        def parsed_xml_result(records, names, errors, done, next_record):
            from xml.etree import ElementTree
            def xml_name(value, fallback):
                normalized = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or fallback))
                return normalized if re.match(r'[A-Za-z_]', normalized) else f'_{normalized}'
            root_name = xml_name(cfg.get('rootElement') or self.schema_root_name(schema, bundle), 'records')
            schema_record_name = None
            shape = None
            if schema:
                if isinstance(schema, str) and schema.lstrip().startswith('<'):
                    shape = xsd_shape(schema, root_name, bundle)
                    schema_record_name = next((name for name, field in shape.get('properties', {}).items()
                                               if field.get('type') == 'array'), None)
            record_name = xml_name(cfg.get('recordElement') or schema_record_name, 'record')
            if shape and schema_record_name == record_name and shape.get('xml', {}).get('name') == root_name:
                xml = etree.tostring(xml_from_value(root_name, {record_name: records}, shape, tree_input=True), encoding='unicode')
            else:
                root = ElementTree.Element(root_name)
                for record in records:
                    item = ElementTree.SubElement(root, record_name)
                    for key, value in record.items():
                        child = ElementTree.SubElement(item, xml_name(key, 'field'))
                        if value is not None: child.text = str(value).lower() if isinstance(value, bool) else str(value)
                xml = ElementTree.tostring(root, encoding='unicode')
            return {
                'mediaType': 'application/xml', 'xml': xml, 'xmlString': xml,
                'root': root_name, 'value': {record_name: records},
                'records': records, 'recordCount': len(records),
                'Rows': {'schema': {record_name: records}},
                'ErrorRows': {'error': errors}, 'done': done, 'nextRecord': next_record,
                **({'fields': names} if names else {}),
            }
        if fixed:
            if cfg.get('fieldOffsets'):
                offsets = [tuple(map(int, part.split(':'))) for part in str(cfg['fieldOffsets']).split(',')]
            else:
                offsets, start = [], 0
                for part in str(cfg.get('widths') or '').split(','):
                    if part.strip():
                        end = start + int(part)
                        offsets.append((start, end))
                        start = end
            if (not fields or len(fields) != len(offsets)
                    or any(len(span) != 2 or span[0] < 0 or span[0] >= span[1] for span in offsets)
                    or any(before[1] > after[0] for before, after in zip(sorted(offsets), sorted(offsets)[1:]))):
                raise ValueError('Fixed-width data requires a positive width or a nonoverlapping start:end offset for each field')
            width_total = max(end for _, end in offsets)
            if cfg.get('lineLength') not in (None, ''):
                # The shared format length includes its configured record separator.
                width_configured = int(cfg['lineLength']) - len(line_ending)
                if width_configured < width_total: raise ValueError('Fixed line length is shorter than the configured field offsets plus separator')
                width_total = width_configured
        if parsing:
            file_mode = str(cfg.get('inputSource', 'String')).lower() in ('file', 'file path', 'filepath')
            inputs = source if isinstance(source, dict) else {}
            file_path = cfg.get('fileName') or cfg.get('filePath') or inputs.get('fileName') or inputs.get('filePath') or inputs.get('path') or (source if isinstance(source, str) else '')
            file_encoding = str(cfg.get('fileEncoding') or cfg.get('encoding') or 'utf-8-sig')
            content = inputs.get('text', inputs.get('Text', inputs.get('content', source))) if isinstance(source, dict) else source
            header_chars = int(cfg.get('skipHeaderCharacters') or cfg.get('SkipHeaderCharacters') or 0)
            limit = int(cfg.get('noOfRecords') if cfg.get('noOfRecords') not in (None,'') else -1)
            if header_chars < 0 or limit < -1: raise ValueError('Header characters and record count must be nonnegative (-1 reads all records)')
            if file_mode and not file_path: raise MinaFault('Parse Data requires a file name', fault_type='FileNotFoundException')
            if not file_mode and not isinstance(content, str): raise ValueError('Parse Data requires text input')
            state = ctx.get('formatCursors')
            activity = ctx.get('context', {}).get('activityId')
            automatic = state is not None and activity and cfg.get('startRecord') in (None,'') and not self.as_bool(cfg.get('manualStartRecord')) and limit >= 0
            start = int(cfg.get('startRecord') or 0)
            if start < 0: raise ValueError('Start record must be a zero-based nonnegative record offset')
            try:
                if file_mode:
                    path = Path(str(file_path)).expanduser()
                    info = path.stat()
                    identity = (str(path), file_encoding, info.st_size, info.st_mtime_ns)
                    handle = path.open(encoding=file_encoding, newline='')
                else:
                    identity, handle = content, io.StringIO(content, newline='')
            except FileNotFoundError as error: raise MinaFault(str(error), fault_type='FileNotFoundException') from error
            blank_policy = str(cfg.get('blankLinePolicy') or ('Skip' if self.as_bool(cfg.get('skipBlankLines'), True) else 'Stop')).lower()
            header = not fixed and self.as_bool(cfg.get('header'), True)
            key = (identity, fixed, delimiter, cfg.get('separatorRule'), header_chars, header, blank_policy, tuple(fields))
            previous = state.get(activity) if automatic else None
            if previous and previous[0] != key: previous = None
            if previous: start = previous[1]
            seekable = fixed or len(delimiter) == 1
            with handle:
                if previous and previous[4]:
                    return parsed_xml_result([], previous[3], [], True, start)
                # Chunk skipping to avoid allocating the skipped portion of a large file.
                resume = seekable and previous and previous[2] is not None
                if resume: handle.seek(previous[2])
                remaining = 0 if resume else header_chars
                while remaining:
                    chunk = handle.read(min(remaining, 65536))
                    if not chunk: break
                    remaining -= len(chunk)
                raw_lines = []
                continue_on_error = self.as_bool(cfg.get('continueOnError'))
                if fixed:
                    rows = (line.rstrip('\r\n') for line in iter(handle.readline, ''))
                elif len(delimiter) == 1:
                    def record_lines():
                        for line in iter(handle.readline, ''):
                            raw_lines.append(line)
                            yield line
                    reader = csv.reader(record_lines() if continue_on_error else iter(handle.readline, ''), delimiter=delimiter, strict=True)
                    def csv_rows():
                        while True:
                            raw_lines.clear()
                            row = next(reader, None)
                            if row is None: return
                            yield row
                    rows = csv_rows() if continue_on_error else reader
                else:
                    text = handle.read(64*1024**2+1)
                    if len(text) > 64*1024**2: raise ValueError('Multi-character data input exceeds the 64 MiB limit')
                    rows = self.delimited_rows(text, delimiter, str(cfg.get('separatorRule','single')).lower()=='any-character')
                if blank_policy == 'skip': rows = filter(bool, rows)
                elif blank_policy == 'stop': rows = takewhile(bool, rows)
                names = previous[3] if resume else next(rows, fields) if header else fields
                if not names: raise ValueError('Parse Data requires header fields or configured field names')
                if len(set(names)) != len(names): raise ValueError('Data field names must be unique')
                if not resume: rows = islice(rows, start, None)
                records, errors, consumed = [], [], 0
                strict = self.as_bool(cfg.get('strictColumns'))
                for row in (rows if limit == -1 else islice(rows, limit)):
                    consumed += 1
                    try:
                        if fixed:
                            if strict and len(row) != width_total: raise ValueError(f'Fixed-width line length {len(row)} does not match {width_total}')
                            record = {}
                            for index, (name, (begin, end)) in enumerate(zip(fields, offsets)):
                                value=row[begin:end];fill=str(cfg.get('fillCharacter',' ') or ' ')[0]
                                if index<len(types) and types[index] in ('integer','int','long','decimal','number','float','double'):
                                    value=value.lstrip(fill) or ('0' if fill=='0' else '')
                                else:value=value.rstrip(fill)
                                record[name]=typed(value,index)
                        else:
                            if strict and len(row) != len(names): raise ValueError(f'Column count {len(row)} does not match schema field count {len(names)}')
                            record = {name: typed(row[index] if index < len(row) else '', index) for index, name in enumerate(names)}
                        records.append(record)
                    except ValueError as error:
                        if not continue_on_error: raise
                        raw = row if fixed else ''.join(raw_lines).rstrip('\r\n') if raw_lines else delimiter.join(row)
                        errors.append({'recordNumber': start + consumed, 'message': str(error), 'raw': raw})
                position = handle.tell() if seekable and automatic else None
                try: done = next(rows, None) is None
                except (csv.Error, ValueError):
                    if limit < 0 or consumed != limit: raise
                    done = False  # Surface malformed data when the next batch actually reads it.
            result = parsed_xml_result(records, names, errors, done, start + consumed)
            if automatic: state[activity] = (key, start + consumed, position, names, done)
            return result
        if isinstance(source, dict):
            if 'records' in source: source = source['records']
            elif 'Rows' in source or 'Rows' in cfg:
                source = source.get('Rows', source)
                if isinstance(source, dict): source = source.get('schema', source)
            if isinstance(source, dict) and len(source) == 1:
                nested = next(iter(source.values()))
                if isinstance(nested, list): source = nested
        records = source if isinstance(source, list) else [source]
        if any(not isinstance(record, dict) for record in records): raise ValueError('Render Data requires record objects')
        if fixed:
            fill = str(cfg.get('fillCharacter', ' ') or ' ')[0]
            def fixed_field(record, name, width, index):
                value = '' if record.get(name) is None else str(record.get(name))
                if self.as_bool(cfg.get('strictColumns',False)) and len(value)>width:raise ValueError('Value exceeds fixed field width: '+name)
                value = value[:width]
                return value.rjust(width, fill) if index < len(types) and types[index] in ('integer','int','long','decimal','number','float','double') else value.ljust(width, fill)
            def fixed_line(record):
                line = [fill] * width_total
                for index, (name, (begin, end)) in enumerate(zip(fields, offsets)):
                    line[begin:end] = fixed_field(record, name, end - begin, index)
                return ''.join(line)
            content = line_ending.join(fixed_line(record) for record in records)
            if self.as_bool(cfg.get('includeFinalLineSeparator', False)): content += line_ending
            return {'content': content, 'text':content, 'Text':content, 'recordCount': len(records)}
        names = fields or list(records[0].keys() if records else [])
        if len(delimiter) == 1:
            output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=names, delimiter=delimiter, lineterminator=line_ending)
            if self.as_bool(cfg.get('header', True)): writer.writeheader()
            writer.writerows(records); content = output.getvalue()
            if not self.as_bool(cfg.get('includeFinalLineSeparator', True)): content = content.removesuffix(line_ending)
        else:
            any_character=str(cfg.get('separatorRule','single')).lower()=='any-character'
            separator=delimiter[0] if any_character and not cfg.get('dataFormatId') else delimiter
            def quote(value):
                value='' if value is None else str(value)
                needs_quote=any(char in value for char in ('"','\r','\n')) or (any(char in value for char in delimiter) if any_character else delimiter in value)
                return '"'+value.replace('"','""')+'"' if needs_quote else value
            rows = ([separator.join(quote(name) for name in names)] if self.as_bool(cfg.get('header', True)) else []) + [separator.join(quote(record.get(name)) for name in names) for record in records]
            content = line_ending.join(rows) + (line_ending if self.as_bool(cfg.get('includeFinalLineSeparator', False)) else '')
        return {'content': content,'text':content, 'Text':content, 'recordCount': len(records), 'fields':names}


def execute_format(kind,operation,cfg,payload,cursors=None,activity_id=None):
    formats=DataFormats();cfg={**cfg,'operation':operation}
    ctx={'last':payload, 'formatCursors':cursors, 'context':{'activityId':activity_id}}
    return formats.run_format(kind,operation,cfg,ctx)
