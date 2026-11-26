"""Offline XML bindings for the portable DataCompose."""
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

from .xml_names import legacy_namespace

XSL = '{http://www.w3.org/1999/XSL/Transform}'
BW_FUNCTIONS = 'urn:mina:mapper:extensions'
BW_RUNTIME_FUNCTIONS = 'urn:mina:mapper:project'
XPATH_FUNCTION_NAMESPACES = {
    'tib': BW_FUNCTIONS,
    'bw': BW_RUNTIME_FUNCTIONS,
    'ext': BW_FUNCTIONS,
    'project': BW_RUNTIME_FUNCTIONS,
}
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


def _function_namespaces(namespaces, native, legacy_path):
    return sorted({uri for uri in namespaces if uri == native or legacy_namespace(uri, legacy_path)})


def _text_namespaces(namespaces):
    return _function_namespaces(namespaces, BW_FUNCTIONS, '/bw/xslt/custom-functions')


def _property_namespaces(namespaces):
    return _function_namespaces(namespaces, BW_RUNTIME_FUNCTIONS, '/bw/xpath/bw-custom-functions')


def xpath_function_aliases(expression):
    return {prefix: uri for prefix, uri in XPATH_FUNCTION_NAMESPACES.items()
            if re.search(r'(?<![\w.:-])' + prefix + ':', expression)}


def saved_xpath_function_aliases(namespaces):
    result = {}
    for prefix, native in XPATH_FUNCTION_NAMESPACES.items():
        uri = namespaces.get(prefix)
        compatible = _text_namespaces if native == BW_FUNCTIONS else _property_namespaces
        if compatible((uri,)):
            result[prefix] = uri
    return result


def _stylesheet_namespaces(binding):
    return {uri for node in binding.iter() for uri in node.nsmap.values()}


def _bw_lxml_extensions(properties, namespaces):
    def convert(operation):
        return lambda _context, *values: operation(*values)

    result = {(uri, name): convert(operation) for uri in _text_namespaces(namespaces)
              for name, (operation, _, _, _) in _BW_FUNCTIONS.items()}
    lookup = _module_property(properties)
    for uri in _property_namespaces(namespaces):
        result[uri, 'getModuleProperty'] = lambda _context, name: lookup(name)
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

    namespaces = _stylesheet_namespaces(binding)
    for uri in _text_namespaces(namespaces):
        for name, (_, arguments, expression, _) in _BW_FUNCTIONS.items():
            if (uri, name, len(arguments)) not in declared:
                function(uri, name, arguments, expression)
    missing = [uri for uri in _property_namespaces(namespaces) if (uri, 'getModuleProperty', 1) not in declared]
    if missing:
        if BW_PROPERTIES in parameters or any(node.get('name') == BW_PROPERTIES for node in binding):
            raise ValueError('XSLT uses a reserved project property parameter')
        document = etree.Element('properties')
        for key, value in properties.items():
            if isinstance(value, (str, bool, int, float)):
                etree.SubElement(document, 'property', name=key).text = str(value).lower() if isinstance(value, bool) else str(value)
        parameters[BW_PROPERTIES] = ('xml', etree.tostring(document, encoding='unicode'))
        etree.SubElement(binding, XSL + 'param', name=BW_PROPERTIES)
        for uri in missing:
            function(uri, 'getModuleProperty', ('value',), f'string(${BW_PROPERTIES}/properties/property[@name = string($value)])')


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


def xpath_context_source(value):
    """Context-free XPath functions also work before a flow has an XML payload."""
    candidate = next((value.get(key) for key in ('xmlString','xml','content','body') if value.get(key)), None) if isinstance(value,dict) else value
    return value if isinstance(candidate,bytes) or isinstance(candidate,str) and candidate.lstrip().startswith('<') else '<input/>'


def parse_xml(value, documents=None):
    if isinstance(value, dict):
        value = value.get('xmlString') or value.get('xml') or value.get('content') or value.get('body')
    if not isinstance(value, (str, bytes)):
        raise ValueError('Select an XML source or supply XML text')
    raw = value.encode('utf-8') if isinstance(value, str) else value
    if len(raw) > MAX_XML_BYTES:
        raise ValueError('DataCompose XML input exceeds 8 MiB')
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
                             encoding='UTF-8' if isinstance(value, str) else None,
                             remove_comments=True, remove_pis=True)
    parser.resolvers.add(ProjectResolver(documents))
    root = etree.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError('XML DTDs are disabled in DataCompose')
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


