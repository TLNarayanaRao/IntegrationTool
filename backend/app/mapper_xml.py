"""Offline XML bindings for the portable Mapper."""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

from lxml import etree


XSL = '{http://www.w3.org/1999/XSL/Transform}'
BW_FUNCTIONS = 'http://www.tibco.com/bw/xslt/custom-functions'
BW_RUNTIME_FUNCTIONS = 'http://www.tibco.com/bw/xpath/bw-custom-functions'
BW_PROPERTIES = 'mina-bw-module-properties'
XSI_NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'
MAX_XML_BYTES = 8 * 1024 * 1024
_XSLT_WORKERS = BoundedSemaphore(2)


def _xpath_string(value):
    if isinstance(value, list):
        value = value[0] if value else ''
    if isinstance(value, etree._Element):
        return ''.join(value.itertext())
    if hasattr(value, 'string_value'):
        return value.string_value
    if isinstance(value, bool):
        return str(value).lower()
    return str(value) if value is not None else ''


def _left(value, length):
    return _xpath_string(value)[:max(0, int(length))]


def _right(value, length):
    size = max(0, int(length))
    return _xpath_string(value)[-size:] if size else ''


def _sequence(value):
    return value if isinstance(value, (list, tuple)) else [value]


def _last_substring(value, delimiter, before):
    value, delimiter = _xpath_string(value), _xpath_string(delimiter)
    if not delimiter or delimiter not in value:
        return ''
    prefix, _, suffix = value.rpartition(delimiter)
    return prefix if before else suffix


_BW_FUNCTIONS = {
    'trim': (lambda value: _xpath_string(value).strip(' \t\r\n'), ('value',),
             r'replace(string($value), "^\s+|\s+$", "")', ('item()?', 'xs:string')),
    'upper-case': (lambda value: _xpath_string(value).upper(), ('value',),
                   'upper-case(string($value))', ('item()?', 'xs:string')),
    'lower-case': (lambda value: _xpath_string(value).lower(), ('value',),
                   'lower-case(string($value))', ('item()?', 'xs:string')),
    'left': (_left, ('value', 'length'), 'substring(string($value), 1, max((0, floor(number($length)))))',
             ('item()?', 'xs:numeric', 'xs:string')),
    'right': (_right, ('value', 'length'), 'substring(string($value), max((1, string-length(string($value)) - max((0, floor(number($length)))) + 1)))',
              ('item()?', 'xs:numeric', 'xs:string')),
    'concat-sequence': (lambda value: ''.join(map(_xpath_string, _sequence(value))), ('value',),
                        'string-join(for $item in $value return string($item), "")', ('item()*', 'xs:string')),
    'xor': (lambda left, right: bool(left) != bool(right), ('left', 'right'),
            'boolean($left) ne boolean($right)', ('xs:boolean', 'xs:boolean', 'xs:boolean')),
    'substring-before-last': (lambda value, delimiter: _last_substring(value, delimiter, True), ('value', 'delimiter'),
                              'if (string($delimiter) ne "" and contains(string($value), string($delimiter))) then '
                              'string-join(tokenize(string($value), string($delimiter), "q")[position() ne last()], string($delimiter)) else ""',
                              ('item()?', 'item()?', 'xs:string')),
    'substring-after-last': (lambda value, delimiter: _last_substring(value, delimiter, False), ('value', 'delimiter'),
                             'if (string($delimiter) ne "" and contains(string($value), string($delimiter))) then '
                             'tokenize(string($value), string($delimiter), "q")[last()] else ""',
                             ('item()?', 'item()?', 'xs:string')),
    'timestamp': (lambda: time.time_ns() // 1_000_000, (),
                  'floor((current-dateTime() - xs:dateTime("1970-01-01T00:00:00Z")) div xs:dayTimeDuration("PT0.001S"))',
                  ('xs:integer',)),
    'base64-to-hex': (lambda value: base64.b64decode(''.join(_xpath_string(value).split()), validate=True).hex().upper(),
                      ('value',), 'string(xs:hexBinary(xs:base64Binary(string($value))))', ('item()?', 'xs:string')),
    'hex-to-base64': (lambda value: base64.b64encode(bytes.fromhex(_xpath_string(value).strip())).decode('ascii'),
                      ('value',), 'string(xs:base64Binary(xs:hexBinary(string($value))))', ('item()?', 'xs:string')),
}


def _module_property(properties):
    def lookup(name):
        value = properties.get(_xpath_string(name), '')
        return value if isinstance(value, (str, bool, int, float)) else ''
    return lookup


