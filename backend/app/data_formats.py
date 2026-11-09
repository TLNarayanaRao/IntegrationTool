"""Shared XML, JSON and delimited/fixed data activities for every runtime."""
import base64,csv,io,json,re,math
import threading
from functools import lru_cache
from pathlib import Path
from .faults import MinaFault
from .mapper import validate_output

@lru_cache(maxsize=8)
def compiled_xsd(schema):
    from lxml import etree
    class Offline(etree.Resolver):
        def resolve(self,url,public_id,context):raise ValueError('External XSD references are disabled; supply a self-contained schema')
    raw=DataFormats.safe_xml(schema)
    if len(raw)>8*1024**2:raise ValueError('XSD exceeds the 8 MiB schema limit')
    parser=etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=False)
    parser.resolvers.add(Offline())
    return etree.XMLSchema(etree.fromstring(raw,parser)),threading.Lock()

class DataFormats:
    def run_format(self,kind,operation,cfg,ctx):
        try:
            if kind=='json':return self.json_activity(cfg,ctx)
            if kind=='flat':return self.flat_data(cfg,ctx)
            return self.parse_xml_activity(cfg,ctx) if operation=='parse' else self.render_xml_activity(cfg,ctx)
        except MinaFault:raise
        except (ValueError,TypeError,SyntaxError,UnicodeError,LookupError,OSError,csv.Error) as error:
            names={'xml':('XMLParseException','XMLRenderException'),'json':('JSONParserException','JSONRenderException'),'flat':('ParseDataException','RenderDataException')}
            raise MinaFault(str(error),fault_type=names[kind][operation!='parse'],cause=type(error).__name__) from error

    @staticmethod
    def safe_xml(value):
        raw=value.encode('utf-8') if isinstance(value,str) else bytes(value)
        if len(raw)>64*1024**2:raise ValueError('XML exceeds the 64 MiB input limit')
        if re.search(br'<!\s*(DOCTYPE|ENTITY)\b',raw.replace(b'\x00',b''),re.I):raise ValueError('XML DTDs and entity declarations are disabled')
        return raw

    @staticmethod
    def validate_xml_document(value,schema):
        from lxml import etree
        try:
            validator,lock=compiled_xsd(schema)
            parser=etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=False)
            document=etree.fromstring(DataFormats.safe_xml(value),parser)
            with lock:
                if not validator.validate(document):raise ValueError('; '.join(str(error.message) for error in list(validator.error_log)[:10]))
        except (ValueError,etree.Error) as error:raise MinaFault('XSD validation failed: '+str(error),fault_type='ValidationException') from error
    @staticmethod
    def as_bool(value,default=False):
        return default if value is None else str(value).lower() in ('true','1','yes','on')

    @staticmethod
    def delimited_rows(text,delimiter,any_character=False):
        rows=[];row=[];field=[];quoted=False;closed=False;index=0
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
                row.append(''.join(field));rows.append([] if blank else row);row=[];field=[];closed=False
                index+=2 if char=='\r' and text[index:index+2]=='\r\n' else 1;continue
            if closed:raise ValueError('Unexpected data after a quoted field')
            if char=='"' and not field:quoted=True
            else:field.append(char)
            index+=1
        if quoted:raise ValueError('Unterminated quoted field')
        if row or field or closed:row.append(''.join(field));rows.append(row)
        return rows

    @staticmethod
    def schema_content(schema_id, ctx):
        project = ctx.get('project')
        schema = next((item for item in getattr(project, 'schemas', []) if item.id == schema_id or item.name == schema_id), None) if project and schema_id else None
        return schema.content if schema else ''

    def configured_schema(self, cfg, ctx):
        return cfg.get('schemaText') or self.schema_content(cfg.get('schemaId'), ctx)

    @staticmethod
    def schema_root_name(schema):
        if not schema: return ''
        try:
            document = schema if isinstance(schema,dict) else json.loads(schema)
            return document.get('title') or next(iter((document.get('properties') or {}).keys()), '')
        except (ValueError, TypeError):
            pass
        from xml.etree import ElementTree
        try: root = ElementTree.fromstring(schema)
        except (ElementTree.ParseError, TypeError): return ''
        return next((item.attrib.get('name') for item in list(root) if item.tag.rsplit('}', 1)[-1] == 'element' and item.attrib.get('name')), '')

    @staticmethod
    def schema_leaf_fields(schema):
        if not schema: return [], []
        try:
            document = schema if isinstance(schema,dict) else json.loads(schema); fields = []
            def walk(node):
                properties = node.get('properties', {}) if isinstance(node, dict) else {}
                for name, child in properties.items():
                    if isinstance(child, dict) and child.get('properties'): walk(child)
                    else: fields.append((name, child.get('type', 'string') if isinstance(child, dict) else 'string'))
            walk(document)
            return [item[0] for item in fields], [item[1] for item in fields]
        except (ValueError, TypeError):
            pass
        from xml.etree import ElementTree
        try: document = ElementTree.fromstring(schema)
        except (ElementTree.ParseError, TypeError): return [], []
        fields = []
        def local(element): return element.tag.rsplit('}', 1)[-1]
        def child_elements(element):
            result = []
            for child in list(element):
                if local(child) == 'element': result.append(child)
                elif local(child) in ('complexType', 'sequence', 'all', 'choice', 'group', 'extension'): result.extend(child_elements(child))
            return result
        def walk(element):
            children = child_elements(element)
            if children:
                for child in children: walk(child)
            elif local(element) == 'element' and element.attrib.get('name'):
                fields.append((element.attrib['name'], element.attrib.get('type', 'string').split(':')[-1]))
            for child in element.iter():
                if local(child) == 'attribute' and child.attrib.get('name'): fields.append((child.attrib['name'], child.attrib.get('type', 'string').split(':')[-1]))
        roots = [item for item in list(document) if local(item) == 'element']
        for root in roots: walk(root)
        unique = list(dict.fromkeys(fields))
        return [item[0] for item in unique], [item[1] for item in unique]

    def parse_xml_activity(self, cfg, ctx):
        style = str(cfg.get('inputStyle', 'Text')).lower()
        source = cfg.get('xmlString', cfg.get('source', ctx['last']))
        if style in ('binary','dynamic') and cfg.get('xmlBinary') not in (None, ''): source = cfg.get('xmlBinary')
        if isinstance(source, dict): source = source.get('bytes') or source.get('binaryContent') or source.get('xmlString') or source.get('content') or source.get('body') or ''
        if isinstance(source, str) and (style == 'binary' or style=='dynamic' and cfg.get('xmlBinary') not in (None,'')):
            source = base64.b64decode(source,validate=True)
        if isinstance(source, (bytes,bytearray)) and (cfg.get('forceEncoding') or cfg.get('encoding')):source=bytes(source).decode(cfg.get('forceEncoding') or cfg['encoding'])
        parsed = self.parse_xml(source)
        if self.as_bool(cfg.get('validateOutput', False)):
            schema = self.configured_schema(cfg, ctx)
            if not schema: raise MinaFault('Validate Output requires a project or inline XSD in Output Editor', fault_type='ValidationException')
            self.validate_xml_document(parsed['xml'],schema)
        return parsed

    def render_xml_activity(self, cfg, ctx):
        schema = self.configured_schema(cfg, ctx)
        root_name = self.schema_root_name(schema) or cfg.get('rootElement') or 'root'
        source = cfg.get(root_name, cfg.get('value', cfg.get('source', ctx['last'])))
        if isinstance(source, dict) and root_name in source and not ('root' in source and 'value' in source): source = source[root_name]
        if self.as_bool(cfg.get('validateInput', False)):
            if not schema: raise MinaFault('Validate Input requires a project or inline XSD in Input Editor', fault_type='ValidationException')
        encoding = cfg.get('encoding') or 'UTF-8'
        content = self.render_xml(source, root_name, 'unicode', pretty=self.as_bool(cfg.get('prettyPrint', False)))
        if self.as_bool(cfg.get('validateInput', False)):self.validate_xml_document(content,schema)
        if not self.as_bool(cfg.get('suppressXmlDeclaration', False)): content = f'<?xml version="1.0" encoding="{encoding}"?>\n{content}'
        if str(cfg.get('outputStyle', 'Text')).lower() == 'binary':
            raw = content.encode(encoding); return {'binaryContent': base64.b64encode(raw).decode(), 'bytes': base64.b64encode(raw).decode(), 'byteCount': len(raw), 'encoding': encoding, 'content': None}
        return {'content': content, 'xmlString': content, 'encoding': encoding}

    @staticmethod
    def validate_xml_root(root_name, schema):
        from xml.etree import ElementTree
        try: schema_root = ElementTree.fromstring(schema)
        except ElementTree.ParseError as exc: raise MinaFault(f'Selected XSD is invalid: {exc}', fault_type='ValidationException') from exc
        expected = next((item.attrib.get('name') for item in list(schema_root) if item.tag.rsplit('}',1)[-1] == 'element' and item.attrib.get('name')), None)
        actual = str(root_name or '').rsplit('}',1)[-1]
        if expected and actual != expected: raise MinaFault(f'XML root {actual!r} does not match XSD root {expected!r}', fault_type='ValidationException', details={'expectedRoot':expected,'actualRoot':actual})

    @staticmethod
    def xml_element_value(root, *, local_names=False):
        def field_name(name):
            return name.rsplit('}', 1)[-1] if local_names else name

        def convert(element):
            children = list(element); result = {'@' + field_name(key): value for key, value in element.attrib.items()}
            if not children:
                text = element.text or ''
                if result:
                    if text: result['#text'] = text
                    return result
                return text
            mixed=bool(element.text and element.text.strip() or any(child.tail and child.tail.strip() for child in children))
            ordered=[{'#text':element.text}] if mixed and element.text else []
            for child in children:
                name = field_name(child.tag)
                value = convert(child)
                if mixed:
                    ordered.append({name:value})
                    if child.tail:ordered.append({'#text':child.tail})
                if name in result:
                    if not isinstance(result[name], list): result[name] = [result[name]]
                    result[name].append(value)
                else:
                    result[name] = value
            if element.text and element.text.strip(): result['#text'] = element.text.strip()
            if mixed:result['#content']=ordered
            return result
        return convert(root)

    def parse_xml(self, source):
        from xml.etree import ElementTree
        if isinstance(source, dict): source = source.get('content') or source.get('body') or ''
        root = ElementTree.fromstring(self.safe_xml(source))
        value = self.xml_element_value(root)
        xml = ElementTree.tostring(root, encoding='unicode')
        return {
            'mediaType': 'application/xml',
            'xml': xml,
            'xmlString': xml,
            'root': root.tag,
            'value': value,
            root.tag.rsplit('}', 1)[-1]: value,
        }

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
        source=cfg.get('jsonString',cfg.get('value',cfg.get('source',ctx['last']))) if operation=='parse' else cfg.get('value',cfg.get('source',ctx['last']))
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
                value = json.loads(source, object_pairs_hook=pairs,parse_constant=invalid_number)
            self.validate_json_if_requested(value, cfg, ctx, 'validateOutput')
            return value
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
        indent = int(cfg.get('indent', 2)) if self.as_bool(cfg.get('prettyPrint', True)) else None
        if indent is not None and not 0<=indent<=16:raise ValueError('JSON indent must be between 0 and 16')
        content = json.dumps(source, indent=indent, allow_nan=False,ensure_ascii=self.as_bool(cfg.get('asciiOnly', False)), separators=None if indent is not None else (',', ':'))
        return {'content': content, 'jsonString': content}

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
        source, delimiter = cfg.get('text', cfg.get('records', cfg.get('source', ctx['last']))), str(cfg.get('delimiter', ','))
        if cfg.get('operation') == 'parse' and str(cfg.get('inputSource', 'String')).lower() in ('file', 'file path', 'filepath'):
            file_path = cfg.get('filePath') or (source.get('path') if isinstance(source, dict) else source)
            if not file_path:
                raise MinaFault('Parse Data file input requires a file path', fault_type='ParseDataException')
            try:
                with Path(str(file_path)).expanduser().open(encoding=str(cfg.get('fileEncoding') or cfg.get('encoding') or 'utf-8-sig'),newline='') as handle:source=handle.read(64*1024**2+1)
                if len(source)>64*1024**2:raise ValueError('Data input exceeds the 64 MiB limit')
            except (OSError, UnicodeError) as exc:
                raise MinaFault(f'Unable to read Parse Data input file {file_path!s}: {exc}', fault_type='ParseDataException', details={'filePath': str(file_path)}) from exc
        fields = [item.strip() for item in cfg.get('fields', '').split(',') if item.strip()]
        types = [item.strip().lower() for item in str(cfg.get('fieldTypes', '')).split(',') if item.strip()]
        if not fields:
            schema_fields, schema_types = self.schema_leaf_fields(self.configured_schema(cfg, ctx))
            if schema_fields: fields = schema_fields
            if not types and schema_types: types = [item.lower() for item in schema_types]
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
        def parsed_xml_result(records, names=None):
            from xml.etree import ElementTree
            def xml_name(value, fallback):
                normalized = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or fallback))
                return normalized if re.match(r'[A-Za-z_]', normalized) else f'_{normalized}'
            schema = self.configured_schema(cfg, ctx)
            root_name = xml_name(cfg.get('rootElement') or self.schema_root_name(schema), 'records')
            schema_record_name = None
            if schema:
                try:
                    schema_document = ElementTree.fromstring(schema)
                    schema_elements = [item for item in schema_document.iter() if item.tag.rsplit('}', 1)[-1] == 'element' and item.attrib.get('name')]
                    schema_record_name = schema_elements[1].attrib['name'] if len(schema_elements) > 1 else None
                except (ElementTree.ParseError, TypeError):
                    pass
            record_name = xml_name(cfg.get('recordElement') or schema_record_name, 'record')
            root = ElementTree.Element(root_name)
            for record in records:
                item = ElementTree.SubElement(root, record_name)
                values = record if isinstance(record, dict) else {'value': record}
                for key, value in values.items():
                    child = ElementTree.SubElement(item, xml_name(key, 'field'))
                    if value is not None: child.text = str(value).lower() if isinstance(value, bool) else str(value)
            xml = ElementTree.tostring(root, encoding='unicode')
            return {
                'mediaType': 'application/xml', 'xml': xml, 'xmlString': xml,
                'root': root_name, 'value': {record_name: records},
                'records': records, 'recordCount': len(records),
                **({'fields': names} if names else {}),
            }
        if str(cfg.get('format', 'delimited')).lower() == 'fixed':
            widths = [int(item.strip()) for item in cfg.get('widths', '').split(',') if item.strip()]
            if not fields or len(fields) != len(widths) or any(width<=0 for width in widths): raise ValueError('Fixed-width data requires matching field names and positive widths')
            if cfg.get('operation') == 'parse':
                records = []
                for line in str(source).splitlines():
                    if not line and self.as_bool(cfg.get('skipBlankLines', True)): continue
                    if self.as_bool(cfg.get('strictColumns', False)) and len(line) != sum(widths): raise MinaFault(f'Fixed-width line length {len(line)} does not match configured width {sum(widths)}', fault_type='ParseDataException')
                    offset, record = 0, {}
                    for index, (name, width) in enumerate(zip(fields, widths)):
                        value=line[offset:offset+width];fill=str(cfg.get('fillCharacter',' ') or ' ')[0]
                        if index<len(types) and types[index] in ('integer','int','long','decimal','number','float','double'):
                            value=value.lstrip(fill) or ('0' if fill=='0' else '')
                        else:value=value.rstrip(fill)
                        record[name],offset=typed(value,index),offset+width
                    records.append(record)
                return parsed_xml_result(records, fields)
            records = source.get('records', source) if isinstance(source, dict) else source
            if not isinstance(records, list): records = [records]
            fill = str(cfg.get('fillCharacter', ' ') or ' ')[0]
            def fixed_field(record, name, width, index):
                value = '' if record.get(name) is None else str(record.get(name))
                if self.as_bool(cfg.get('strictColumns',False)) and len(value)>width:raise ValueError('Value exceeds fixed field width: '+name)
                value = value[:width]
                return value.rjust(width, fill) if index < len(types) and types[index] in ('integer','int','long','decimal','number','float','double') else value.ljust(width, fill)
            content = line_ending.join(''.join(fixed_field(record, name, width, index) for index, (name, width) in enumerate(zip(fields, widths))) for record in records)
            if self.as_bool(cfg.get('includeFinalLineSeparator', False)): content += line_ending
            return {'content': content, 'text':content,'recordCount': len(records)}
        if cfg.get('operation') == 'parse':
            text = str(source.get('content', source) if isinstance(source, dict) else source)
            if len(delimiter) == 1:
                rows = list(csv.reader(io.StringIO(text,newline=''), delimiter=delimiter,strict=True))
                if self.as_bool(cfg.get('skipBlankLines', True)):rows=[row for row in rows if row]
            else:
                rows=self.delimited_rows(text,delimiter,str(cfg.get('separatorRule','single')).lower()=='any-character')
                if self.as_bool(cfg.get('skipBlankLines',True)):rows=[row for row in rows if row]
            if self.as_bool(cfg.get('header', True)) and rows: names, rows = rows[0], rows[1:]
            else: names = fields
            if not names: raise MinaFault('Parse Data requires header fields or configured field names', fault_type='ParseDataException')
            if len(set(names))!=len(names):raise ValueError('Data field names must be unique')
            records = []
            for row in rows:
                if self.as_bool(cfg.get('strictColumns', False)) and len(row) != len(names): raise MinaFault(f'Column count {len(row)} does not match schema field count {len(names)}', fault_type='ParseDataException')
                records.append({name: typed(row[index] if index < len(row) else '', index) for index, name in enumerate(names)})
            return parsed_xml_result(records, names)
        records = source.get('records', source) if isinstance(source, dict) else source
        if not isinstance(records, list): records = [records]
        names = fields or list(records[0].keys() if records else [])
        if len(delimiter) == 1:
            output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=names, delimiter=delimiter, lineterminator=line_ending)
            if self.as_bool(cfg.get('header', True)): writer.writeheader()
            writer.writerows(records); content = output.getvalue()
            if not self.as_bool(cfg.get('includeFinalLineSeparator', True)): content = content.removesuffix(line_ending)
        else:
            any_character=str(cfg.get('separatorRule','single')).lower()=='any-character'
            separator=delimiter[0] if any_character else delimiter
            def quote(value):
                value='' if value is None else str(value)
                needs_quote=any(char in value for char in ('"','\r','\n')) or (any(char in value for char in delimiter) if any_character else delimiter in value)
                return '"'+value.replace('"','""')+'"' if needs_quote else value
            rows = ([separator.join(quote(name) for name in names)] if self.as_bool(cfg.get('header', True)) else []) + [separator.join(quote(record.get(name)) for name in names) for record in records]
            content = line_ending.join(rows) + (line_ending if self.as_bool(cfg.get('includeFinalLineSeparator', False)) else '')
        return {'content': content,'text':content, 'recordCount': len(records), 'fields':names}


def execute_format(kind,operation,cfg,payload):
    formats=DataFormats();cfg={**cfg,'operation':operation};ctx={'last':payload}
    return formats.run_format(kind,operation,cfg,ctx)