_XPATH_HELP = {
    'string':('Strings','Convert a value or the current context node to text.','value'),
    'concat':('Strings','Join two or more text values.','first text','second text'),
    'string-join':('Strings','Join sequence items using a separator.','values','separator'),
    'substring':('Strings','Extract text starting at a one-based position, with an optional length.','text','start','length'),
    'substring-before':('Strings','Return text before the first occurrence of a token.','text','token'),
    'substring-after':('Strings','Return text after the first occurrence of a token.','text','token'),
    'string-length':('Strings','Count the characters in a string.','text'),
    'normalize-space':('Strings','Trim XML whitespace and collapse consecutive whitespace.','text'),
    'normalize-unicode':('Strings','Normalize Unicode text using the requested normalization form.','text','normalization form'),
    'upper-case':('Strings','Convert text to uppercase.','text'),
    'lower-case':('Strings','Convert text to lowercase.','text'),
    'translate':('Strings','Replace or remove individual characters by position in the translation strings.','text','characters','replacements'),
    'contains':('Strings','Test whether text contains a substring.','text','substring','collation'),
    'starts-with':('Strings','Test whether text begins with a prefix.','text','prefix','collation'),
    'ends-with':('Strings','Test whether text ends with a suffix.','text','suffix','collation'),
    'compare':('Strings','Compare two strings using the default or supplied collation.','first text','second text','collation'),
    'codepoint-equal':('Strings','Compare strings by Unicode code points.','first text','second text'),
    'string-to-codepoints':('Strings','Convert text into a sequence of Unicode code points.','text'),
    'codepoints-to-string':('Strings','Create text from Unicode code points.','code points'),
    'matches':('Regular expressions','Test text against an XML Schema regular expression.','text','pattern','flags'),
    'replace':('Regular expressions','Replace regex matches using a replacement expression.','text','pattern','replacement','flags'),
    'tokenize':('Regular expressions','Split text into a sequence using a regex separator.','text','pattern','flags'),
    'number':('Numbers','Convert a value or the context node into a number.','value'),
    'abs':('Numbers','Return the absolute value of a number.','number'),
    'ceiling':('Numbers','Round upward to the nearest integer.','number'),
    'floor':('Numbers','Round downward to the nearest integer.','number'),
    'round':('Numbers','Round a number to the nearest integer.','number'),
    'round-half-to-even':('Numbers','Round using the half-to-even rule, optionally to a decimal precision.','number','precision'),
    'sum':('Numbers','Sum sequence values; optionally supply the result for an empty sequence.','values','empty result'),
    'avg':('Numbers','Return the average of a sequence of numeric or duration values.','values'),
    'min':('Numbers','Return the minimum sequence value.','values','collation'),
    'max':('Numbers','Return the maximum sequence value.','values','collation'),
    'count':('Sequences','Count sequence items or selected nodes.','items'),
    'empty':('Sequences','Test whether a sequence has no items.','items'),
    'exists':('Sequences','Test whether a sequence contains at least one item.','items'),
    'distinct-values':('Sequences','Remove duplicate atomic values using the selected collation.','values','collation'),
    'index-of':('Sequences','Find the one-based positions of a value in a sequence.','values','search value','collation'),
    'insert-before':('Sequences','Insert items before a one-based sequence position.','items','position','new items'),
    'remove':('Sequences','Remove the item at a one-based sequence position.','items','position'),
    'reverse':('Sequences','Reverse the order of sequence items.','items'),
    'subsequence':('Sequences','Select part of a sequence using a one-based position and optional length.','items','start','length'),
    'deep-equal':('Sequences','Compare sequences and their nested node content.','first items','second items','collation'),
    'zero-or-one':('Sequences','Require zero or one item; fail for a longer sequence.','items'),
    'one-or-more':('Sequences','Require a nonempty sequence.','items'),
    'exactly-one':('Sequences','Require exactly one sequence item.','items'),
    'boolean':('Boolean','Return the effective boolean value of the argument.','value'),
    'not':('Boolean','Negate the effective boolean value of the argument.','value'),
    'true':('Boolean','Return true.'),
    'false':('Boolean','Return false.'),
    'name':('Nodes and namespaces','Return the qualified name of a node.','node'),
    'local-name':('Nodes and namespaces','Return a node name without its namespace prefix.','node'),
    'namespace-uri':('Nodes and namespaces','Return the namespace URI of a node.','node'),
    'node-name':('Nodes and namespaces','Return a node name as an XML QName.','node'),
    'root':('Nodes and namespaces','Return the root of the tree containing a node.','node'),
    'data':('Nodes and namespaces','Extract atomic values from sequence items.','items'),
    'base-uri':('Nodes and namespaces','Return the base URI associated with a node without retrieving it.','node'),
    'document-uri':('Nodes and namespaces','Return the URI associated with a document node without retrieving it.','document node'),
    'lang':('Nodes and namespaces','Test the xml:lang language of a node.','language','node'),
    'id':('Nodes and namespaces','Find elements by XML ID values in the context tree.','ID values','node'),
    'idref':('Nodes and namespaces','Find nodes that reference XML IDs.','ID values','node'),
    'QName':('Nodes and namespaces','Create a QName from a namespace URI and lexical name.','namespace URI','qualified name'),
    'resolve-QName':('Nodes and namespaces','Resolve a lexical QName against an element namespace context.','qualified name','element'),
    'prefix-from-QName':('Nodes and namespaces','Extract the prefix from a QName.','QName'),
    'local-name-from-QName':('Nodes and namespaces','Extract the local name from a QName.','QName'),
    'namespace-uri-from-QName':('Nodes and namespaces','Extract the namespace URI from a QName.','QName'),
    'namespace-uri-for-prefix':('Nodes and namespaces','Resolve a namespace prefix in an element context.','prefix','element'),
    'in-scope-prefixes':('Nodes and namespaces','List namespace prefixes available on an element.','element'),
    'position':('Context','Return the current one-based position within a predicate or iteration.'),
    'last':('Context','Return the size of the current context sequence.'),
    'current-date':('Date and time','Return the current date with its timezone.'),
    'current-time':('Date and time','Return the current time with its timezone.'),
    'current-dateTime':('Date and time','Return the current date and time with timezone.'),
    'implicit-timezone':('Date and time','Return the implicit timezone offset used by the expression.'),
    'dateTime':('Date and time','Combine an XML Schema date and time.','date','time'),
    'adjust-date-to-timezone':('Date and time','Adjust a date to the implicit or supplied timezone.','date','timezone'),
    'adjust-time-to-timezone':('Date and time','Adjust a time to the implicit or supplied timezone.','time','timezone'),
    'adjust-dateTime-to-timezone':('Date and time','Adjust a date-time to the implicit or supplied timezone.','date and time','timezone'),
    'encode-for-uri':('URI encoding','Encode text as a URI component without retrieving a resource.','text'),
    'iri-to-uri':('URI encoding','Convert an internationalized resource identifier into a URI.','IRI'),
    'escape-html-uri':('URI encoding','Escape URI characters for HTML attributes.','URI'),
    'resolve-uri':('URI encoding','Resolve a relative URI against a base URI without retrieving it.','relative URI','base URI'),
    'default-collation':('Context','Return the default string collation URI.'),
    'static-base-uri':('Context','Return the expression static base URI.'),
    'error':('Diagnostics','Raise an XPath error with an optional code, description and error object.','error QName','description','error object'),
    'nilled':('Nodes and namespaces','Test whether an element is marked nil.','node'),
    'unordered':('Sequences','Declare that the order of a sequence is not significant.','items'),
}


