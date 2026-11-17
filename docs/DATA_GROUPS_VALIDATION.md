# Header/detail/trailer groups and whole-file Data validation

Streaming Parse Data and Render Data support explicit header/detail/trailer
groups, per-group trailer controls and validation through end of file. The
implementation is shared by Run, Debug, direct Python and engine Python.

## Enable and map a grouped format

Enable **Stream large files** and **Group header/detail/trailer records** in
Configuration. Map `formatOptions.recordLayouts` to a JSON object such as:

```json
{
  "header": {
    "match": {"column": 0, "value": "H"},
    "fields": "kind,orderId",
    "fieldTypes": "string,string"
  },
  "detail": {
    "match": {"column": 0, "value": "D"},
    "fields": "kind,sku,amount,orderRef",
    "fieldTypes": "string,string,string,string"
  },
  "trailer": {
    "match": {"column": 0, "value": "T"},
    "fields": "kind,count,total",
    "fieldTypes": "string,integer,string",
    "defaults": {"kind": "T"}
  },
  "trailerChecks": [
    {"kind": "count", "trailerPath": "/count"},
    {"kind": "sum", "detailPath": "/amount", "trailerPath": "/total", "scale": 2}
  ],
  "maxGroupDetails": 10000,
  "maxGroupBytes": 8388608,
  "deriveTrailer": false
}
```

The base activity supplies delimiter, separator rule, line ending and encoding.
Every role supplies its own fields/types and can override `fieldPaths`, widths,
offsets, line length and fill. Role `fieldPaths` activates nested mappings for
that role. With no explicit paths, **Nested record structures** enables dotted
paths. Fields include the discriminator column: it is not silently removed.

Delimited matches select a zero-based column and a literal case-sensitive value
before type conversion/trimming. Fixed-width matches use
`{"start":0,"end":1,"value":"H"}` instead; `end` is excluded. A record must
match exactly one role. The file contains role records, not a separate CSV column
header; ordinary `header` settings do not consume the first role record.

Parse accepts this sequence:

```text
H,A
D,A1,10.25,B
D,A2,2.75,A
T,2,13.00
H,B
D,B1,0.10,A
D,B2,0.20,B
T,2,0.30
```

Each completed group becomes one UTF-8 JSON Lines envelope:

```json
{"header":{"kind":"H","orderId":"A"},"details":[{"kind":"D","sku":"A1","amount":"10.25","orderRef":"B"},{"kind":"D","sku":"A2","amount":"2.75","orderRef":"A"}],"trailer":{"kind":"T","count":2,"total":"13.00"}}
```

A new header requires the previous trailer. Details and trailers require an
open header. EOF with an open group, unknown/ambiguous discriminators, and
malformed control records fail the activity. Parse buffers one group rather
than the complete file. Groups are bounded to 8 MiB/10,000 details by default;
configured maxima are 64 MiB and 1,000,000 details. Each physical role record
also obeys `streamMaxRecordBytes`. A single group must fit the selected limits;
this mode does not split an oversized group or infer arbitrary recursive record
grammars. Ordinary non-grouped streaming remains available.

Render consumes the same envelope format from `streamInputFile`. It writes
header, details and trailer in order, checks each emitted discriminator, and
honors encoding and final-line settings. Existing trailers are validated by
default. Set `deriveTrailer: true` to create/recompute the configured fields;
trailer `defaults` supply the marker and other static values. Unconfigured
fields are not automatically invented.

Count checks compare accepted detail count. Sum checks use decimal arithmetic
over the specified detail pointer. Values must be finite numeric strings or
numbers; Booleans/missing values fail. Without `scale`, comparison is exact.
With scale 0–12, the control is quantized using half-to-even rounding. Derived
sums are decimal strings to preserve scale; count values are integers. Use
string field types when the file must retain exact decimal lexical formatting.
Overlapping/duplicate trailer control paths are rejected.

## Whole-file rules

Enable **Validate whole-file rules** and map `formatOptions.wholeFileRules`:

```json
{
  "minRecords": 8,
  "maxRecords": 8,
  "minGroups": 2,
  "maxGroups": 2,
  "minDetails": 4,
  "maxDetails": 4,
  "maxErrors": 0,
  "uniqueKeys": [["/header/orderId"]],
  "totals": [{"name":"amount","path":"/amount","expected":"13.30"}]
}
```

