# XML JSON and Data parse and render activities

All six Parse/Render XML, JSON and Data activities use one implementation in Studio, Direct Python archives and Engine Python archives. **Configuration** contains design selectors and checkboxes. Map documents, paths, encodings, delimiters, fixed offsets, root names, JSON formatting and other runtime values in **Input → formatOptions**. A mapped option takes precedence over the checkbox, activity default or shared Data Format value. Existing text settings appear as editable Input mappings; Studio migrates them when you edit the mappings. Attach project or inline schemas in the Input/Output Editor.

## XML

Parse XML accepts text, base64 binary or dynamic input. Map binary input to `xmlBinary.bytes` and optionally supply `xmlBinary.forceEncoding` and `xmlBinary.byteCount`. Without an override, Parse XML uses the byte order mark or XML declaration. Attributes use `@name`, schema-defined repeating elements are arrays even with one occurrence, and ordered mixed text and child elements use `#content`.

Render XML accepts a parsed wrapper or a mapped schema tree. In Configuration, choose text or binary and set the default validation, declaration, indentation and namespace options. In Input, map `byteEncoding` for binary output and `formatOptions.cdataElements` for CDATA. The CDATA picker can insert paths from the selected input schema. Binary output includes `xmlBytes`, plus the existing MINA `binaryContent`, `bytes`, `byteCount` and `encoding` fields.

Validate parsed output and Validate input tree perform XSD validation, including required children, attributes and datatypes. Select the entry XSD as the activity schema. Keep its `xs:include` and `xs:import` dependencies as project schema assets with the relative filenames used by `schemaLocation`. An import without a location resolves only when there is one project XSD for that namespace. The schema tree and both Python archives use the same project assets.

The resolver is offline: URLs, local machine paths, traversal outside the project, DTDs, entities, XSD redefine and override are rejected. XML input is limited to 64 MiB; each XSD to 8 MiB and a dependency graph to 32 MiB. Namespace URIs and mixed text are preserved structurally; serialized prefixes, whitespace and lexical formatting need not match the original bytes.

Binary XML output preserves characters outside the selected encoding using numeric XML character references. For CDATA-selected text, references are emitted outside the CDATA sections so parsing restores the original value. Literal ampersands and `]]>` content retain their values. A CDATA selector can be a schema path such as `record.notes` or an expanded element name such as `{urn:example}notes`. Expanded names match both the namespace and local name. Imported binary render bindings can carry a mapped byte encoding alongside the XML document. MINA uses that encoding and serializes the document inside the binding. Schema-tree mappings with expanded namespace names are ordered according to the XSD and retain qualified attributes. Unknown input or output styles raise a validation error.

## JSON

Select the conversion mode under **Configuration → Schema type**:

- **Native JSON** is the existing MINA mode. It parses and renders objects, arrays and primitive values directly. It supports offline JSON Schema validation with local references, and can omit null object fields without changing array positions.
- **Generic** converts between a JSON string and an XML string without a schema. With Badgerfish selected, namespaces use `@xmlns`, attributes use `@name` and text uses `$`. Generic Render JSON treats XML text as strings unless **Infer numeric and boolean values** is enabled.
- **XSD** converts between JSON and a schema-defined XML tree. Select an XSD in Parse JSON's Output Editor or Render JSON's Input Editor. Validation is on by default. **Ignore additional JSON fields** filters unknown input fields when validation is enabled. An array declared by the XSD remains an array even when only one value is present.

New JSON activities default to **XSD**. Existing activities without a saved mode continue to use **Native JSON**. The JSON root styles are **None**, **JSON with Root** and **Anonymous Array**. For Anonymous Array in XSD mode, the root must have one repeating child. **Use null for empty values** represents empty containers as nil when there is an XML container. Parse JSON rejects malformed JSON and non-finite numbers; its duplicate-key policy supports First wins, Last wins and Error. Render JSON can format the result and exposes the serialized output as `jsonString`.

XSD simple-content types retain their primitive text datatype, including inheritance from another simple-content type. A type with attributes exposes its text as `#text` in XML schema-tree mappings, alongside `@attribute` fields. Parse JSON's normalized output aliases expose the same text as `$` and attributes without `@`; Studio source paths match those aliases. A simple-content value with no attributes is a primitive field. XML boolean text accepts the whitespace permitted by its XSD datatype.

