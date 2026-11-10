"""Convert BusinessWorks XML Data Format resources into portable project assets."""
import json
import re
from hashlib import sha256
from pathlib import PurePosixPath
from uuid import uuid4

from lxml import etree
from .xsd_catalog import XS, asset_path

SUFFIXES = ('.dataformat', '.dataformatresource', '.dataformatsharedresource')
XSI_TYPE = '{http://www.w3.org/2001/XMLSchema-instance}type'
PROFILES = ('local', 'dev', 'qa', 'pre', 'production')
PROPERTY_PREFIX = 'bw.dataFormat.'


def key(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def local(node):
    return etree.QName(node).localname


def property_scope(path):
    parts = PurePosixPath(path).parts[:-1]
    boundary = next((i for i, part in enumerate(parts) if part.lower() in ('resources', 'meta-inf', 'profiles')), len(parts))
    return '/'.join(parts[:boundary])


def property_name(value):
    value = value.strip()
    # EAR profile entries can qualify a module property as //Module///Group/Name.
    qualified = re.fullmatch(r'//([^/]+)///(.+)', value)
    module, name = qualified.groups() if qualified else ('', value.lstrip('/'))
    if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name):
        raise ValueError('unsupported BusinessWorks module-property name')
    return module, name


def profile_values(document):
    for entry in document.iter():
        if not isinstance(entry.tag, str) or key(local(entry)) != 'globalvariable': continue
        fields = {key(local(child)): child.text or '' for child in entry if isinstance(child.tag, str)}
        if 'name' not in fields or 'value' not in fields: continue
        try: module, name = property_name(fields['name'])
        except ValueError: continue
        kind = fields.get('type', 'String').strip().lower().split(':')[-1]
        secret = kind in ('password', 'encrypted') or fields.get('ispassword','').lower() == 'true' or fields.get('encrypted','').lower() == 'true'
        yield module, name, None if secret else fields['value'], kind


def data_format_property(path, reference, fallback, profiles):
    requested, name = property_name(reference)
    scope = property_scope(path)
    module = requested or PurePosixPath(scope).name
    prefix = re.sub(r'[^A-Za-z0-9_.-]+', '-', module) or 'standalone'
    readable = name.replace('/', '.')
    digest = sha256(f'{requested or scope}\0{name}'.encode()).hexdigest()[:10]
    property_key = f'{PROPERTY_PREFIX}{prefix}.{readable}.{digest}'
    defaults = {}
    for environment in ('default', *PROFILES):
        candidates = []
        for profile_path, profile, entries in profiles:
            if profile != environment: continue
            profile_scope = property_scope(profile_path)
            for owner, entry, value, kind in entries:
                if entry != name or owner and owner != module: continue
                if owner:
                    score = 3
                elif (not requested and profile_scope == scope) or (
                        requested and profile_scope and PurePosixPath(profile_scope).name == requested):
                    score = 2
                elif not requested and not profile_scope:
                    score = 1
                else:
                    continue
                candidates.append((score, value, kind))
        if candidates:
            best = max(score for score, _, _ in candidates)
            selected = {(value, kind) for score, value, kind in candidates if score == best}
            if len(selected) != 1: raise ValueError(f'ambiguous module property {reference!r} in profile {environment}')
            value, kind = selected.pop()
            if value is None or kind != 'string':
                raise ValueError(f'Data Format separator requires a non-secret string module property: {reference}')
            defaults[environment] = value
    if fallback and fallback.strip() in {reference, name, '/' + name, '${' + reference + '}', '%%' + reference + '%%'}:
        fallback = ''
    default = defaults.get('default', fallback) or ''
    return property_key, {environment: defaults.get(environment, default) for environment in PROFILES}


