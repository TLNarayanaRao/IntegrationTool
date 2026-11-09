# XML JSON and Data parse and render activities

All six Parse/Render XML, JSON and Data activities use one implementation in Studio, Direct Python archives and Engine Python archives. Map document content in Input and choose format/validation policies in Configuration. Attach project or inline schemas using the Input/Output Editor where applicable.

## XML

Parse XML accepts text, base64 binary or dynamic input. Binary XML respects its declaration/BOM unless a forced encoding is supplied. Attributes use `@name`, repeated elements use arrays, and ordered mixed text/child content uses `#content`. Render XML accepts a parsed wrapper or a mapped schema tree, supports declarations, pretty printing and encoded binary output. Binary Output exposes `binaryContent`, `bytes`, `byteCount` and `encoding`.

Validate parsed output and Validate input tree perform full XSD validation for self-contained schemas, including required children, attributes and datatypes. Validators use a bounded cache. The backend needs `lxml`; generated archives list the dependency. Refresh backend requirements when starting from source.

DTDs/entities and external XSD includes/imports are disabled; supply a self-contained XSD. XML input is limited to 64 MiB and XSD content to 8 MiB. Namespace URIs and mixed text are preserved structurally; serialized prefixes, pretty-print whitespace and lexical formatting need not match the original bytes.

## JSON

Parse JSON supports First wins, Last wins and Error policies for duplicate keys. Malformed JSON and NaN/Infinity are rejected. The parsed value is published directly; map the activity root or selected schema fields.

Render JSON accepts objects, arrays and primitive values. It supports pretty printing, bounded indentation, non-ASCII escaping and omission of null object fields. Null array positions are preserved. Validation uses bounded offline JSON Schema validation with local references. Invalid schema content fails rather than silently disabling validation.

## Delimited and fixed-width Data

Parse Data accepts a string or runtime file path with a selected encoding. It supports headers or configured/schema-derived field names, scalar type conversion, blank-line policy and strict column counts. Output includes typed `records`, `recordCount`, field names and an XML representation.

Quoted CSV values retain delimiters, escaped quotes and embedded line breaks. Literal multi-character delimiters and any-character separator sets also support quoting. Render Data exposes both `content` and `text` for mapping into HTTP bodies, files or subsequent activities. Headers, line endings and final separators are configurable.

Fixed-width records require positive widths matching field names. Numeric fields use left padding and preserve significant trailing zeroes. Strict mode rejects over-width values; permissive mode retains truncation. Invalid boolean values, non-finite numbers and duplicate columns fail explicitly. File input is bounded to 64 MiB. These activities represent flat records; use Mapper for additional hierarchy and complex transformations.

## Dynamic HTTP and REST invocation settings

HTTP Request and REST Invoke Configuration keeps the display name and shared connection selector. Request-specific settings are mapped in **Input → RestInputRequest**:

```text
RestInputRequest
  Config
    host, port, scheme, requestURI, Method, RequestBody, bodyFormat
    QueryParameters, URIParameters, QueryString, FilePath
    timeout, activityTimeoutSeconds, followRedirects, raiseForStatus
    openApiDocument, operationId, openApiBaseUrl
    openApiReferenceDocuments, openApiAllowedRefOrigins
    validateRequest, requestSchema, validateResponse, responseSchema
  Headers
    accept, content-type, Accept-Charset, Accept-Encoding, Cookie, pragma
    DynamicHeaders[] → name, value
  mimeEnvelopeElement
    mimePart[] → mimeHeaders, binaryContent | textContent | fileName
```

Map constants, properties, upstream values or functions. String literals require quotes; booleans use `true`/`false`. Contract/schema fields accept JSON objects or quoted JSON/YAML/XSD text as appropriate. Operation IDs select the contract operation, whose method/path are authoritative. Empty custom schema overrides use the contract.

Previously saved Configuration values appear as typed Input mappings without a manual migration. Listener routing, server connections and security policies remain startup settings because they must exist before a request arrives. Keep external-reference origins restricted to trusted values; empty disables network reference retrieval.

## Verification

The tests cover XSD content validation, binary encodings, mixed XML, duplicate JSON keys, local schema references, null positions, multiline CSV, separators, fixed-width padding and file input. All six activities run in fresh Direct and Engine archives and are compared with Studio. HTTP tests exercise dynamic contract selection and JSON/XSD validation.

From `backend`, with its Python environment:

```text
python -m unittest tests.test_format_activities tests.test_http_dynamic_contracts tests.test_ai_exception_data tests.test_raw_python tests.test_engine_export tests.test_activity_packs -q
```

References: [Python CSV newline handling](https://docs.python.org/3/library/csv.html) and [lxml parsing/validation](https://lxml.de/apidoc/lxml.etree.html).
