# Mediation: business messages without transformation scripts

Mediation is a separate activity in the transformation palette. Mapper and Transform remain unchanged. Use Mediation to normalize partner formats into a shared business contract using readable, deterministic rules. It does not use AI inference, contact external services, or execute user scripts.

## Configuration

Open Configuration, load an example or add business fields. Choose JSON, XML or CSV for input/output. Source collection selects a record or list using a dotted path (`orders`, `customer.orders`, `orders.0`) or `$` for the entire input. Each rule reads relative to the selected record. A list is processed record by record. Enable Always return collection to preserve an array even when XML contains only one record.

Rules provide a source path, target path, action and Required flag. Target paths such as `customer.name` build nested objects. Duplicate or overlapping targets are rejected instead of silently overwriting data. Actions include copy, trim, uppercase, lowercase, integer, number, boolean and dictionary lookup. A constant replaces the source; a default applies to missing/null fields before conversion. Enter constants/defaults as JSON values, for example `"Unknown"`, `0` or `true`. Required rejects absent input when no default exists. Unmapped fields are not copied automatically; optional absent fields are omitted.

## Input and output

## Load a target structure

Use **Target structure** in Configuration to select a project schema, upload a `.json`/`.xsd` file (up to 500 KB), or paste a schema. The schema is saved as an activity-local snapshot, so exported Python uses the same contract without contacting external schema servers. Reselect the project schema to refresh the snapshot after editing it.

The field list displays dotted target paths, types and required flags. Click **+ Map field** to add a mapping row, then supply its source. Existing rules are preserved. Arrays appear as whole-array targets; nested per-item mapping is not yet implemented. Preview and runtime validate types and required fields before serializing output. Object schemas apply to each record; an array schema validates the whole collection.

Supported JSON Schema keywords: `type`, `properties`, `required`, `items`, `additionalProperties`, and descriptive metadata (`title`, `description`, `$schema`, `$id`). References, unions, enums, patterns, numeric constraints and compositions are rejected. XSD supports one root element, sequences, inline/named non-recursive complex types and primitive types. This checks structure, not full XSD facets, namespaces or occurrence bounds. XML attributes, imports, choices and restrictions are rejected. No external references are fetched.

## Input and output contract

### Map previous activity outputs in Input

After loading a target schema in Configuration, open **Input**. The left Data pane lists available preceding activity outputs; the right tree lists target fields beneath `targetValues`. Drag a source onto a target, type an expression such as `${ReadOrder.id}`, or use **Edit mappings** for the expanded editor. These mappings are resolved for each invocation, not entered as fixed values in Configuration. An Input mapping overrides that field's recipe source; its conversion and final schema validation still apply. Unmapped fields retain existing recipe behavior. You can use only Input mappings with no recipe rules.

Map `payload` to select the message/collection to iterate. A directly mapped target value is resolved once per activity invocation and applies to every selected record; use record-relative recipe rules for per-record values. Whole arrays can be mapped directly; this does not add nested per-item iteration.

**Map & Test** accepts a synthetic context such as `{"activities":{"ReadOrder":{"output":{"id":"A-100"}}}}` to test `${ReadOrder.id}`. It never reruns ReadOrder or calls a connector. Use synthetic data only. Plain upstream references work in both Studio and exported Python; advanced Input mapping operators remain subject to the exporter's existing supported-expression limits.

The Input tab's payload mapping overrides the previous activity's output. With no override, the previous output is used. JSON input can be an object/list or JSON text. XML/CSV input is text. JSON output is an object or list; XML/CSV output is text. The activity publishes the document directly, not a wrapper containing `result`. Preview's records/rules/trace envelope is only a design-time explanation.

XML attributes become fields, repeated child elements become lists, and non-empty mixed text is stored under `_text`. XML output uses a configurable root and `record` elements for top-level arrays. DTDs/entities are rejected. This is not a namespace-preserving XML round-trip editor or an XSD validator. CSV output requires scalar, flat target fields; nested targets must instead use JSON/XML. CSV values are serialized faithfully; spreadsheet consumers must apply their own formula-injection protections before opening untrusted CSV.

## Try: normalize an order

Load **Normalize orders**, then Preview mediation. Input:

```json
{"orders":[{"id":"A-100","buyer":" Ana ","amount":"42.50","status":"N"}]}
```

The recipe selects `orders`, copies `id` to `order.id`, trims `buyer` into `customer.name`, converts `amount` to `order.total`, and looks up `N` as `New` for `order.status`.

```json
[{"order":{"id":"A-100","total":42.5,"status":"New"},"customer":{"name":"Ana"}}]
```

The other built-in examples demonstrate CSV customer records with lowercase email/boolean conversion, and XML orders with typed quantities and a stable collection output. Loading an example replaces the current recipe. Preview uses the same Python implementation as execution and performs no connector actions. Preview samples are saved with the project: use synthetic data, never credentials or personal production payloads.

## Advanced, errors and execution

Standard activity retry and payload logging policies apply. Avoid payload logging for sensitive messages. Studio Run/Debug uses a `MEDIATION` fault; exported Python raises `MediationError`. Conversion errors identify record/rule and target, not field values. Errors include missing required sources, unknown collection paths, invalid recipes, unsupported formats, missing lookup entries, invalid XML and non-flat CSV targets. Failed execution returns no partial result.

Limits are 200 rules, 10,000 selected records, 2 MB text input and 64 levels for XML traversal. This is bounded-batch processing, not a streaming large-file processor. Split larger payloads upstream. Recursive per-child collection mapping, joins, aggregation, chained actions, schema inference and full XSD validation are not part of this initial activity.

## Code and deployment

## Conditional target fields in Studio

Right-click a target field in Input and select **When / Otherwise**. Enter the number of When branches (1-100), then select **Create branches**. A Choose tree appears on that field, with expandable When rows and a final Otherwise row. Edit each condition and value inline; drag source fields into an individual condition or branch value. The first matching When supplies the field value. If none matches, Otherwise supplies it. Inactive branch values are not evaluated by the Studio runtime. Existing single When/Otherwise mappings remain editable. Use **Remove conditions** to clear the statement from that field.

## Implementation locations

- UI recipe editor: `frontend/src/MediationStudio.tsx`; styles: `mediation-studio.css`.
- Activity contracts/documentation: `frontend/src/ActivityEditor.tsx`; palette: `frontend/src/main.tsx`.
- Engine and validation: `backend/app/mediation.py`.
- Preview: `POST /api/mediation/test` in `backend/app/main.py`.
- Studio execution: Mediation branch in `backend/app/runtime.py`.
- Raw Python export: `backend/app/raw_python.py` links `application/native/mediation.py` only when Mediation is used; dispatch is in `raw_python_support/core.py`.
- Regression tests: `backend/tests/test_mediation.py`.

Deploy updated Studio/runtime code before authoring or running this new activity. Re-export packages containing it for deployed runtimes. Existing installations without this activity kind cannot run it. No vendor drivers are required for Mediation itself.
