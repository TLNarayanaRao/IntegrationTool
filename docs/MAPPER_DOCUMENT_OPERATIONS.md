# DataCompose document operations and record enrichment

DataCompose includes document and record functions for API updates, record matching,
snapshot reconciliation, grouped summaries
and explicit output masking. They use the same implementation in preview, Run,
Debug, generic activity Input mappings and both Python archives. Source values
are not modified by these functions.

## Find and use the functions

Open **Input → Functions**. **Document** contains JSON Pointer/Patch/Merge Patch
and change generation. **Collection** includes indexed joins, deduplication,
`aggregateRecords` rollups and `reconcileRecords` snapshot comparison.
**Privacy** contains explicit key redaction and text masking. Drag a function
onto a target or type its name for suggestions, then supply the intended source
and arguments. The Visual DataCompose function library exposes the same entries.

| Function | Purpose |
| --- | --- |
| `jsonPointer(document, pointer, default?)` | Select one exact JSON member or array item |
| `jsonPatch(document, operations)` | Apply an ordered sequence of conditional updates |
| `jsonMergePatch(document, patch)` | Merge objects, remove members with null and replace arrays/scalars |
| `jsonDiff(before, after)` | Generate a repeatable JSON Patch describing changes |
| `joinRecords(left, right, leftKeys, rightKeys, mode?)` | Match records with composite keys using an index |
| `deduplicateRecords(records, keys, keep?)` | Keep the first or last occurrence of each key |
| `aggregateRecords(records, keys, metrics)` | Calculate named count/sum/average/min/max values for composite-key groups |
| `reconcileRecords(before, after, keys)` | Separate inserted, updated, deleted and unchanged records between snapshots |
| `redactKeys(document, fieldNames, replacement?)` | Replace explicitly named fields throughout nested objects/arrays |
| `maskText(text, visibleSuffix?, marker?)` | Retain a chosen suffix and mask the preceding characters |

## Exact paths with JSON Pointer

