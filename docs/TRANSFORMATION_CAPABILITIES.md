# Transformation and mediation capabilities

The Mapper remains the transformation activity. General activities provide
durable message composition and recovery without reintroducing Mediation.

## Mapper tests, templates and contracts

Open **Map & Test** and expand **Saved transformation tests**. Give each case a
name, an input JSON value and an independently reviewed expected JSON value.
Save the case and run the suite. Failures show field paths, expected/actual
values and contract errors in dark red. Tests remain in the activity config and
survive project save/export/import. They do not call connectors.

**Versioned templates and schema changes** exports a `.mtemplate.json` file
containing schemas, mapping rules, lookup tables, execution policies, custom
functions and test cases. Templates have a format version and content checksum;
the checksum detects corruption, not authenticity. Import a template into another
Mapper. Project schema IDs are cleared because IDs are project-specific. Local
history retains the last 20 exported versions; changed content requires a new
version. Restore a version, review its contract and rerun its tests.

Capture a contract baseline before changing the selected schema. Compare the
current contract to see added/removed/changed fields, affected target mappings
and raw contract changes. This reports changes; it is not a full backward
compatibility proof for every schema dialect.

The portable validator now checks JSON `pattern`, `patternProperties`, common
formats, conditional contracts (`if`/`then`/`else`), dependent required fields,
property names and `contains` counts, in addition to the previous checks.
Supported asserted formats are date, date-time, time, IPv4, IPv6, UUID, email,
hostname and URI; unknown formats remain annotations. Pattern matching has a
100 ms timeout and requires the `regex` package, declared in deployment
qualification when a schema uses patterns. XSD restrictions support enumeration,
length bounds, numeric bounds and digit constraints. XSD patterns use the
portable regex dialect with full matching; XML Schema-specific regex syntax
and complete JSON Schema/XSD conformance are not claimed.

## Lookups, enrichment and joins

Save named JSON lookup tables under **Lookup tables and execution limits**:

```json
{"countries": {"US": "United States", "IN": "India"}}
```

Use `lookupTable(${input.country}, "countries", "Unknown")` in Mapper, or
append a `lookupTable("countries", "Unknown")` pipeline step. Keys are
case-sensitive. `lookup(value, table, default)` accepts an object table directly;
`enrich(record, fields)` merges objects with enrichment fields taking precedence;
`joinBy(left, right, leftKey, rightKey)` produces matching merged records;
`chunks(records, size)` splits an array into batches. Missing join keys do not
match. Many-to-many joins stop at 100,000 result records.

## Large data and cancellation

Mapper has evaluation-step, execution-time and output-size limits. Defaults are
100,000 evaluation steps and 30 seconds. Execution runs in a worker thread;
workflow cancellation signals the evaluator at subsequent evaluation checks.
These are cooperative limits, not preemption of every individual function or
vendor call. Input has target-field search and collapse/expand controls, so
users can focus on a small portion of a large schema without losing mappings.

Both Python archive formats include:

```powershell
python run_tests.py
Get-Content records.jsonl | python transform_jsonl.py --activity main/map --batch-size 100
```

`run_tests.py` runs saved suites and exits nonzero when any case fails or no
saved suites exist. `transform_jsonl.py` processes one JSON record per line and
prints one mapped JSON record per line. It runs Mapper alone, without connectors.
Records are limited to 1 MB; batches default to 16 MB of serialized input/output
and mapped records default to a 1 MB output limit. Use a smaller batch if the
batch quota is exceeded. Output written before an error remains written; stage
the output before publishing if all-or-nothing delivery is needed.

## Durable message activities

Use an explicit **Message namespace** for each integration and the same
**Durable state file** for cooperating activities. `MINA_MESSAGE_STATE_FILE`
can provide the file globally; the default is `message-state.sqlite3` under
`MINA_DATA_DIR` or the user's `.mina` folder. SQLite transactions coordinate
processes sharing the same local file. For containers, mount durable storage.
This is not a distributed database for multiple hosts or network filesystems.
Payloads are capped at 1 MB, aggregate groups at 64 MB and state capacity defaults
to 256 MB. Size accounting is an approximate SQLite page budget.

1. **Deduplicate Message** claims a stable message key and returns `accepted`
   and `claimToken`. Route on `accepted`: process accepted messages, skip or
   acknowledge duplicate deliveries according to the connector policy.
2. **Message Receipt** completes the exact claim token after downstream success
   or marks it failed on an error path. Stale/expired tokens cannot complete a
   newer claim. Acknowledge the broker only after successful work and receipt.
3. **Replay Messages** lists failed/expired candidates. `requeue` makes one
   explicit key claimable again; it does not execute downstream activities.
   Feed the returned stored payload back through the normal task deliberately.
   `purge` removes expired completed keys and old completed aggregates; it keeps
   failed and pending messages. Completed keys default to seven-day retention.
4. **Aggregate Messages** appends messages with a stable message ID and
   correlation key. Duplicate IDs do not increase the group count. When the
   expected count is reached, `ready=true` returns the records once; subsequent
   deliveries do not emit again. Check `ready` before forwarding. After a timeout,
   `flush` explicitly emits a partial group. A completed group needs a new
   correlation/window key for the next aggregation.
5. **Split Records** creates record batches from an array for use with the
   existing For Each group. It is an in-memory activity; use the JSONL tool for
   streaming file transformations.

These primitives support reliable processing but cannot guarantee exactly-once
external side effects. A crash between an external write and its receipt may
require replay; make the downstream write idempotent using the stable key.
Live broker/provider qualification remains necessary for production deployment.

## Visual mapper and generated previews

Open Visual AI Mapper from Mapper Configuration. The left pane contains editable source test data and available source paths, the middle pane contains saved mappings and the complete selected target schema field list, and the right pane displays generated output after Run mapping test. Named XSD types and local JSON Schema references use the same field parser as the Input tab. Source expressions remain editable, including upstream activity references and functions. Schema text is available under the collapsed schema sections.

Map & Test also displays generated output directly after running. JSON targets show formatted JSON; XSD targets show an XML preview with repeating elements and the target namespace. The preview does not change the Mapper runtime object or exported archive behavior; use Render XML or render-xml when the downstream activity requires a serialized XML value. Test data and the latest output are retained when saving the visual mapper.