def layout_assets(document, path, schemas, profiles=()):
    """Read direct XML and XMI named-resource layouts without opening references."""
    suffix = PurePosixPath(path).suffix
    name = PurePosixPath(path).stem
    kind = key(local(document))
    config = next((node for node in document if isinstance(node.tag, str) and key(local(node)) == 'configuration'), document)
    declared = key(config.get(XSI_TYPE, '').split(':')[-1])
    if 'dataformat' not in kind and 'dataformat' not in declared:
        raise ValueError(f'{name}: expected a BusinessWorks Data Format XML resource')
    nodes = []
    embedded = []
    bindings = []
    def visit(node):
        if not isinstance(node.tag, str): return
        if node.tag == XS + 'schema':
            embedded.append(node)
            return
        if key(local(node)) in ('substitutionbindings', 'substitutionbinding', 'modulepropertybinding'):
            bindings.append(node)
            return
        nodes.append(node)
        for child in node: visit(child)
    visit(config)

    def values(node):
        result = {key(etree.QName(k).localname): v for k, v in node.attrib.items() if not k.startswith('{')}
        if node.text and node.text.strip(): result.setdefault(key(local(node)), node.text.strip())
        if 'value' in result: result.setdefault(key(local(node)), result['value'])
        for child in node:
            if isinstance(child.tag, str) and not len(child) and child.text is not None:
                result.setdefault(key(local(child)), child.text if key(local(child)) in ('delimiter','colseparator','columnseparator','fillwith','fillcharacter') else child.text.strip())
        return result

    settings = {}
    for node in nodes: settings.update(values(node))
    def get(*names, default=None):
        return next((settings[key(name)] for name in names if key(name) in settings), default)
    mappings, properties = {}, {}
    for binding in bindings:
        field = binding.get('template') or binding.get('field') or ''
        prop = binding.get('propName') or binding.get('propertyName') or ''
        if key(field) not in ('colseparator', 'columnseparator', 'delimiter') or not prop or len(binding):
            raise ValueError(f'{name}: unsupported Data Format module-property binding on {field or "(unknown field)"}')
        target = 'formatOptions.delimiter'
        if target in mappings:
            raise ValueError(f'{name}: multiple module-property bindings for the column separator')
        identifier, defaults = data_format_property(path, prop, get('colSeparator','columnSeparator','delimiter'), profiles)
        mappings[target] = '${properties.' + identifier + '}'
        properties[identifier] = defaults
    layout = {'header': False, 'includeFinalLineSeparator': True}
    form = key(get('formatType','dataFormatType','format','type', default=''))
    if 'fix' in form:
        layout['format'] = 'fixed'
    elif 'delim' in form or 'separator' in form or (not form and (mappings or get('colSeparator','columnSeparator','delimiter') is not None)):
        layout['format'] = 'delimited'
    else:
        raise ValueError(f'{name}: unrecognized Data Format type {form!r}')
    line = get('lineSeparator','recordSeparator', default='New Line')
    newline = {'newline':'LF','lf':'LF','linefeed':'LF','carriagereturn':'CR','cr':'CR','crlf':'CRLF',
               'carriagereturnlinefeed':'CRLF','carriagereturnlinefeedwindows':'CRLF','windows':'CRLF',
               'unix':'LF','mac':'CR','none':'Auto','auto':'Auto'}.get(key(line))
    newline = {'\n':'LF','\r':'CR','\r\n':'CRLF','\\n':'LF','\\r':'CR','\\r\\n':'CRLF'}.get(line, newline)
    if not newline: raise ValueError(f'{name}: unsupported line separator {line!r}')
    layout['lineSeparator'] = newline
    if layout['format'] == 'delimited':
        delimiter = get('colSeparator','columnSeparator','delimiter')
        if not delimiter and not mappings: raise ValueError(f'{name}: column separator is missing')
        layout['delimiter'] = '' if mappings else {'\\t':'\t','TAB':'\t'}.get(delimiter, delimiter)
        rule = key(get('colSeparatorParseRule','columnSeparatorParseRule','separatorRule', default='single'))
        if rule in ('single','singlecolumnseparator','treatallcharactersasone','treatallcharactersenteredasasinglecolumnseparatorstring','allcharacters'):
            layout['separatorRule'] = 'single'
        elif 'each' in rule or 'any' in rule:
            layout['separatorRule'] = 'any-character'
        else: raise ValueError(f'{name}: unsupported column separator rule {rule!r}')
    else:
        if mappings: raise ValueError(f'{name}: fixed-width layouts do not have a column separator')
        fill = get('fillWith','fillCharacter','fill', default='Space')
        layout['fillCharacter'] = {'space':' ', 'dash':'-'}.get(fill.lower(), fill)
        if len(layout['fillCharacter']) != 1: raise ValueError(f'{name}: expected one fill character')
        length = get('lineLength','recordLength')
        if length is not None: layout['lineLength'] = int(length)
        columns = []
        for node in nodes:
            if key(local(node)) not in ('field','fieldoffset','fieldoffsets','columnoffset','columnoffsets','column'): continue
            values_here = values(node)
            start = next((values_here[k] for k in ('startoffset','start','startingoffset','begin') if k in values_here), None)
            end = next((values_here[k] for k in ('endoffset','end','endingoffset') if k in values_here), None)
            if start is None and end is None: continue
            field = next((values_here[k] for k in ('fieldname','name','columnname','elementname') if k in values_here), '')
            if start is None or end is None or not re.fullmatch(r'@?[\w.-]+', field):
                raise ValueError(f'{name}: invalid fixed-width column')
            columns.append((field, int(start), int(end)))
        if not columns or len({field for field, _, _ in columns}) != len(columns):
            raise ValueError(f'{name}: fixed-width columns are missing or duplicated')
        ordered = sorted(columns, key=lambda item: item[1])
        if any(start < 0 or end <= start for _, start, end in ordered) or any(a[2] > b[1] for a, b in zip(ordered, ordered[1:])):
            raise ValueError(f'{name}: invalid or overlapping fixed-width offsets')
        layout['fields'] = ','.join(field for field, _, _ in columns)
        layout['fieldOffsets'] = ','.join(f'{start}:{end}' for _, start, end in columns)
    if len(embedded) > 1: raise ValueError(f'{name}: more than one embedded XSD')
    created = []
    schema_link = get('schemaLocation','schemaFile','schemaPath','schemaRef','schema')
    root_ref = get('schemaElementQName','schemaQName','rootElementQName','schemaElement','rootElement')
    if embedded:
        schema = {'id': f'bw-xsd-{uuid4().hex}', 'name': str(PurePosixPath(path).with_suffix(suffix + '.xsd')),
                  'content': etree.tostring(embedded[0], encoding='unicode')}
        schema['source_path'] = schema['name']
        created.append(schema)
    elif schema_link and not re.fullmatch(r'[\w.-]+:[\w.-]+', schema_link):
        ref = schema_link.split('#', 1)[0]
        root_relative = asset_path(ref, str(PurePosixPath(path).parent))
        matches = [schema for schema in schemas if (schema.get('source_path') or schema['name']) == root_relative]
        if not matches:
            ref = asset_path(ref)
            matches = [schema for schema in schemas if (schema.get('source_path') or schema['name']) == ref
                       or (schema.get('source_path') or schema['name']).endswith('/' + ref)]
        if len(matches) != 1: raise ValueError(f'{name}: schema reference is missing or ambiguous: {ref}')
        schema = matches[0]
    else:
        schema = None
        root_ref = root_ref or schema_link
        if root_ref:
            if root_ref.startswith('{'):
                qname = etree.QName(root_ref)
                namespace, root_name = qname.namespace, qname.localname
            else:
                prefix, separator, root_name = root_ref.partition(':')
                if not separator: root_name, prefix = prefix, None
                namespace = next((node.nsmap[prefix] for node in nodes if prefix in node.nsmap), None)
                if prefix and namespace is None: raise ValueError(f'{name}: undefined QName prefix: {prefix}')
            from .data_formats import DataFormats
            matches = []
            for candidate in schemas:
                if not candidate['name'].lower().endswith('.xsd'): continue
                definition = etree.fromstring(DataFormats.safe_xml(candidate['content']),
                    etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
                if (not namespace or definition.get('targetNamespace') == namespace) and any(
                        item.get('name') == root_name for item in definition.findall(XS + 'element')):
                    matches.append(candidate)
            if len(matches) != 1: raise ValueError(f'{name}: row schema QName is missing or ambiguous: {root_ref}')
            schema = matches[0]
    if schema:
        layout['schemaId'] = schema['id']
        if root_ref: layout['rootElement'] = root_ref.rsplit('}', 1)[-1] if root_ref.startswith('{') else root_ref.rsplit(':', 1)[-1]
    if not schema and not layout.get('fields'):
        fields = get('fields', 'fieldNames')
        if not fields: raise ValueError(f'{name}: include the row XSD or declare the field names')
        layout['fields'] = fields
    asset = {'id': f'bw-data-format-{uuid4().hex}', 'name': str(PurePosixPath(path).with_suffix(suffix + '.json')),
             'content': json.dumps({'dataFormat': layout, **({'inputMappings': mappings} if mappings else {})}, ensure_ascii=False, indent=2)}
    return asset, created, mappings, properties