Paths follow [RFC 6901](https://www.rfc-editor.org/info/rfc6901/).
An empty pointer selects the document, `/` selects an object member whose name
is empty, and `/rows/0/id` selects an array member. Encode `~` as `~0` and `/`
inside a member name as `~1`. Dots are literal member-name characters, avoiding
ambiguity between an object key containing a dot and a nested path. URI-fragment
forms such as `#/customer/id` are accepted by `jsonPointer` too.

```text
jsonPointer(${input.document}, "/customer/id")
jsonPointer(${input.document}, "/optional", "fallback")
```

A supplied default handles a missing member/index, not malformed pointer syntax.
An existing JSON null remains null. Array indices cannot have leading zeros;
the append marker `-` has no readable value.

## Conditional document updates and generated changes

`jsonPatch` implements the `add`, `remove`, `replace`, `move`, `copy` and `test`
operations defined by [RFC 6902](https://www.rfc-editor.org/info/rfc6902/).
The function works on a private tree. A failed test, missing target or invalid
operation fails the call without changing its source or returning a partial patch.
Numeric equality treats 1 and 1.0 alike while distinguishing true from 1.

```text
jsonPatch(${input.document}, ${input.patch})
```

Example operations:

```json
[
  {"op":"test","path":"/version","value":7},
  {"op":"replace","path":"/status","value":"approved"},
  {"op":"add","path":"/tags/-","value":"reviewed"}
]
```

Root add/replace/remove are supported. A remove with `"path":""` deletes the
document. Inside that patch, a subsequent test, replace, copy/move from, nested
add or second remove fails because the root no longer exists. A subsequent root
add recreates the document. If it remains removed at the end, the function returns
JSON null at MINA's value boundary. DataCompose's **Null and missing values** policy
then applies: the default omits the target field; **Preserve null / xsi:nil**
retains null. This representation does not turn the absent root into an existing
null during patch evaluation. Patch paths
use pointer strings rather than URI fragments. Moving a value into its own
descendant is rejected. Copying a subtree creates independent values.

`jsonMergePatch` follows [RFC 7396](https://www.rfc-editor.org/info/rfc7396/).
Object members with null values are removed; nested objects merge; arrays and
non-object patches replace the selected value. A root null patch returns null.

```text
jsonMergePatch(${input.document}, ${input.changes})
jsonDiff(${input.before}, ${input.after})
```

`jsonDiff` produces deterministic operations with escaped pointer paths. It
replaces changed arrays as a whole instead of attempting an expensive minimal
edit sequence. Applying its result to `before` reconstructs `after`.
An empty operation array means there is no change.

These are local document transformations. To send generated operations to an API,
map them to the request body and choose the provider's supported content type,
such as `application/json-patch+json` or `application/merge-patch+json`. The remote
API must implement the corresponding update behavior; DataCompose does not change it.
These functions execute in native DataCompose rules and generated XSLT bindings.

## XSLT bindings for document functions

**Generate XSLT binding** detects the eight functions in source expressions and
pipeline descriptors. It embeds their implementations in a self-contained
**XSLT 3.0** stylesheet; no Python callback, extension function or external import
is required. Bindings without these functions continue to use XSLT 2.0. Manual
XSLT 1.0, 2.0 and 3.0 bindings are accepted. MINA executes 2.0/3.0 with its isolated
Saxon worker and includes the Saxon requirement in both Python archive formats.
Generated bindings can be reopened as editable visual rules; hand-editing them
continues to switch to manual binding mode.

JSON has maps, arrays and nulls that do not have a direct XML text-field type.
For these functions, supply JSON document/record arguments as JSON text inside
source XML elements. For example:

```xml
<input>
  <document>{"name":"Ada","password":"secret"}</document>
  <changes>[{"op":"remove","path":"/password"}]</changes>
</input>
```

```text
jsonPointer(jsonPatch(${input.document}, ${input.changes}), "/name")
```

This generates a target XML text value `Ada`. Object/array/null results become
JSON text in the target XML field, such as `{"name":"Ada"}` or `null`;
strings, numbers and Booleans use scalar text. Choose a string-valued target XSD
field for JSON document results. The functions do not invent an XML element
schema from JSON keys. `maskText` takes ordinary source text. Literal JSON
arguments, nested document calls and existing text pipeline functions can be
combined. Source-path arguments in expressions, or `${...}` pipeline arguments,
are evaluated dynamically.

The embedded functions also expose their palette names under
`urn:mina:mapper:documents:1`. When authoring a manual binding from a generated
one, use `md:jsonPatch($document, $operations)`, `md:joinRecords(...)`, etc.
These return XDM values, so serialize maps/arrays explicitly when placing them in
an XML text field. The generated binding handles this boundary automatically.
The self-contained stylesheet is verified directly with Saxon 13, as well as
through MINA; this is not a certification for every third-party XSLT processor.
It uses XSLT 3.0 maps/arrays and JSON functions described by the
[W3C recommendation](https://www.w3.org/TR/xslt-30/). Numeric parsing uses Saxon's
documented `number-parser` option to preserve large integer/decimal values rather
than forcing JSON numbers through double precision; see the
[Saxon JSON parsing options](https://www.saxonica.com/html/documentation13/functions/fn/json-doc.html).
An external processor needs a compatible numeric parsing option to preserve that
precision behavior.

## Composite-key enrichment and reconciliation

```text
joinRecords(${input.orders}, ${input.customers}, ["/customerId", "/region"], ["/id", "/region"], "left")
deduplicateRecords(${input.records}, ["/id", "/region"], "last")
```

`joinRecords` supports **inner**, **left**, **right**, **full**, **semi** and
**anti** modes. Key arguments may be one pointer string or equal-length arrays
of pointers. Comparisons are type-sensitive: strings and Booleans do not match
numbers. Numerically equal integer/floating values match. Missing or null key
components never match. Normalize text keys explicitly when case folding is needed.

Inner/left/right/full joins produce `{left: ..., right: ...}` envelopes, using
null for an unmatched side. This preserves conflicting field names instead of
silently overwriting them. Semi/anti joins return the selected left records.
Repeated keys produce every matching pair. Left encounter order and right-match
order are stable; unmatched right records follow in right encounter order.

The right side is indexed once. Joins still materialize their inputs and result;
they are not constant-memory streaming joins. Choose batch sizes appropriate to
your data and retain the documented output limits for high-cardinality matches.

Deduplication keeps first or last keyed records and preserves the encounter order
of the retained occurrences. Records with missing/null key components are retained
separately, preventing accidental deletion of incomplete data. No durable cross-run
deduplication is implied; use the durable message-state activity for that purpose.

## Pivot and unpivot records

Use **pivotRecords** to turn rows with a metric name and value into one sparse object per composite key. The output preserves the order in which groups first appear. Each group contains a `key` array and a `values` object. A duplicate column within a group raises a mapping error so a measurement cannot silently replace another.

```text
pivotRecords(${input.lines}, ["/order/id", "/region"], "/metric", "/amount")
```

Use **unpivotRecords** to turn selected fields of an object into one row per field. Each row contains `key`, `column`, and `value`. Input row order and the requested column order are preserved. Missing columns are skipped and explicit nulls are emitted.

```text
unpivotRecords(${input.orders}, ["/order/id", "/region"], "/values", ["net", "tax"])
```

Both functions accept JSON Pointer paths and require non-null scalar key values. Column names are case-sensitive, nonempty strings up to 128 characters. Unpivot accepts up to 128 distinct column names. The functions use the document limits of 100,000 records and 8 MiB. Find them under **Collection** in the Input function palette, or import them from `mina::Records`. They also work in generated XSLT 3.0 bindings.

## Grouped summaries for integration batches

```text
aggregateRecords(${input.orders}, ["/region", "/currency"], [
  {"name":"total","op":"sum","path":"/amount"},
  {"name":"average","op":"average","path":"/amount"},
  {"name":"presentAmounts","op":"count","path":"/amount"},
  {"name":"orders","op":"count"}
])
```

Each group returns a record like:

```json
{"key":["US","USD"],"count":3,"values":{"total":30,"average":15,"presentAmounts":2,"orders":3}}
```

Group order follows the first appearance of each key. Include currency, tenant
or other business boundaries in the key to avoid combining unrelated amounts.
Keys use one to sixteen JSON Pointers and must be present, non-null scalar values.
String `"1"`, number `1` and Boolean `true` identify different groups. Duplicate
keys are expected in a rollup. Input rows must be record objects.

Supply one to sixteen metrics with unique names (1–128 characters). `sum`,
`average`, `min` and `max` require a `path`. Missing/null metric values are
ignored. An all-missing group returns zero for `sum` and null for average/min/max.
`count` without a path counts every row; with a path it counts non-null present
values. Numeric text and Booleans are rejected by numeric metrics; normalize
them explicitly before grouping. Unknown operations and misspelled metric
configuration fields fail validation, including on an empty batch.

Numeric results are ordinary JSON numbers. Summation uses decimal arithmetic
internally to avoid the usual `0.1 + 0.2` accumulation artifact; fractional
results still have JSON/runtime numeric precision. This does not add a monetary
rounding policy. Apply the business-required rounding explicitly. Numeric
sum/average inputs are bounded to 1,000 significant digits.

Numeric minimum/maximum results also normalize integral values to JSON integers.
Large numeric comparisons use lexical decimal values consistently with portable
XSLT; for example JSON `1e30` and integer `1000000000000000000000000000000`
do not produce a false snapshot update or JSON Diff merely because Python's
binary float representation differs. This does not recover precision already
lost by a caller before supplying a JSON number. Booleans remain distinct.

## Reconcile source and target snapshots

```text
reconcileRecords(${input.previous}, ${input.current}, ["/id", "/tenant"])
```

The result contains four arrays:

- `inserted`: current records whose key did not exist previously.
- `updated`: `{key:[...],before:{...},after:{...}}` records with the same key
  but different values.
- `deleted`: previous records whose key is absent from the current snapshot.
- `unchanged`: current records equal to their previous version.

Inserted, updated and unchanged rows follow current-snapshot order; deleted
rows follow previous-snapshot order. Object member order does not create an
update; array order does. Boolean and numeric values compare differently,
while numerically equal integer/floating key values match.

Keys must uniquely identify every row in each snapshot. Missing, null,
non-scalar or duplicate keys cause an error instead of silently generating
ambiguous changes. The whole function fails without modifying either input.
An empty current snapshot classifies every previous row as deleted: supply
complete snapshots, not an incomplete page or failed source fetch.

Map `jsonPointer(${last.changes}, "/inserted")` (or the corresponding result
path) into downstream database, messaging or other activity inputs. These are
change classifications only: the DataCompose does not issue writes, retain durable
CDC state, enforce transactions or guarantee delivery. Keep those responsibilities
in the appropriate integration activities.

Both functions are available in the shared Input-tab drag/drop and suggestion
palette, Visual DataCompose pipelines/expressions, `mina::Records` script imports,
preview, Run, Debug and both Python archives. Generated XSLT embeds standalone
XSLT 3.0 implementations; downloaded bindings need no MINA callbacks. XML fields
carry JSON text at that boundary. Inputs and results are bounded to 8 MiB,
100,000 rows per input array and the existing nesting/work limits. They
materialize snapshots/groups rather than maintaining constant-memory streams.
Result growth is checked while appending rows, including expanded before/after
envelopes. For large datasets, partition by complete key groups/snapshots.

Reproduce the complete-flow and standalone XSLT checks with:

```text
python -m unittest backend.tests.test_mapping_records backend.tests.test_mapper_document_xslt -v
```

See [record capability verification](validation/mapper-records-summary-2026-11-16.json)
and [changed files](MAPPER_RECORDS_CHANGED_FILES.md).

## Explicit masking of mapped output

```text
redactKeys(${input.document}, ["password", "accessToken"])
maskText(${input.accountNumber}, 4, "*")
```

Key redaction matches whole field names case-insensitively at any depth, including
records in arrays. The default replacement is `[REDACTED]`; a third argument can
provide a different JSON value. It does not guess which fields contain sensitive
data. Replacing a value can change its type, so verify the selected target schema.

Text masking retains four trailing characters by default. A suffix of zero masks
the complete string; a suffix longer than the text exposes the whole short value.
The marker must be one character. JSON null is preserved. This modifies mapped
output; it is not encryption and does not remove source data from separately
configured input/execution logs.

## Script modules

Transformer scripts can import these same implementations:

```text
%mina 2.0
import jsonMergePatch from mina::Documents
import redactKeys from mina::Privacy
output application/json
---
redactKeys(jsonMergePatch(payload, vars.changes), ["password"])
```

`mina::Documents` exports the four document functions, `mina::Records` exports
joinRecords/deduplicateRecords/aggregateRecords/reconcileRecords, and
`mina::Privacy` exports redactKeys/maskText.
These are MINA extensions, not claims about another engine's standard modules.

## Limits, errors and verification

Document arguments and results are restricted to JSON values with string object
keys, finite numbers, depth at most 128 and serialized size at most 8 MiB.
Native functions also enforce cumulative work limits (four million visited nodes and
128 MiB of serialized intermediate checks). XSLT checks each document against the
depth/byte limits and four million nodes, and runs within MINA's existing isolated
worker timeout, concurrency and 8 MiB XML input/output limits. It preflights join
and redaction expansion before constructing the output. Additional limits are 10,000 patch
operations, 100,000 input/result records, 16 key components, 8,192-character
pointers, 1,024 redaction field names and 65,536-character masking inputs.
Combined limits can reject a workload before an individual maximum is reached.
Expanding joins and redaction replacements are checked before retaining oversized
outputs. These limits are JSON-size/work guards, not an operating-system RSS quota.

An additional fix makes terminal End/HTTP Send Response mapping failures fail the
task instead of being reported as successful completion. Generic Input function
arguments now parse JSON arrays/objects consistently with DataCompose expressions.

Tests cover all patch operations, pointer escapes/defaults, immutable sources,
typed equality, diff round-trips, six join modes, deduplication, redaction/masking,
limits, preview, generic Input mappings, failure propagation and both archives.
The XSLT suite additionally covers all eight functions, generated-binding
round-trips, standalone Saxon execution, manual bindings, target XSD validation,
Unicode names/fragments, large integers, absent-root transitions and relative ZIP
import execution. Invalid patches fail the task in all four execution modes.

The repeatable bulk benchmark is:

```text
python scripts/mapper-standards-qa.py --records 100000 --output-dir tmp/mapper-standards-qa-new
```

This executes Start → one DataCompose joining two record collections → End. Every
joined row is audited; archive generation/startup/IPC and cleanup are included.
It measures bulk collection processing rather than per-message orchestration,
broker throughput or a long-duration soak. Actual interpreter RSS samples include
fixture data, materialized results and runtime/logging overhead.

On 2026-11-16, each mode audited 100,000 unique joined records from two
100,000-record input collections:

| Mode | Elapsed seconds | Sampled peak interpreter RSS MiB |
| --- | ---: | ---: |
| Run | 4.09 | 287.93 |
| Debug | 4.23 | 548.63 |
| Direct Python archive | 2.42 | 184.41 |
| Engine Python archive | 5.33 | 456.71 |

The bulk operation is fast but materializes substantial data, especially with
Debug snapshots and archive IPC. These measurements are not a constant-memory
claim. See the [qualification report](validation/mapper-standards-summary-2026-11-16.json)
and linked per-mode evidence for exact values.
