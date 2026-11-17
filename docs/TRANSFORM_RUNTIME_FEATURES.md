# Transformation libraries, outputs, streaming and contracts

Mapper and Transformer share portable runtime support for these features in Run,
Debug and both Python archive formats. Existing single-output projects retain
their behavior. These additions extend MINA's embedded language; they do not
install another vendor runtime or claim compatibility with every external script.

## Reusable script libraries

In Transformer Configuration, expand **Reusable script libraries**. Add a module
name such as `company::Names` and its declarations:

```text
module Names
var prefix = "Customer: "
fun normalize(value) = upper(trim(value))
fun label(value) = prefix ++ normalize(value)
```

Import the module in any output script:

```text
%dw 2.0
import company::Names as Names
output application/json
---
{name: Names::normalize(payload.name), label: Names::label(payload.name)}
```

Named imports (`import normalize from company::Names`) and wildcard imports are
also supported. Library variables can be imported as constants. Declarations may
span balanced parentheses, arrays or objects across lines. Functions have lexical
module scope; they receive flow data through arguments. A module can import another
configured module. Cycles, unknown exports and excessive import depth/work fail.
Sources stay in the activity's `libraries` dictionary, are shared by its output
scripts and travel with the project and both exports. No filesystem, network,
Java or Python module loader is exposed through script imports.

Built-in module inventory:

| Module | Supported exports |
| --- | --- |
| `dw::Core` | Explicit imports of existing core built-ins: upper/lower/trim, sizeOf/isEmpty, flatten, keysOf/valuesOf, sum/min/max/avg, joinBy/splitBy/contains/startsWith/endsWith, abs/floor/ceil/mod/pow, zip/unzip, uuid/now/typeOf/read/write |
| `dw::core::Strings` | capitalize, camelize, underscore, dasherize, padLeft, padRight, substringBefore, substringAfter, reverse |
| `dw::core::Arrays` | divideBy, take, drop |
| `dw::core::Numbers` | fromBinary, fromHex, fromRadixNumber, toBinary, toHex, toRadixNumber |
| `dw::util::Math` | acos, asin, atan, cos, sin, tan, log10, logn, toDegrees, toRadians |
| `dw::util::Coercions` | Basic string toNumber/toBoolean/toArray conversions |
| `mina::Documents` | jsonPointer, jsonPatch, jsonMergePatch, jsonDiff |
| `mina::Records` | joinRecords, deduplicateRecords, aggregateRecords (grouped metrics), reconcileRecords (snapshot change sets) |
| `mina::Privacy` | redactKeys, maskText |

See [Mapper document operations](MAPPER_DOCUMENT_OPERATIONS.md) for standards,
examples and limits for the MINA modules.

Only the listed overloads and the embedded expression syntax are supported; locale
formatters, arbitrary custom types/namespaces and the complete external function
libraries are not implied. `import` names outside the configured and built-in
inventory produce a diagnostic. Library sources contain declarations; put a
mapping body inside a function rather than an ignored module body.

## Multiple output targets

Expand **Multiple output targets**, then choose **Add output target**. Each target
has its own script and optional selected target schema. Supported targets are
payload, attributes and a named variable. Only one payload and one attributes
target are allowed; variable names must be distinct. Attribute results must be
objects. Remove all output definitions to return to the original single target.

All scripts read the same original payload, attributes and variables. No target
can observe another target's newly calculated value. The runtime calculates and
validates every result before committing payload/attribute/variable updates. A
script or contract failure leaves the previous attributes and variables intact.
This transaction covers transformation state, not external service transactions.
Subsequent activities can map `${attributes}` or `${attributes.field}` as well as
the resulting payload and variables.

**Map & Test** displays every configured output and enforces the same contracts.
Main single-output controls are disabled while multiple targets are active; edit
each output's script, schema and visual mappings in its target section.

## Visual/script synchronization

Expand **Visual / script mappings**. Static object fields appear as editable
target-path/expression pairs, including nested fields and empty objects. Changing
a field updates the script; script edits refresh this view after a short debounce.
Existing headers, imports and declarations are retained on a visual edit.

An array, map/filter pipeline, conditional root or object that cannot safely be
flattened appears as a whole-payload expression node. Editing that node updates
the complete body without discarding it. Syntax outside the embedded parser's
supported grammar reports an error and preserves the script. This view is an
expression graph, not a promise to infer detailed field connections from arbitrary
code. The existing Mapper visual/XSLT binding round-trip remains available for
its documented mapping subset.

## Source and target schema validation

Transformer source/target selections now enforce JSON Schema or XSD contracts in
preview, Run, Debug and both archives. Validation is on by default when a schema
is selected; explicit source/target checkboxes can disable it. Each additional
output may select its own contract. XSD structure selectors choose the required
root/type instead of validating against unrelated global structures.

