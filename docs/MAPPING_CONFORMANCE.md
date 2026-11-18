# Mapping and transformation qualification

## Scope

The follow-up [runtime feature guide](TRANSFORM_RUNTIME_FEATURES.md) documents
libraries, multiple targets, bounded file streaming, script synchronization and
schema enforcement added after the initial measurements below. The original
reports remain historical evidence; current feature qualification is separate.

MINA provides a schema-driven Mapper and a scripted Transformer. The tests
use local migration fixtures and cover MINA behavior and performance.

## XML namespaces and imports

New generated Mapper bindings declare the XPath function namespaces used by
their expressions, including expressions inside Choose and Otherwise branches.
Saved bindings reopen with their declared compatible function namespaces.
Studio checks that the stylesheet still matches its editable mapping rules.

Project import identifies process extensions from the XML elements and
attributes that use them. A conflicting process or an unreadable XML asset
appears under **Review required** while other supported assets are imported.
Namespace declarations are resolved locally.

## Changes from this review

- Equality no longer executes unrelated relational operators, and Boolean values
  are distinguished from numbers in structured comparisons.
- If/else, default, and logical operators skip evaluation of unneeded expressions
  while still checking their syntax. Empty and null collections skip lambda
  execution; null-capable collection operations preserve null.
- Object mapping supports value/key/index parameters, anonymous `$`/`$$`/`$$$`
  parameters and dynamic object keys. `filterObject`, `minBy`, `maxBy`, `zip`,
  `unzip`, `mod` and `pow` are available. Mapper functions remain a separate palette.
- Quoted Unicode text, subtraction without spaces, exponent-form numbers and
  trailing whitespace work. Unknown identifiers/coercions and unsupported module
  imports, writer properties, language headers and output formats raise errors
  rather than silently changing behavior.
- XML input retains attributes on leaf elements and handles MIME parameters.
  The internal representation uses `@attribute` and `#text`; this is a MINA value
  representation, not an implementation of every XML selector in another language.
  XML output understands that representation. DTDs and external entities are
  disabled, parsing has normal tree limits, and XML input is capped at 8 MiB.
- Repeated formulas reuse immutable token lists in a 128-entry cache. Payloads,
  lambda environments and results are never cached. Expressions are capped at
  64 KiB. This is token reuse, not compiled streaming execution.
- Script execution runs off the async event loop in Run/Debug, matching the direct
  archive's scheduling behavior. A regression verifies other async work can proceed.
- The direct exporter accepts the Transformer's default operation, matching Run,
  Debug and the engine archive. The pre-fix failed benchmark is retained as evidence.
  Both archives declare the XML reader's existing `lxml` dependency in their
  generated deployment checks, including scripts that select XML at runtime.
- Studio includes object-filter and highest-score script starting points, with
  updated activity help describing the embedded language subset.

## Capability assessment

| Area | Schema-driven Mapper | Scripted Transformer | Qualification / remaining boundary |
| --- | --- | --- | --- |
| Schema trees and target editing | Selected XSD roots/types, inline contracts, occurrence markers and source views | Source/target schema selection for script generation | Not a claim of identical designer controls; script schema selection is not full source/output validation |
| Direct, conditional and repeating mappings | Copy-Of, For-Each, grouping, If/Choose and independent duplicate occurrences | Objects/arrays, conditions, defaults and collection lambdas | Existing Mapper regressions plus new scripted semantic cases |
| Expressions and functions | General functions, XPath 1.0/2.0 catalogs, custom functions and lookup tables | Configured module imports, constants, multiline functions and listed built-in modules | Not all proprietary extensions or every external library/overload |
| XML bindings | Offline XSLT 1.0/2.0, generated binding round-trips within the documented subset | Basic XML read/write | Not full namespace-aware script selectors, mixed content, writer settings or proprietary parallel XSLT extensions |
| Format conversion | Use schema mapping with Parse/Render activities | JSON, XML, CSV and plain text paths | Not every binary, Java object, spreadsheet, copybook or flat-file format supported by other engines |
| Source/target metadata | Schema validation, source coercions and occurrence overrides | JSON Schema/XSD source and target enforcement with packaged local references | Validation now applies in preview and all execution modes; richer inference remains distinct |
| Multiple output targets | Mapping rules build one structured activity output | Atomic independently scripted payload, attributes and named-variable targets | Streaming multiple targets use per-record JSON envelopes |
| Visual/source synchronization | Supported visual rules can generate and restore XSLT | Object-field synchronization and whole-expression graph nodes | Unsupported syntax is preserved; arbitrary code is not inferred as detailed field connections |
| Preview and tests | Map & Test, saved cases, expected output comparison | Map & Test using the shared embedded engine | API-level preview verified; installed desktop mouse interaction not automated in this review |
| Large inputs / streaming | Bounded file-record execution and explicit batch helpers | Incremental JSON array/JSONL/CSV input and atomic file output | Not arbitrary live connector stream objects or all external reader/writer conventions |
| Migration | Supported process/binding imports with diagnostics | Supported expression subset | Not lossless conversion of arbitrary projects, modules or proprietary code |

The stated boundaries remain real. Installing more function names or presenting a script
as accepted would not make those semantics equivalent. Scripts using unsupported
features should be migrated explicitly; do not treat an accepted small sample as
proof that every input or external project is compatible.

## Verification and performance

`backend/tests/test_transform_semantics.py` checks documented control-flow,
collection and string behavior. `test_transform_execution_parity.py` checks eight
independently reviewed cases through preview, Run, Debug and both generated
archives, plus event-loop responsiveness. Existing Mapper tests cover schema,
cardinality, repeated structures, bindings and archive behavior. Installed sample
bindings are imported and exercised with `test_bw613_vendor_samples.py`; this
executes their converted representation in MINA, not the installed vendor engine.

The benchmark runs an eight-field transformation of 100,000 approximately 1 KiB
records with four workers, batches of 1,000 and a 600-second deadline per mode.
Every output is checked against a separately constructed expected record, including
trim/uppercase normalization and an array sum. Run/Debug log bookkeeping remains
enabled. Generated archive startup, import, IPC and final cleanup are included.
This common workload is narrower than the entire capability matrix and is not a
long-duration memory soak or a comparison against another runtime.

Measured on 2026-11-16, all eight cases completed with 100,000 unique payloads
verified per case (800,000 records total):

| Activity | Run seconds | Debug seconds | Direct archive seconds | Engine archive seconds |
| --- | ---: | ---: | ---: | ---: |
| Mapper | 38.91 | 41.95 | 11.72 | 18.61 |
| Transformer | 27.50 | 30.72 | 9.08 | 15.05 |

See the [aggregate evidence](validation/mapping-conformance-summary-2026-11-16.json)
for exact values and individual report filenames. The original direct archive
default-operation failure is retained in
`validation/mapping-transformer-python-direct-before-default-export-fix-2026-11-16.json`.
The shared harness's older reports use a generic Mapper scope label even for the
Transformer workload; the `family` field selects the activity actually executed.

From the repository root with backend/test dependencies available:

```text
python scripts/flow-throughput.py --family mapper --mode run --records 100000 --deadline 600 --output tmp/mapper-run.json --diagnostics tmp/mapper-run-logs
python scripts/flow-throughput.py --family transformer --mode run --records 100000 --deadline 600 --output tmp/transformer-run.json --diagnostics tmp/transformer-run-logs
```

Repeat each with `debug`, `python-direct` and `python-engine` and fresh output paths.
No broker or network service is required. Keep temporary generated files out of Git.