def _bw_lxml_extensions(properties):
    def convert(operation):
        return lambda _context, *values: operation(*values)

    result = {(BW_FUNCTIONS, name): convert(operation) for name, (operation, _, _, _) in _BW_FUNCTIONS.items()}
    lookup = _module_property(properties)
    result[BW_RUNTIME_FUNCTIONS, 'getModuleProperty'] = lambda _context, name: lookup(name)
    return result


def _bw_xslt_functions(binding, properties, parameters):
    declared = set()
    for function in binding.findall(XSL + 'function'):
        prefix, separator, name = function.get('name', '').partition(':')
        if separator:
            declared.add((function.nsmap.get(prefix), name, len(function.findall(XSL + 'param'))))

    def function(uri, name, arguments, expression):
        declaration = etree.SubElement(binding, XSL + 'function',
                                       nsmap={'bw': uri, 'xs': 'http://www.w3.org/2001/XMLSchema'}, name='bw:' + name)
        for argument in arguments:
            etree.SubElement(declaration, XSL + 'param', name=argument)
        etree.SubElement(declaration, XSL + 'sequence', select=expression)

    namespaces = {uri for element in binding.iter() for uri in element.nsmap.values()}
    if BW_FUNCTIONS in namespaces:
        for name, (_, arguments, expression, _) in _BW_FUNCTIONS.items():
            if (BW_FUNCTIONS, name, len(arguments)) not in declared:
                function(BW_FUNCTIONS, name, arguments, expression)
    if BW_RUNTIME_FUNCTIONS in namespaces and (BW_RUNTIME_FUNCTIONS, 'getModuleProperty', 1) not in declared:
        if BW_PROPERTIES in parameters or any(node.get('name') == BW_PROPERTIES for node in binding):
            raise ValueError('XSLT uses a reserved project property parameter')
        document = etree.Element('properties')
        for key, value in properties.items():
            if isinstance(value, (str, bool, int, float)):
                etree.SubElement(document, 'property', name=key).text = str(value).lower() if isinstance(value, bool) else str(value)
        parameters[BW_PROPERTIES] = ('xml', etree.tostring(document, encoding='unicode'))
        etree.SubElement(binding, XSL + 'param', name=BW_PROPERTIES)
        function(BW_RUNTIME_FUNCTIONS, 'getModuleProperty', ('value',), f'string(${BW_PROPERTIES}/properties/property[@name = string($value)])')


class ProjectResolver(etree.Resolver):
    def __init__(self, documents=None):
        self.documents = documents or {}

    def resolve(self, url, public_id, context):
        key = url
        if key not in self.documents and ':' not in url and not url.startswith('/'):
            matches = [path for path in self.documents if path.endswith('/' + url)]
            if len(matches) == 1:
                key = matches[0]
        if key in self.documents:
            return self.resolve_string(etree.tostring(parse_xml(self.documents[key])), context, base_url=key)
        raise OSError(f'External XML resource is unavailable: {url}')


def parse_xml(value, documents=None):
    if isinstance(value, dict):
        value = value.get('xmlString') or value.get('xml') or value.get('content') or value.get('body')
    if not isinstance(value, (str, bytes)):
        raise ValueError('Select an XML source or supply XML text')
    raw = value.encode('utf-8') if isinstance(value, str) else value
    if len(raw) > MAX_XML_BYTES:
        raise ValueError('Mapper XML input exceeds 8 MiB')
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
                             encoding='UTF-8' if isinstance(value, str) else None,
                             remove_comments=True, remove_pis=True)
    parser.resolvers.add(ProjectResolver(documents))
    root = etree.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError('XML DTDs are disabled in Mapper')
    return root


def element_value(element, *, local_names=False, shape=None):
    if element.get(XSI_NIL) in ('true', '1'):
        return None
    def name(key): return key.rsplit('}', 1)[-1] if local_names else key
    fields = {'@' + name(key): value for key, value in element.attrib.items()}
    if not len(element) and not fields:
        return element.text or ''
    if element.text and element.text.strip():
        fields['#text'] = element.text
    for child in element:
        local = child.tag.rsplit('}', 1)[-1]
        definition = (shape or {}).get('properties', {}).get(local, {})
        xml = (definition.get('items', {}) if definition.get('type') == 'array' else definition).get('xml', {})
        namespace = child.tag[1:].partition('}')[0] if child.tag.startswith('{') else ''
        if (xml.get('namespace') or '') != namespace:
            definition = {}
        repeated = definition.get('type') == 'array'
        value = element_value(child, local_names=local_names, shape=definition.get('items') if repeated else definition)
        key = name(child.tag)
        if key not in fields:
            fields[key] = [value] if repeated else value
        elif isinstance(fields[key], list):
            fields[key].append(value)
        else:
            fields[key] = [fields[key], value]
    return fields


