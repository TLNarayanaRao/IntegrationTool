# Nested Data records and large-file streaming

Parse Data and Render Data support nested column paths, repeating JSON-valued
columns, byte-bounded file batches and recoverable malformed quoting. The same
implementation is packaged for Run, Debug, direct Python and engine Python.
Existing non-streaming activities keep their record/text outputs.

## Nested objects and repeating children

Enable **Nested record structures** in Configuration. In Input, map:

```json
{
  "formatOptions.fields": "id,city,items",
  "formatOptions.fieldTypes": "integer,string,json",
  "formatOptions.fieldPaths": {
    "id": "/customer/id",
    "city": "/customer/address/city",
    "items": "/lines"
  }
}
```

Each CSV or fixed-width column keeps its declared name. Paths are JSON Pointers
relative to one record. Parse creates the structure; Render selects the same
paths. A JSON column can carry an object or arbitrary repeating children:

```json
{
  "customer": {"id": 7, "address": {"city": "Paris"}},
  "lines": [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 1}]
}
```

The `items` CSV cell contains JSON text for the entire `lines` array; ordinary
CSV escaping preserves commas, quotes and newlines. Missing/overlapping paths
fail in strict mode rather than replacing another mapped branch. Explicit
array positions such as `/lines/0/sku` are also supported. Numeric segments
create arrays; use a JSON-valued column for objects with numeric property names.
Paths use `~1` for a slash and `~0` for a tilde in a member name. Without explicit
overrides, dotted names such as `customer.id` become nested paths.

A selected XSD or JSON Schema can supply nested field names and types. A single
repeating wrapper child is treated as the row collection; otherwise the root
is the record. `recordElement` explicitly selects a repeating child when needed.
Nested objects retain parent paths, and repeating fields become JSON-valued
columns. This supports hierarchies **inside each logical row**. For related
header/detail/trailer rows, enable explicit [record grouping and whole-file
validation](DATA_GROUPS_VALIDATION.md); relationships are configured rather than
guessed from unrelated rows.

Structured `records`/`Rows` output retains original JSON keys. The convenience
XML view normalizes invalid XML names when no XSD is selected and rejects
normalization collisions; use structured records for exact unusual JSON keys.

## Parse a large file

Enable **Stream large files** in Parse Data. Map these Input fields:

| Input | Meaning |
| --- | --- |
| `fileName` | Source delimited or fixed-width file on the runtime machine |
| `streamOutputFile` | Destination UTF-8 JSON Lines file, one nested record per line |
| `streamErrorFile` | Optional UTF-8 rejected-record JSON Lines file |
| `formatOptions.fileEncoding` | Source encoding; defaults to UTF-8 with BOM handling |
| `formatOptions.streamBatchSize` | Maximum records per batch; default 500, maximum 10,000 |
| `formatOptions.streamMaxBatchBytes` | Raw/parsed record budget per batch; default 8 MiB, maximum 64 MiB |
| `formatOptions.streamMaxRecordBytes` | Raw/parsed record limit; default 1 MiB, configurable 256 bytes–64 MiB |

The record limit must fit in the batch budget. A byte limit can end a batch
before its row count. Stream mode processes the whole source and owns its cursor;
manual `startRecord` and legacy `noOfRecords` are not used as stream offsets.
Multi-character separators now use the bounded reader as well, so total file
size is no longer limited to 64 MiB. Limits apply to records and batches.

The output is metadata:

```json
{"streamed":true,"filePath":"/runtime/output/records.jsonl","recordCount":35000,"errorCount":0,"batchCount":350,"errorFile":null,"done":true}
```

The complete file is not returned as an array, XML document or text value.
Unless XSD validation needs it, Parse does not build convenience XML for streamed
batches. Intermediate records exist only within configured byte/count budgets.

## Render a large file

Enable **Stream large files** in Render Data. Map `streamInputFile` to the Parse
JSON Lines output and `streamOutputFile` to the formatted destination. JSON Lines
input is UTF-8; map `formatOptions.fileEncoding` for the output encoding. Select
the same nested paths/types and normal separators, widths and header settings.