Schema IDs reload the current project asset at execution, preserving the selected
XSD structure. Project-relative XSD imports/includes and JSON Schema references
resolve only from packaged project schema assets. Remote schema retrieval remains
disabled. JSON types, required properties, formats and bounded patterns use the
shared validator. XSD documents use the compiled project contract. XML-valued
outputs validate as XML; structured outputs with XSD contracts are rendered
against the selected structure for validation. Failures identify source or target
and prevent output-state commit. Exports include the selected assets, transitive
dependencies and deployment dependency declarations.

## Record streaming for Mapper and Transformer

Expand **Streaming record transformation** in Mapper policies or Transformer
configuration. Enable streaming, choose input/output formats and provide file
paths. Paths can be dynamic expressions, for example `${input.sourceFile}` and
`${properties.outputFile}`. Both paths refer to the machine running the flow;
an exported application does not carry the user's input files.

- Input formats: a top-level JSON array, JSON Lines or CSV (including quoted
  multiline fields). JSON arrays use an incremental decoder, not a full-file load.
- Output formats: JSON array, JSON Lines or CSV. Output is written one record at
  a time. CSV columns come from the first output row; unexpected later columns
  fail rather than being silently discarded. The Python CSV parser's field-size
  limit also applies.
- Mappings/scripts and selected schemas apply to one record. Whole-file sorting,
  grouping and random access are not stream operations; apply them explicitly to
  each record or use a separate aggregation step.
- Multiple Transformer targets write a per-record JSON/JSONL envelope containing
  `payload`, `attributes` and `variables`. They do not accumulate file-sized arrays
  in flow variables. Multiple-target envelopes cannot use the CSV writer.
- Run/Debug returns `streamed`, `recordsWritten`, `outputFile` and `outputFormat`;
  it does not load the generated file into the activity result. Map & Test tests a
  sample record without opening the configured files.
- Limits are configurable: maximum record bytes (256 bytes–8 MiB), maximum records
  and a positive finite deadline. Defaults are 1 MiB, one million and 600 seconds.
  Invalid/incomplete JSON, duplicate CSV headers, oversized records, schema errors
  and cancellation fail the activity.
- A sibling temporary output is flushed and atomically replaces the destination
  only after the full stream succeeds. Failure or cancellation observed before
  commit removes the temporary file and preserves an existing destination. Cooperative cancellation drains the
  owned worker; a consumer never receives a half-written destination file.

This is file-backed, record-at-a-time streaming. It is not an in-memory stream
object passed through every connector, nor an implementation of every external
reader/writer property or nested-XML streaming convention. Memory scales with a
record, its schema/module environment and fixed-size parser buffers, not the total
record count. Full-record size guards apply before emission.

## Verification

`backend/tests/test_transform_features.py` covers imports and lexical scope,
transactional targets, preview parity, script round-trips, schema reloads/local
references, XSD includes, streaming rollback/limits and all four execution modes.
Generated archives are built and executed in independent Python interpreters.

The repeatable large-file qualification is:

```text
python scripts/transform-stream-qa.py --records 100000 --output-dir tmp/stream-qa-new
```

It runs Start → streaming Mapper/Transformer → End for each execution mode,
validates source and target schemas, audits every output, and samples the actual
interpreter's RSS. Its timings include archive startup/import, readback and cleanup.
Use a fresh output directory. These measurements are a bounded workload test,
not a long-duration leak proof or a comparison against another product's runtime.

See the dated qualification summary and per-mode reports in `docs/validation/`.

On 2026-11-16, all eight 100,000-record cases passed with full readback and source/
target validation enabled:

| Activity | Run seconds | Debug seconds | Direct archive seconds | Engine archive seconds |
| --- | ---: | ---: | ---: | ---: |
| Mapper | 26.98 | 28.08 | 28.41 | 28.78 |
| Transformer | 27.56 | 29.22 | 28.19 | 30.42 |

Sampled interpreter RSS peaks were 37.89–70.45 MiB across these cases, including
runtime/import overhead. The actual archive interpreter identifies itself to the
harness; measurements do not accidentally sample only the Windows launcher.
These samples alone do not establish long-duration memory stability.

The broad backend run completed 684 tests with 11 environment-dependent skips
and no failures. A final 33-test focused run also passed after the property/
condition and cancellation refinements. See
[qualification evidence](validation/transform-features-summary-2026-11-16.json).

Reference behavior was checked against the official [module reference](https://docs.mulesoft.com/dataweave/2.9/dw-functions),
[streaming documentation](https://docs.mulesoft.com/dataweave/latest/dataweave-streaming),
[Numbers module](https://docs.mulesoft.com/dataweave/latest/dw-numbers) and
[Math module](https://docs.mulesoft.com/dataweave/2.4/dw-math). These references do
not imply full language or runtime equivalence.