@lru_cache(maxsize=2)
def restricted_xpath2(allow_regex=False):
    from elementpath import XPath2Parser

    disabled = {'doc', 'doc-available', 'collection', 'to', 'trace'}
    if not allow_regex:
        disabled.update({'matches', 'replace', 'tokenize'})

    class OfflineXPath2(XPath2Parser):
        symbol_table = {name: token for name, token in XPath2Parser.symbol_table.items() if name not in disabled}

    return OfflineXPath2


@lru_cache(maxsize=2)
def xpath_function_palette(version):
    from elementpath import ElementPathError, XPath1Parser
    from elementpath.xpath_tokens import XPathConstructor

    parser = XPath1Parser if version == '1.0' else restricted_xpath2(allow_regex=True)
    palette = []
    for (qname, arity), signature in parser.function_signatures.items():
        name = qname.local_name
        if name not in parser.symbol_table:
            continue
        if qname.uri == 'http://www.w3.org/2005/xpath-functions':
            category = ('Date and time' if any(part in name.lower() for part in ('date', 'time', 'duration'))
                        else 'Strings' if any(part in name for part in ('string', 'case', 'space', 'codepoint', 'concat'))
                        else 'Standard XPath')
        elif qname.uri == 'http://www.w3.org/2001/XMLSchema':
            category, name = 'XML Schema constructors', 'xs:' + name
        else:
            continue
        palette.append({'name': name, 'args': [f'argument {index + 1}' for index in range(arity)],
                        'category': category, 'signature': signature})
    if version == '2.0':
        names = {entry['name'] for entry in palette}
        probe = parser()
        for name, token in parser.symbol_table.items():
            if not re.fullmatch(r'[A-Za-z][\w-]*', name) or 'xs:' + name in names:
                continue
            if not issubclass(token, XPathConstructor) and 'constructor function' not in token.label:
                continue
            try:
                probe.parse(f'xs:{name}(())')
            except ElementPathError:
                continue
            palette.append({'name':'xs:' + name, 'args':['value'], 'category':'XML Schema constructors', 'signature':''})
    palette.extend({'name': 'ext:' + name, 'args': list(args), 'category': 'Extension functions', 'signature': ''}
                   for name, (_, args, _, _) in _BW_FUNCTIONS.items())
    palette.append({'name': 'project:getModuleProperty', 'args': ['property name'], 'category': 'Extension functions', 'signature': ''})
    return sorted(palette, key=lambda entry: (entry['category'], entry['name'], len(entry['args'])))


def xpath_value(root, expression, version, namespace_text, variables=None, properties=None, *, _regex_worker=False):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 4096:
        raise ValueError('XPath requires a nonempty expression of at most 4096 characters')
    if version == '2.0' and not _regex_worker and re.search(r'\b(?:matches|replace|tokenize)\s*\(', expression):
        supplied = {name: etree.tostring(value, encoding='unicode') if isinstance(value, etree._Element) else value
                    for name, value in (variables or {}).items()}
        request = {'source': etree.tostring(root, encoding='unicode'), 'expression': expression,
                   'namespaces': namespace_text, 'variables': supplied, 'properties': properties}
        return json.loads(_run_xml_worker(request, 5, 'XPath 2.0 regex'))
    namespaces = json.loads(namespace_text or '{}') if isinstance(namespace_text, str) else namespace_text or {}
    if not isinstance(namespaces, dict) or any(not isinstance(prefix, str) or not prefix or not isinstance(uri, str)
                                               for prefix, uri in namespaces.items()):
        raise ValueError('XPath namespaces must be a JSON object of prefix-to-URI strings')
    conventional = {prefix: uri for prefix, uri in {'ext': BW_FUNCTIONS, 'project': BW_RUNTIME_FUNCTIONS,
                                                    'tib': BW_FUNCTIONS, 'bw': BW_RUNTIME_FUNCTIONS}.items()
                    if prefix + ':' in expression}
    namespaces = {**conventional, **{prefix: uri for prefix, uri in root.nsmap.items() if prefix}, **namespaces}
    properties = properties or {}
    bindings = {}
    for name, value in (variables or {}).items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][\w.-]*', name):
            raise ValueError('XPath variable names must be unprefixed XML names')
        if isinstance(value, dict) or isinstance(value, str) and value.lstrip().startswith('<'):
            value = parse_xml(value)
        if not isinstance(value, (etree._Element, str, bool, int, float)) and value is not None:
            raise ValueError(f'XPath variable {name!r} requires XML or a scalar value')
        bindings[name] = value
    if version == '1.0':
        try:
            result = etree.XPath(expression, namespaces=namespaces, smart_strings=False, regexp=False,
                                 extensions=_bw_lxml_extensions(properties))(root, **bindings)
        except etree.XPathError as error:
            raise ValueError(f'XPath 1.0: {error}') from error
    elif version == '2.0':
        from elementpath import ElementPathError, XPathContext, select
        try:
            parser_class = restricted_xpath2(allow_regex=_regex_worker)
            prefixes = {uri: key for key, uri in namespaces.items()}
            if BW_FUNCTIONS in prefixes or BW_RUNTIME_FUNCTIONS in prefixes:
                parser = parser_class(namespaces)
                if BW_FUNCTIONS in prefixes:
                    for name, (operation, _, _, types) in _BW_FUNCTIONS.items():
                        parser.external_function(operation, name=name, prefix=prefixes[BW_FUNCTIONS], sequence_types=types)
                if BW_RUNTIME_FUNCTIONS in prefixes:
                    parser.external_function(_module_property(properties), name='getModuleProperty',
                                             prefix=prefixes[BW_RUNTIME_FUNCTIONS], sequence_types=('xs:string', 'item()'))
                result = parser.parse(expression).get_results(XPathContext(root, namespaces=namespaces, variables=bindings))
            else:
                result = select(root, expression, namespaces=namespaces, parser=parser_class, variables=bindings)
        except ElementPathError as error:
            raise ValueError(f'XPath 2.0: {error}') from error
    else:
        raise ValueError(f'Unsupported XPath version: {version}')
    def convert(value):
        if isinstance(value, etree._Element): return element_value(value)
        if isinstance(value, (str, bool, int, float)) or value is None: return value
        return str(value)
    return [convert(value) for value in result] if isinstance(result, list) else convert(result)


