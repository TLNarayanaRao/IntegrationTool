# Transformation and mediation capabilities

The Mapper remains the transformation activity. General activities provide
durable message composition and recovery without reintroducing Mediation.

## Mapper schemas and suggestions

The Mapper supports multiple named views of one source, each with its own
schema, optional XSD complex type, and occurrence range. Keep schema files
at their project-relative paths when importing or editing the contract.
The Mapper resolves imports and includes from project assets. A repeating element
stays an array in the structured result even when the generated XML has one
occurrence; the XML itself retains the original element structure.

In **Visual AI Mapper → AI mapping options**, choose **Exact names** or a
similarity strategy. Select a source or target branch to limit matching to
that branch, then set each side's search depth from 1 to 10 (default 4).
Leave a side on **Entire schema** to search all fields on that side. Existing
manual mappings are preserved.

### Drop a repeating structure

On Mapper **Input**, drag a repeating complex source onto a repeating complex target and choose **Finish** after selecting a mapping mode:

- **Make a copy of each** copies the whole collection. The target shows one **[Copy-Of]** row with its source expression and hides the children. Existing child mappings in that occurrence are replaced. Clear the copy to show the children again. Use this when the source items already match the target structure.
- **For each** adds a **[For-Each]** row for the collection and keeps the item and its children visible. Matching paths are filled in without regard to case. Children display expressions relative to the current item, such as `Name` or `Address.City`, and remain editable.
- **SmartMap** builds an editable loop and also matches child paths that differ by underscores or hyphens. Ambiguous matches are left unmapped.

The same three choices are available on other activity **Input** tabs and in **Edit mappings** when both structures expose repeating records. This includes **Call Sub Task** inputs and **End** return mappings when the task has a schema. Drops onto simple fields still map the value directly.

To add another source for a repeating target, right-click the row and choose **Duplicate mapping**. This works in Mapper and other activity Input editors, including **Call Sub Task** and **End**. You can duplicate an unmapped repeating field too. The new occurrence starts with empty bindings. Drop a different collection onto it and choose a mapping mode for complex records. The original keeps its source and child bindings. At runtime the original items come first, followed by the configured duplicates in order. An occurrence with no source adds no items.

Use **Map & Test** to check the generated result before running or exporting the flow.

### XML expressions and bindings

In Mapper **Configuration**, choose the XPath version and expand **XML
expressions and runtime binding**. Set the XML source to a mapping path such as
`${last.xmlString}`, or leave it empty to use the previous activity's XML
output. Add namespace prefixes and variables as JSON objects. For example,
`{"ord":"urn:orders"}` binds a namespace and
`{"minimum":"${input.minimum}"}` binds a value to `$minimum`.

In **Input**, enter an expression such as
`xpath('string(/ord:orders/ord:order[@id=$minimum]/@id)')`.
The **XPath expression builder** can test a raw formula against sample XML or
a JSON envelope and apply it to the selected target. Choose a function to
display its arguments. Drag a sample XML field into an argument, or select the
field and use the argument's button. In XPath 2.0, the target cast action wraps
the current formula in the target's supported XML Schema constructor.
XPath node selections return sequences. Use an XPath scalar function when the
target expects one value. Map & Test accepts raw XML or a JSON input envelope.
XPath resource loading is disabled. XPath 2.0 regex functions run in an isolated
worker with a deadline.

Import an `.xsl` or `.xslt` file or edit the binding directly to select manual
XSLT. A manual XSLT 1.0 or 2.0 binding publishes `xmlString` and
structured XML values. Select a target XSD to validate the generated XML.
Referenced XSDs must be present in project schemas under their declared
locations. Stylesheets run with file and network access disabled. XML inputs,
stylesheets, and parsed results are limited to 8 MiB per document. XSLT 2.0
runs in a separate SaxonC worker with a scrubbed environment and a deadline.
The configured XML variables also supply stylesheet parameters. XSLT 2.0
accepts XML-valued parameters as document nodes.

In **Configuration**, use **Source type overrides** to coerce specific source
paths before formulas and XML parameter binding. For example,
`{"input.order.amount":"decimal"}` converts the input amount to a number.

In **Input → Source coercions and cardinality**, create named views of the same
source path. Set optional, exactly one, repeating, or at least one. Select a
project schema to copy its contract into the view, or enter an inline contract.
For XML, a named complex type must be valid for the source element's declaration.
For JSON, the selected contract validates each occurrence. Choose a view or one
of its fields from Data Sources. Occurrence ranges and type validation apply
when a rule reads that view. Source views run in visual mapping mode.

In the XPath builder, use **Check XPath 1.0 quick fix** or **Check XPath 2.0
quick fix** to compare the two evaluations. Apply a passing fix to the selected
visual mapping. Other mappings keep their existing XPath version. A matching
sample result does not establish equivalence for every possible input.

In **Input → Open visual AI Mapper**, use **Download XSLT** to save the active
stylesheet or generate XSLT 2.0 from direct rules. Generation supports XML element
paths, scalar constants, If, Choose, For-Each, For-Each-Group, nested loops,
and duplicate loop occurrences with mapped children. It supports trim,
normalize space, and case conversion. A selected
XSD must have one root and a uniform element qualification policy. Supply an
XML sample with the named document root for testing. Use **Open XSLT** to restore
the editable mappings from a generated file. **Use generated XSLT** binds
execution to the current visual rules. **Generated XML binding preferences**
controls optional field existence checks, suppression when a nil source maps
to an optional non-nillable target, and copying `xsi:nil` to nillable targets.
Generated conditions accept XML field paths, scalar literals, comparisons,
and logical operators. Custom functions and mapping statements outside this
subset require a handwritten stylesheet.

The XPath builder provides extension functions such as `ext:trim`,
`upper-case`, `lower-case`, `left`, `right`, `concat-sequence`, `xor`,
`substring-before-last`, `substring-after-last`, `timestamp`,
`base64-to-hex`, and `hex-to-base64`.
`project:getModuleProperty` reads scalar MINA project
properties supplied to the execution. Java system properties, proprietary
extensions, and custom Java XPath functions require a separate migration.

### Legacy process import

Open a compatible process file or ZIP through Studio's project
import. Supported sequences, simple scopes, conditional XPath links,
no-match links, error links, static subtask calls, Mapper bindings, XML render,
file activities, and basic outbound HTTP requests become MINA activities.
Supported HTTP, JMS and Timer event definitions become native starters.
HTTP XML reply bindings become response activities. The importer also reads
supported HTTP client and server settings, non-XA JDBC resources and static
SQL activities, and JMS text-message activities with direct or JNDI connections.
Passwords are represented by empty deployment properties. Project XSDs are included. Check the
import messages in Studio for processes and settings that need review.
Unsupported processes can contribute standalone Mapper tasks for their
recoverable bindings. Supply original activity variables as task input for
these standalone tasks. REST/SOAP service descriptors, explicit BPEL join
expressions, XA transactions, vendor-specific JDBC/JMS features, and proprietary
transport policies still need manual conversion.

### Shared Smart Mapper learning

Use **Share reviewed mappings** in Visual AI Mapper after reviewing direct
field mappings. The Studio server stores field paths and schema fingerprints.
Recommendations for the same source and target schema rank shared field pairs
first. Disabled rules, pending suggestions, formulas, and literal values
are excluded from learning. The catalog is stored in the Studio server's
data directory and is available to Studio users connected to that server.

Both Python archive formats include `requirements-mapper.txt` when they use
XML bindings. Install those dependencies in the target runtime before running
the archive.

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