def _xpath_palette_entry(name,arity,signature,category):
    info=_XPATH_HELP.get(name)
    if info:category,description,*labels=info
    elif name.startswith('xs:'):
        category,description,labels='XML Schema constructors','Convert a value to XML Schema '+name[3:]+'.',['value']
    elif '-from-' in name and any(part in name.lower() for part in ('date','time','duration')):
        part,_,value=name.partition('-from-')
        category,description,labels='Date and time',f'Extract {part} from a {value} value.',[value]
    else:description,labels='Evaluate '+name+' using the displayed XPath signature.',[]
    return {'name':name,'args':[(labels[index] if index<len(labels) else f'argument {index+1}') for index in range(arity)],
            'category':category,'description':description,'signature':signature}


@lru_cache(maxsize=2)
def xpath_function_palette(version):
    if version not in ('1.0','2.0'):raise ValueError('Unsupported XPath version: '+str(version))
    from elementpath import ElementPathError, XPath1Parser
    from elementpath.xpath_tokens import XPathConstructor

    parser = XPath1Parser if version == '1.0' else restricted_xpath2(allow_regex=True)
    palette = []
    for (qname, arity), signature in parser.function_signatures.items():
        name = qname.local_name
        if name not in parser.symbol_table:
            continue
        if version == '1.0' and (name, arity) == ('sum', 2):
            # The signature table also lists the XPath 2.0 overload. libxml2 rejects it.
            continue
        if (name, arity) == ('tokenize', 1):
            # The signature table also lists the XPath 3.1 shorthand.
            continue
        if qname.uri == 'http://www.w3.org/2005/xpath-functions':
            category = ('Date and time' if any(part in name.lower() for part in ('date', 'time', 'duration'))
                        else 'Strings' if any(part in name for part in ('string', 'case', 'space', 'codepoint', 'concat'))
                        else 'Standard XPath')
        elif qname.uri == 'http://www.w3.org/2001/XMLSchema':
            category, name = 'XML Schema constructors', 'xs:' + name
        else:
            continue
        palette.append(_xpath_palette_entry(name,arity,signature,category))
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
            palette.append(_xpath_palette_entry('xs:'+name,1,'','XML Schema constructors'))
    palette.extend({'name': 'ext:' + name, 'args': list(args), 'category': 'Extension functions', 'signature': '',
                    'description':'Apply the '+name+' text, encoding or timestamp extension.'}
                   for name, (_, args, _, _) in _BW_FUNCTIONS.items())
    palette.append({'name': 'project:getModuleProperty', 'args': ['property name'], 'category': 'Extension functions', 'signature': '',
                    'description':'Read a configured project property by name.'})
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
    conventional = xpath_function_aliases(expression)
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
                                 extensions=_bw_lxml_extensions(properties, namespaces.values()))(root, **bindings)
        except etree.XPathError as error:
            raise ValueError(f'XPath 1.0: {error}') from error
    elif version == '2.0':
        from elementpath import ElementPathError, XPathContext, select
        try:
            parser_class = restricted_xpath2(allow_regex=_regex_worker)
            prefixes = {uri: key for key, uri in namespaces.items()}
            text_namespaces = _text_namespaces(prefixes)
            property_namespaces = _property_namespaces(prefixes)
            if text_namespaces or property_namespaces:
                parser = parser_class(namespaces)
                for uri in text_namespaces:
                    for name, (operation, _, _, types) in _BW_FUNCTIONS.items():
                        parser.external_function(operation, name=name, prefix=prefixes[uri], sequence_types=types)
                for uri in property_namespaces:
                    parser.external_function(_module_property(properties), name='getModuleProperty',
                                             prefix=prefixes[uri], sequence_types=('xs:string', 'item()'))
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
    binding = etree.Element(XSL + 'stylesheet', nsmap={**xpath_function_aliases(expression), **namespaces, 'mina-xsl': XSL[1:-1]}, version='2.0',
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
        # Archives may be imported through a relative ZIP path. The worker runs
        # in a different temporary directory, so its import root must be absolute.
        package_root = Path(__file__).resolve().parents[len(__package__.split('.'))]
        bootstrap = (f'import sys; sys.path.insert(0, {str(package_root)!r}); '
                     f'from {__name__} import xslt_worker; sys.exit(xslt_worker())')
        command = [sys.executable, '-I', '-c', bootstrap]
    request = json.dumps(payload).encode()
    if not _XSLT_WORKERS.acquire(timeout=timeout):
        raise ValueError(f'{name} worker limit reached')
    try:
        with tempfile.TemporaryDirectory(prefix='mina-xslt-') as directory:
            deadline = time.monotonic() + timeout
            environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ}
            for attempt in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    result = subprocess.run(command, input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            timeout=remaining, cwd=directory, env=environment,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
                    break
                except OSError as exc:
                    # Windows can transiently reject CreateProcess with ERROR_GEN_FAILURE.
                    if attempt or getattr(exc, 'winerror', None) != 31 or deadline - time.monotonic() <= .05:
                        raise
                    time.sleep(.05)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'{name} exceeded its execution time limit') from exc
    finally:
        _XSLT_WORKERS.release()
    if result.returncode:
        raise ValueError(f'{name}: ' + (result.stdout.decode(errors='replace') or 'worker failed'))
    return result.stdout


def _transform_xslt2(root, binding, timeout, parameters):
    request = [etree.tostring(root, encoding='unicode'), etree.tostring(binding, encoding='unicode'), parameters]
    return parse_xml(_run_xml_worker(request, timeout, 'XSLT ' + binding.get('version')).decode('utf-8'))


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
    if binding.tag not in (XSL + 'stylesheet', XSL + 'transform') or version not in ('1.0', '2.0', '3.0'):
        raise ValueError('DataCompose binding requires an XSLT 1.0, 2.0 or 3.0 stylesheet')
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
    if version in ('2.0', '3.0'):
        _bw_xslt_functions(binding, properties or {}, parameters)
        return _transform_xslt2(root, binding, timeout, parameters)
    transform = etree.XSLT(binding, regexp=False, access_control=etree.XSLTAccessControl.DENY_ALL,
                           extensions=_bw_lxml_extensions(properties or {}, _stylesheet_namespaces(binding)))
    result = transform(root, **{name: etree.XSLT.strparam(value) if kind == 'string' else
                                ('true()' if value else 'false()') if kind == 'boolean' else str(value)
                                for name, (kind, value) in parameters.items()})
    if result.getroot() is None:
        raise ValueError('DataCompose binding must produce an XML document element')
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