def bw_transition_condition(expression, config, lookup, properties):
    """Evaluate imported transition XPath with the BW variables in scope."""
    if not expression or len(expression) > 4096:
        raise ValueError('Imported transition requires XPath of at most 4096 characters')
    variables = {name: lookup(path) for name, path in config.get('variables', {}).items()}
    namespaces = config.get('namespaces', {})
    root = parse_xml('<input/>')
    version = config.get('version')
    if version == '1.0':
        return xpath_value(root, f'boolean({expression})', '1.0', namespaces, variables, properties)
    if version != '2.0':
        raise ValueError('Unsupported transition XPath version')
    binding = etree.Element(XSL + 'stylesheet', nsmap={**namespaces, 'mina-xsl': XSL[1:-1]}, version='2.0',
                            attrib={'exclude-result-prefixes': '#all'})
    for name in variables:
        etree.SubElement(binding, XSL + 'param', name=name)
    template = etree.SubElement(binding, XSL + 'template', match='/')
    result = etree.SubElement(template, 'matches')
    etree.SubElement(result, XSL + 'value-of', select=f'boolean({expression})')
    return transform_xml(root, etree.tostring(binding), timeout=5, variables=variables,
                         properties=properties, element_variables=True).text == 'true'


def _run_xml_worker(payload, timeout, name):
    if getattr(sys, 'frozen', False):
        command = [sys.executable, '--mina-xslt-worker']
    else:
        package_root = Path(__file__).parents[len(__package__.split('.'))]
        bootstrap = (f'import sys; sys.path.insert(0, {str(package_root)!r}); '
                     f'from {__name__} import xslt_worker; sys.exit(xslt_worker())')
        command = [sys.executable, '-I', '-c', bootstrap]
    request = json.dumps(payload).encode()
    if not _XSLT_WORKERS.acquire(timeout=timeout):
        raise ValueError(f'{name} worker limit reached')
    try:
        with tempfile.TemporaryDirectory(prefix='mina-xslt-') as directory:
            result = subprocess.run(command, input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=timeout, cwd=directory, env={key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ},
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'{name} exceeded its execution time limit') from exc
    finally:
        _XSLT_WORKERS.release()
    if result.returncode:
        raise ValueError(f'{name}: ' + (result.stdout.decode(errors='replace') or 'worker failed'))
    return result.stdout


def _transform_xslt2(root, binding, timeout, parameters):
    request = [etree.tostring(root, encoding='unicode'), etree.tostring(binding, encoding='unicode'), parameters]
    return parse_xml(_run_xml_worker(request, timeout, 'XSLT 2.0').decode('utf-8'))