Render emits the header once, preserves separators between batches, and honors
the final-line-separator option. UTF-16 output has one encoding preamble because
one writer owns the stream. The output is file/count metadata, not the entire
formatted text. Malformed JSON Lines input fails atomically; it is not skipped
silently. JSON column values reject duplicate names, non-finite numbers and
excessive nesting.

Input/output/reject paths must differ, including aliases/hard links. Source files
must remain unchanged while processing. Paths resolve on the executing runtime
machine; use Input properties instead of embedding development-machine paths.
Destination directories must exist. Files are staged alongside the destination,
flushed and atomically replaced only after successful processing. Failures and
cancellation remove partial files and retain the previous destination. There is
no rollback after a completed replacement. Reject files are independently
published before the main output; the pair is not a filesystem transaction.

## Recover malformed quoted records

Enable **Continue on record errors** and choose `formatOptions.quoteRecovery`:

- `bounded` (default) accepts valid multiline quoted fields. It buffers at most
  `streamMaxRecordBytes` and `maxRecordLines` (default 1,000, maximum 10,000).
  When a quoted candidate is malformed, the first physical line is rejected and
  subsequent buffered lines are replayed as new candidates. Cursor checkpoints
  point to logical boundaries, so recovery also works across Parse batches.
- `physical-line` treats each physical line as a record. Use this when the file
  contract forbids multiline fields; broken quotes cannot absorb following rows.

With continuation disabled, malformed quoting still raises an activity fault.
With continuation enabled, type/column/quote errors appear in `ErrorRows` or the
stream reject file, and `errorCount` reports rejected records. Reject diagnostics
are byte-bounded and may truncate raw text (`rawTruncated: true`). Invalid headers
still fail because the field contract cannot safely be established.

An unclosed quote is inherently ambiguous: some later lines can look like a
valid continuation. Recovery cannot establish business correctness or reconstruct
missing characters. Choose physical-line mode for a single-line contract and
review rejects and recovered records before accepting a feed. Rejected
candidates are explicitly reported rather than hidden.

## Validation and limits

Optional XSD validation remains available. The original validation checkboxes
validate bounded batches. Enable **Validate complete file against XSD** for a
disk-staged document and global keys/references/cardinality; this replaces batch
checks for that stream. **Validate whole-file rules** adds counts, exact totals
and disk-backed uniqueness. See the [grouping/validation guide](DATA_GROUPS_VALIDATION.md).
Render validation happens before formatting; strict mode prevents truncation.

Nested paths/JSON records are bounded to 64 levels, layouts to 10,000 columns,
explicit array indices to 1,000 and automatically allocated array slots to
10,000 per record. JSON-valued columns handle larger repeating child arrays
within the byte/complexity limits. Fixed-width fields/fill cannot contain line
breaks, which would corrupt physical record boundaries. String input and legacy
record/text outputs remain available, but only file-stream mode avoids returning
the entire result. Streamed writes do not provide message delivery guarantees or
database transactions.

## Verification

```text
python -m unittest backend.tests.test_data_stream backend.tests.test_format_activities -v
python scripts/data-stream-qa.py --records 35000 --payload-chars 2048 --output-dir tmp/data-stream-new
```

On 2026-11-16, a 72,963,904-byte nested CSV file was parsed to JSON Lines and
rendered back through complete Run, Debug and both Python archive flows. All
35,000 records were audited in each mode and output SHA-256 matched the source.
Execution times were 4.72–5.44 seconds in this local run. Archive creation,
startup/cleanup and audit passes are outside the timed interval. Sampled RSS
growth was below 13 MB; 10 ms RSS sampling can miss short peaks and is not a
constant-memory guarantee or long-duration soak.

See [verification results](validation/data-stream-summary-2026-11-16.json)
and [changed files](DATA_STREAM_CHANGED_FILES.md).