On Render JSON, explicitly mapped schema-tree fields take precedence over a predecessor's serialized XML wrapper. Mapping only `formatOptions` changes formatting or conversion settings without replacing the payload. **Use empty values for null** substitutes empty containers for schema-typed nil objects/arrays; nil primitives remain JSON `null`, including primitive items in repeating fields, preserving array positions. Empty simple-content strings with attributes remain explicit text values.

## Delimited and fixed-width Data

Parse Data accepts a string or runtime file path with a selected encoding. Map `text` or `fileName` in Input. Use `skipHeaderCharacters` to bypass a preamble, `noOfRecords` to limit a batch (`-1` means all records), and `startRecord` for a zero-based manual offset. If you leave the offset unmapped, each batch advances the same activity's cursor within that task execution. Use `done` to exit a loop and `nextRecord` when supplying your own offset. **Continue on record errors** returns invalid field values or column counts in `ErrorRows.error`; an invalid document structure, such as an unterminated quoted field, still fails.

Configure the format inline or add a JSON schema asset under **Project Explorer → Schemas** with a `dataFormat` object. Select it as **Shared Data Format** on both activities. For example:

```json
{"dataFormat":{"format":"delimited","delimiter":",","header":true,"fields":"id,name","fieldTypes":"integer,string","strictColumns":true}}
```

An optional `schemaId` links the shared format to a project row schema. Parse Data exposes typed `records`, `Rows.schema`, record counts and the XML representation. Render Data accepts mapped records and exposes the rendered value as `text`, `Text` and `content`.

To reuse an existing layout, right-click **Schemas** and choose **Import XSD or Data Format**. Select a Data Format XML resource (`.dataformat`, `.dataformatresource` or `.dataformatsharedresource`) or a ZIP containing it and its companion XSDs. ZIP entries retain their relative paths. The importer converts delimited and fixed layouts into reusable MINA assets and links supported Parse/Render Data references in imported processes.

A source module property bound to the Data Format column separator becomes a MINA environment property and an editable **Input → formatOptions → Column separator** mapping. Import the ZIP with its `default.substvar` and, if available, `local.substvar`, `dev.substvar`, `qa.substvar`, `pre.substvar` or `production.substvar`. A profile value overrides the default, which falls back to the resource's literal separator if present. If no value is available, set the imported property before running. Select the imported Data Format on both activities to add its mapping without overwriting custom mappings. Unsupported substitution targets and ambiguous or secret profile values are reported during import.

Quoted CSV values retain delimiters, escaped quotes and embedded line breaks. Literal multi-character delimiters and any-character separator sets also support quoting. Render Data exposes both `content` and `text` for mapping into HTTP bodies, files or subsequent activities. Headers, line endings and final separators are configurable.

Fixed-width records use positive widths or zero-based `start:end` offsets (end excluded), so columns can have gaps. The optional fixed line length includes the separator. Numeric fields use left padding and preserve significant trailing zeroes. Strict mode rejects over-width values; permissive mode retains truncation. Single-character delimited and fixed-width files are read record by record; the multi-character delimiter reader has a 64 MiB limit. Use Mapper for hierarchy and complex transformations.

## Data validation and layout safeguards

Parse Data and Render Data now have an optional **Validate records against
selected XSD** checkbox. The equivalent dynamic Input options are
`formatOptions.validateOutput` for parsing and `formatOptions.validateInput`
for rendering. Validation uses the complete record XML and selected project or
inline XSD, including packaged imports/includes, required fields, numeric
facets, string constraints and namespaces. Validation is off by default for
existing Data activities. Enabling it without an XSD fails explicitly. JSON
Schema field inference does not substitute for XSD record validation.

Validation runs on the parsed batch or on the structured render input before
formatting. It does not validate the truncated text of a permissive fixed-width
render; enable strict mode to prevent truncation. If all records are rejected or
the batch is empty, an XSD requiring at least one row can reject the batch.

Declared field names and types are matched by name when a CSV header is in a
different order. Under **Require exact record fields**, headers must contain
the declared names, with no missing/extra fields; a different order is allowed.
Without strict mode, legacy unmatched headers retain positional type fallback.
Empty or duplicate field/header names are rejected. Header names remain case
sensitive. This prevents an integer type intended for `id` being applied to
the `name` column merely because the source changed column order.