def xslt_worker():
    """Run one transform in a separate process with a scrubbed environment."""
    try:
        request = json.load(sys.stdin.buffer)
        if isinstance(request, dict):
            value = xpath_value(parse_xml(request['source']), request['expression'], '2.0', request['namespaces'],
                                request['variables'], request['properties'], _regex_worker=True)
            result = json.dumps(value).encode()
            if len(result) > MAX_XML_BYTES:
                raise ValueError('XPath result exceeds 8 MiB')
            sys.stdout.buffer.write(result)
            return 0
        from saxonche import PySaxonProcessor
        source, stylesheet, parameters = request
        with PySaxonProcessor(license=False) as processor:
            feature = 'http://saxon.sf.net/feature/'
            processor.set_configuration_property(feature + 'allowedProtocols', '#none')
            processor.set_configuration_property(feature + 'allow-external-functions', 'false')
            processor.set_configuration_property(feature + 'disableXslEvaluate', 'true')
            executable = processor.new_xslt30_processor().compile_stylesheet(stylesheet_text=stylesheet)
            executable.set_property('!encoding', 'UTF-8')
            for name, (kind, value) in parameters.items():
                builders = {'boolean':processor.make_boolean_value, 'integer':processor.make_integer_value,
                            'float':processor.make_double_value, 'string':processor.make_string_value}
                parameter = processor.parse_xml(xml_text=value) if kind in {'xml', 'xml-element'} else builders[kind](value)
                if kind == 'xml-element':
                    parameter = parameter.children[0]
                executable.set_parameter(name, parameter)
            result = executable.transform_to_string(xdm_node=processor.parse_xml(xml_text=source))
        if not result or len(result.encode()) > MAX_XML_BYTES:
            raise ValueError('Expected an XML result of at most 8 MiB')
        sys.stdout.buffer.write(result.encode())
        return 0
    except Exception as exc:
        sys.stdout.buffer.write(str(exc).encode(errors='replace')[:4096])
        return 1


def transform_xml(root, stylesheet, timeout=30, variables=None, *, properties=None, element_variables=False):
    binding = parse_xml(stylesheet)
    version = binding.get('version')
    if binding.tag not in (XSL + 'stylesheet', XSL + 'transform') or version not in ('1.0', '2.0'):
        raise ValueError('Mapper binding requires an XSLT 1.0 or 2.0 stylesheet')
    parameters = {}
    for name, value in (variables or {}).items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][\w.-]*', name):
            raise ValueError('XSLT parameter names must be unprefixed XML names')
        if value is None: continue
        if isinstance(value, dict) or isinstance(value, str) and value.lstrip().startswith('<'):
            if version == '1.0': raise ValueError('XML-valued parameters require an XSLT 2.0 binding')
            parameters[name] = ('xml-element' if element_variables else 'xml', etree.tostring(parse_xml(value), encoding='unicode'))
        elif isinstance(value, bool): parameters[name] = ('boolean', value)
        elif isinstance(value, int): parameters[name] = ('integer', value)
        elif isinstance(value, float): parameters[name] = ('float', value)
        elif isinstance(value, str): parameters[name] = ('string', value)
        else: raise ValueError(f'XSLT parameter {name!r} requires XML or a scalar value')
    if version == '2.0':
        _bw_xslt_functions(binding, properties or {}, parameters)
        return _transform_xslt2(root, binding, timeout, parameters)
    transform = etree.XSLT(binding, regexp=False, access_control=etree.XSLTAccessControl.DENY_ALL,
                           extensions=_bw_lxml_extensions(properties or {}))
    result = transform(root, **{name: etree.XSLT.strparam(value) if kind == 'string' else
                                ('true()' if value else 'false()') if kind == 'boolean' else str(value)
                                for name, (kind, value) in parameters.items()})
    if result.getroot() is None:
        raise ValueError('Mapper binding must produce an XML document element')
    return parse_xml(bytes(result))


def xml_result_shape(root, schema, documents, path='', *, validate=True):
    from .data_formats import compiled_xsd, xsd_shape
    from .faults import MinaFault

    bundle = (path, tuple(sorted((documents or {}).items()))) if re.search(
        r'<(?:[\w.-]+:)?(?:import|include|redefine|override)\b', schema) else ()
    if validate:
        try:
            validator, lock = compiled_xsd(schema, bundle)
            with lock:
                if not validator.validate(root):
                    raise ValueError('; '.join(error.message for error in list(validator.error_log)[:10]))
        except (ValueError, etree.Error) as error:
            raise ValueError('Target schema validation failed: ' + str(error)) from error
    try:
        return xsd_shape(schema, root.tag, bundle)
    except MinaFault:
        # A valid XML result can use XSD constructs the field projection
        # cannot describe. Preserve the output even without shape metadata.
        return None
