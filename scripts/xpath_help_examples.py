"""Curated inputs for the examples in Studio's XPath function help."""

XML = ('<orders xmlns:p="urn:mina:example" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
       ' xml:lang="en-US" xml:base="https://example.org/orders/">'
       '<price>12</price><price>8</price><p:item xml:id="a1">  12  </p:item>'
       '<missing xsi:nil="true"/></orders>')

COLLATION = "'http://www.w3.org/2005/xpath-functions/collation/codepoint'"
DATE = "xs:date('2026-03-14Z')"
TIME = "xs:time('15:09:26.5Z')"
DATETIME = "xs:dateTime('2026-03-14T15:09:26.5Z')"
DURATION = "xs:duration('P2Y3M4DT5H6M7.5S')"
OFFSET = "xs:dayTimeDuration('-PT5H')"
QNAME = "QName('urn:mina:example', 'p:item')"
ITEM = "/orders/p:item"

# Entries can include optional arguments. The generator takes as many as the selected overload accepts.
ARGUMENTS = {
    'abs': ('-12',),
    'adjust-date-to-timezone': (DATE, OFFSET),
    'adjust-dateTime-to-timezone': (DATETIME, OFFSET),
    'adjust-time-to-timezone': (TIME, OFFSET),
    'avg': ('(10, 20, 30)',),
    'base-uri': (ITEM,),
    'boolean': ("'ready'",),
    'ceiling': ('3.2',),
    'codepoint-equal': ("'SKU-1'", "'SKU-2'"),
    'codepoints-to-string': ('(65, 66, 67)',),
    'compare': ("'A'", "'B'", COLLATION),
    'concat': ("'ORD-'", "'123'"),
    'contains': ("'orders.csv'", "'.csv'", COLLATION),
    'count': ('/orders/price',),
    'data': ('/orders/price',),
    'dateTime': (DATE, TIME),
    'deep-equal': ('(1, 2)', '(1, 2)', COLLATION),
    'distinct-values': ("('US', 'CA', 'US')", COLLATION),
    'document-uri': ('/',),
    'element-with-id': ("'a1'", '/orders'),
    'empty': ('/orders/discount',),
    'encode-for-uri': ("'part #1'",),
    'ends-with': ("'orders.csv'", "'.csv'", COLLATION),
    'escape-html-uri': ("'https://example.org/café'",),
    'exactly-one': ("('ORD-123')",),
    'exists': ('/orders/price',),
    'ext:base64-to-hex': ("'TUlOQQ=='",),
    'ext:concat-sequence': ('/orders/price',),
    'ext:hex-to-base64': ("'4D494E41'",),
    'ext:left': ("'ORD-123'", '3'),
    'ext:lower-case': ("'MINA'",),
    'ext:right': ("'ORD-123'", '3'),
    'ext:substring-after-last': ("'a/b/c'", "'/'"),
    'ext:substring-before-last': ("'a/b/c'", "'/'"),
    'ext:trim': ("'  MINA  '",),
    'ext:upper-case': ("'mina'",),
    'ext:xor': ('true()', 'false()'),
    'floor': ('3.8',),
    'id': ("'a1'", '/orders'),
    'idref': ("'a1'", '/orders'),
    'in-scope-prefixes': (ITEM,),
    'index-of': ("('A', 'B', 'A')", "'A'", COLLATION),
    'insert-before': ("('A', 'C')", '2', "'B'"),
    'iri-to-uri': ("'https://example.org/café'",),
    'lang': ("'en'", ITEM),
    'local-name': (ITEM,),
    'local-name-from-QName': (QNAME,),
    'lower-case': ("'MINA'",),
    'matches': ("'ORD-123'", "'^ORD-[0-9]+$'", "'i'"),
    'max': ('(10, 20, 30)', COLLATION),
    'min': ('(10, 20, 30)', COLLATION),
    'name': (ITEM,),
    'namespace-uri': (ITEM,),
    'namespace-uri-for-prefix': ("'p'", ITEM),
    'namespace-uri-from-QName': (QNAME,),
    'nilled': ('/orders/missing',),
    'node-name': (ITEM,),
    'normalize-space': ("'  pending   review  '",),
    'normalize-unicode': ("'cafe\u0301'", "'NFC'"),
    'not': ('false()',),
    'number': ("'12.5'",),
    'one-or-more': ('(10, 20)',),
    'prefix-from-QName': (QNAME,),
    'project:getModuleProperty': ("'region'",),
    'QName': ("'urn:mina:example'", "'p:item'"),
    'remove': ("('A', 'B', 'C')", '2'),
    'replace': ("'inv-23'", "'^INV-'", "'ORDER-'", "'i'"),
    'resolve-QName': ("'p:item'", ITEM),
    'resolve-uri': ("'https://example.org/orders/123'",),
    'reverse': ('(1, 2, 3)',),
    'root': (ITEM,),
    'round': ('3.6',),
    'round-half-to-even': ('12.25', '1'),
    'starts-with': ("'ORD-123'", "'ORD-'", COLLATION),
    'string': ('42',),
    'string-join': ("('US', 'CA')", "' / '"),
    'string-length': ("'MINA'",),
    'string-to-codepoints': ("'ABC'",),
    'subsequence': ('(10, 20, 30, 40)', '2', '2'),
    'substring': ("'MINA'", '2', '2'),
    'substring-after': ("'ORD-123'", "'-'", COLLATION),
    'substring-before': ("'ORD-123'", "'-'", COLLATION),
    'sum': ('/orders/price',),
    'tokenize': ("'A   B C'", "'\\s+'", "'i'"),
    'translate': ("'A-B-C'", "'-'", "'_'"),
    'unordered': ('(1, 2, 3)',),
    'upper-case': ("'mina'",),
    'zero-or-one': ('()',),
}