Count bounds are nonnegative integers. In grouped mode, records count accepted
physical H/D/T records; groups count completed envelopes; details count accepted
detail rows. `recordCount` in the activity result counts group envelopes, while
`sourceRecordCount` reports physical role records. In ordinary streaming,
records count accepted logical rows and group/detail counts are zero.

File totals apply to detail rows in grouped mode, or every row in ordinary mode.
Each named total has a required pointer and expected decimal value. File totals
are exact; normalize/round upstream if business rules require rounding.

Uniqueness applies to completed group envelopes or ordinary records. Supply
up to 16 rules, each containing one to 16 composite JSON Pointer paths. Keys
must exist, be non-null scalars and serialize to at most 64 KiB. Comparison is
typed/case-sensitive; numerically equal integer/floating keys match, while
Booleans and numeric strings remain distinct. A temporary disk-backed SQLite
index avoids retaining all uniqueness values in a Python collection. It is
removed on success, failure and cancellation.

Maximum limits fail as soon as exceeded; minimum limits and expected totals
are checked at EOF. With rule validation enabled, `maxErrors` defaults to zero.
Unknown settings, invalid bounds or missing total/key values fail explicitly.
Whole-file rules also work without HDT grouping, across any batch size.

## Complete-file XSD validation

Enable **Validate complete file against XSD**, select the project/inline XSD and
select `recordElement` when the root has multiple repeating children. The XML
contract is a root containing the repeating logical record/group element.
Optional `wholeFileRules.rootAttributes` supplies required root attributes:

```json
{"rootAttributes":{"batchId":"QA-2026"}}
```

The activity stages the complete logical XML document to disk, then validates
through EOF using the packaged schema graph and a clearing incremental parser.
Imports/includes follow the existing project-schema access restrictions. This
checks root cardinality, facets and XSD identity/key-reference constraints across
groups and batches. Forward references to a later group are allowed when the
complete XSD permits them. Root attributes are not inferred as CSV columns.

Complete-file XSD validation replaces per-batch XSD checks for that stream, so a
valid forward reference or whole-file minimum cannot fail merely because a
batch ends early. The existing validation checkboxes retain batch semantics
when complete-file validation is disabled. File rule validation and XSD validation
are independently selectable.

The complete XML is disk-staged, not returned as a DOM or string. Standard XML
depth/text limits still apply. XSD identity validation can retain key/reference
state internally, so memory can grow with the number of identity values. Use
disk-backed `uniqueKeys` rules where uniqueness alone is sufficient; there is
no universal constant-RAM guarantee for arbitrary XSD constraints. Provision
temporary disk space for staged output, XML and uniqueness indexes.

## Failure, rejected records and publication

Every framing, trailer, file-rule and XSD check completes before the destination
is atomically replaced. EOF failure preserves an existing output and removes
staging files/indexes. This is atomic publication of one activity output, not a
transaction spanning successive activities: a later Render failure does not
roll back a previously successful Parse output. The reject file is independently
published before the main output, as in ordinary streaming.

With **Continue on record errors**, bounded quote errors and conversion errors
on recognized detail records may be rejected explicitly. Header/trailer type
errors, unknown roles and invalid framing remain fatal because skipping them
could change group ownership. Trailer controls still have to match accepted
details. Whole-file `maxErrors` must explicitly permit rejected records; the
default is zero. Recovery cannot reconstruct missing quotes reliably—use the
physical-line policy for a single-line source contract and review diagnostics.
Whole-file processing rejects Stop-at-blank-line mode so later records cannot
escape validation.

Output metadata includes group/detail/source counts and `validation`, with
`rulesValidated`, `xsdValidated`, final totals and the number of uniqueness rules.
Keep stream paths property-driven on the runtime machine. Non-streaming activities
cannot enable grouping or whole-file validation.

## Verification

```text
python -m unittest backend.tests.test_data_groups backend.tests.test_data_stream -v
python scripts/data-group-qa.py --groups 5000 --output-dir tmp/hdt-qa-new
```

On 2026-11-16, complete Parse → grouped JSON Lines → Render flows audited 5,000
groups, 10,000 details and 20,000 physical records per mode in Run, Debug, direct
Python and engine Python. Every group was compared and rendered SHA-256 matched
the source. A missing key reference at the end of each source failed the full
XSD pass and preserved both pre-existing outputs. Execution took 5.61–5.82 seconds
in this local synthetic run, excluding archive startup/cleanup and audit passes.
These are functional/bulk checks, not a memory or long-duration soak benchmark.

See [verification report](validation/data-groups-summary-2026-11-16.json)
and [changed files](DATA_GROUPS_CHANGED_FILES.md).