Strict rendering requires every declared field and rejects extra fields for
single-character, multi-character and fixed layouts. An explicit null field
remains distinct from a missing mapping and renders empty/padded text under
existing rules. Fixed numeric zero-fill keeps a negative sign at the front
(`-12` at width five becomes `-0012`).

Automatic batch cursors now reset when field types, fixed offsets/length,
trimming, fill, strictness, validation/schema or record-error handling changes,
as well as when the source/header/separator changes. Changing batch size alone
continues from the current position. Task runs retain separate cursor state.

Unknown format, separator rule, blank-line policy and line-separator options
fail rather than silently falling back to a different interpretation. Supported
line-separator selectors are Auto, LF, CRLF and CR.

**Nested record structures** preserves parent paths and repeating JSON-valued
columns. **Stream large files** parses to JSON Lines or renders JSON Lines to a
formatted file in byte/count-bounded batches, returning file/count metadata.
Multi-character separators use the same bounded reader. **Continue on record
errors** now supports bounded malformed-quote recovery and physical-line mode,
with explicit rejected-record reporting. Recovery cannot remove the inherent
ambiguity of missing quotes; select the policy matching the source contract.
See [nested records and streaming](DATA_NESTED_STREAMING.md) for Input mappings,
validation scope, limits, atomic output behavior and complete-flow measurements.
Streaming activities also support explicit **Group header/detail/trailer
records**, **Validate whole-file rules** and **Validate complete file against
XSD**. Map role layouts, trailer controls, file counts/totals, unique keys and
root attributes dynamically in Input. Global XSD validation runs through EOF
before publication, replacing batch-only checks for that stream. See the
[HDT and whole-file guide](DATA_GROUPS_VALIDATION.md).

See [gap verification](validation/mapper-data-gaps-summary-2026-11-16.json)
and [changed files](MAPPER_DATA_GAPS_CHANGED_FILES.md).

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
  CustomHeaders[] → name, value
  mimeEnvelopeElement
    mimePart[] → mimeHeaders, binaryContent | textContent | fileName
```

Map constants, properties, upstream values or functions. String literals require quotes; booleans use `true`/`false`. Contract/schema fields accept JSON objects or quoted JSON/YAML/XSD text as appropriate. Operation IDs select the contract operation, whose method/path are authoritative. Empty custom schema overrides use the contract.

Previously saved Configuration values appear as typed Input mappings without a manual migration. Listener routing, server connections and security policies remain startup settings because they must exist before a request arrives. Keep external-reference origins restricted to trusted values; empty disables network reference retrieval.

## Verification

The tests cover binary encoding overrides, CDATA, XML namespaces, XSD import/include resolution and access boundaries, Generic and XSD JSON conversion, Data Format import, dynamic Input mappings, rejected records, batching, multiline CSV and fixed offsets. All six activities run in fresh Direct and Engine archives and are compared with Studio Run and Debug.

### Imported processes

Import a compatible process ZIP from Studio. MINA can retain XML and JSON Parse/Render steps and their original XSLT input bindings. Selected XSD elements are resolved by namespace and local name, including schemas embedded in the process. When a connector blocks full process conversion, the import can recover supported Mapper and format activities as separate subtasks. Supply each recovered activity's original input variables by name. Studio reports unbound Parse Data resources and empty input bindings.

From `backend`, with its Python environment:

```text
python -m unittest tests.test_format_activities tests.test_http_dynamic_contracts tests.test_ai_exception_data tests.test_raw_python tests.test_engine_export tests.test_activity_packs -q
```

References: [Python CSV newline handling](https://docs.python.org/3/library/csv.html) and [lxml parsing and validation](https://lxml.de/apidoc/lxml.etree.html).
## Selecting the XSD entry structure

When an XSD contains several global elements or named complex types, choose the
required **Structure** beside the schema selector. This choice controls the
activity's Input/Output tree, XML root, schema-derived record fields and runtime
validation. Other declarations stay available as dependencies and as choices;
they are not shown as additional mapping roots. The selected entry is retained
in Run, Debug and both Python export formats. Imported schema text is hidden;
inline source editing is available explicitly through **Edit inline schema**.