OVERLOADS = {
    ('resolve-uri', 2): ("'123'", "'https://example.org/orders/'"),
    ('replace', 3): ("'inv-23'", "'^inv-'", "'ORDER-'"),
    ('sum', 2): ('()', '0'),
}

CONSTRUCTORS = {
    'anyURI': 'https://example.org/orders', 'base64Binary': 'TUlOQQ==',
    'boolean': 'true', 'byte': '12', 'date': '2026-03-14Z',
    'dateTime': '2026-03-14T15:09:26Z', 'dayTimeDuration': 'P2DT3H', 'decimal': '12.50',
    'double': '1.25E2', 'duration': 'P1Y2M3DT4H', 'ENTITIES': 'first second', 'ENTITY': 'order',
    'float': '1.25E2', 'gDay': '---14', 'gMonth': '--03', 'gMonthDay': '--03-14',
    'gYear': '2026', 'gYearMonth': '2026-03', 'hexBinary': '4D494E41', 'ID': 'a1',
    'IDREF': 'a1', 'IDREFS': 'a1 a2', 'int': '42', 'integer': '42', 'language': 'en-US',
    'long': '3000000000', 'Name': 'p:item', 'NCName': 'item', 'negativeInteger': '-5',
    'NMTOKEN': 'ORD-123', 'NMTOKENS': 'ORD-1 ORD-2', 'nonNegativeInteger': '0',
    'nonPositiveInteger': '0', 'normalizedString': 'pending   review', 'positiveInteger': '5',
    'QName': 'p:item', 'short': '120', 'string': 'ORD-123', 'time': '15:09:26Z',
    'token': '  pending   review  ', 'unsignedByte': '250', 'unsignedInt': '4000000000',
    'unsignedLong': '9000000000000000000', 'unsignedShort': '65000',
    'untypedAtomic': 'ORD-123', 'yearMonthDuration': 'P2Y3M',
}

CONTEXT_EXPRESSIONS = {
    'last': '/orders/price[last()]/text()',
    'position': '/orders/price[position() = 2]/text()',
}

CONTEXT_ITEM_FUNCTIONS = {
    'base-uri', 'local-name', 'name', 'namespace-uri', 'normalize-space',
    'number', 'root', 'string', 'string-length',
}

VARIABLE_RESULTS = {
    'current-date': ('2026-03-14Z', r'\d{4}-\d{2}-\d{2}.*', 'The current date and timezone depend on the runtime clock.'),
    'current-dateTime': ('2026-03-14T15:09:26Z', r'\d{4}-\d{2}-\d{2}T.*', 'The timestamp depends on the runtime clock.'),
    'current-time': ('15:09:26Z', r'\d{2}:\d{2}:\d{2}.*', 'The current time and timezone depend on the runtime clock.'),
    'implicit-timezone': ('PT0S', r'-?PT.*', 'The duration depends on the runtime timezone.'),
    'ext:timestamp': (1773500966000, r'\d+(\.0)?', 'The result is Unix time in milliseconds and changes with the runtime clock.'),
}

DESCRIPTIONS = {
    'concat': 'Join two or more text values in argument order, without inserting a separator.',
    'element-with-id': 'Find an element by its XML ID. The optional node chooses which tree to search.',
    'ext:base64-to-hex': 'Decode Base64 and return the bytes as uppercase hexadecimal text.',
    'ext:concat-sequence': 'Join the string values of sequence items without a separator.',
    'ext:hex-to-base64': 'Decode hexadecimal text and encode the bytes as Base64.',
    'ext:left': 'Return up to the requested number of characters from the start of a string.',
    'ext:lower-case': 'Convert the input text to lowercase.',
    'ext:right': 'Return up to the requested number of characters from the end of a string.',
    'ext:substring-after-last': 'Return text after the last delimiter. Return empty text if the delimiter is missing or empty.',
    'ext:substring-before-last': 'Return text before the last delimiter. Return empty text if the delimiter is missing or empty.',
    'ext:timestamp': 'Return the number of milliseconds elapsed since midnight UTC on January 1, 1970.',
    'ext:trim': 'Remove leading and trailing XML whitespace while preserving whitespace inside the string.',
    'ext:upper-case': 'Convert the input text to uppercase.',
    'ext:xor': 'Return true when exactly one of the two boolean arguments is true.',
    'idref': 'Find nodes with a typed XML ID reference. Ordinary strings and XML IDs alone are not references.',
    'project:getModuleProperty': 'Read a project property using its configured name. A missing property returns empty text.',
    'string': 'Convert a value to text. With no argument, return the string value of the context node.',
}
