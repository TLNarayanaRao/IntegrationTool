# Assisted mapping and automatic repeating structures

Open a Mapper's **Input → AI Mapper**, then select **AI Map**. The assistant
builds an executable mapping plan from schemas, contract metadata or JSON samples.
It does not require an external AI account or send payloads to an external model.
The confidence score is a local matching rank, not a probability of correctness.

## Review, apply and undo

By default analysis leaves the current mappings unchanged. The review shows:

- Suggested fields with source paths, confidence and matching reasons.
- Automatically aligned nested repeating structures and repeated-value copies.
- Protected existing mappings, ambiguous candidates and unmatched targets.
- Required fields that still need attention.

Select **Choose this source** to resolve an ambiguous candidate, then analyze the
updated choice. **Apply reviewed suggestions** applies the plan as one operation;
**Discard plan** leaves mappings unchanged. **Undo AI Map** restores the mappings
from immediately before application. Undo is disabled after a subsequent mapping
edit so it cannot silently discard that edit. Existing **Require approval** may
be turned off to apply safe suggestions directly after analysis.

Changes to schemas, samples, upstream contracts, mapping rules or analysis options
cancel stale requests and discard the old review. An old response cannot replace
newer edits. A manual stylesheet remains authoritative until the user selects
**Use visual mappings** or **Use generated XSLT**; applying a visual plan is blocked
while a manual stylesheet supplies the runtime output.

## Detect repeating collections at every level

For example, a source can contain purchases with their own item collections:

```json
{"purchases":[{"id":1,"items":[{"sku":"A","qty":2},{"sku":"B","qty":3}]}]}
```

For a target schema declaring `orders[].lines[]`, the Commerce vocabulary can
produce this plan:

```text
orders                    For Each last.purchases
  id                      last.purchases.id
  lines                   For Each last.purchases.items
    productCode           last.purchases.items.sku
    quantity              last.purchases.items.qty
```

The inner collection stays inside its own outer record. Independent collections
are not flattened or combined into a Cartesian product. Repeating primitive
values such as `tags: ["A", "B"]` use **Copy-Of**, preserving array values rather
than creating empty objects. Generated XSLT supports these repeated scalar copies
as well as ordinary complex collection loops.

Source and target repeating depths and shapes must agree for automatic matching.
Repeating-to-scalar selection, aggregation and shape-changing coercions remain
explicit mapping decisions. Turning off **Infer repeating structures** excludes
automatic repeating mappings.

## Source detection and vocabulary

The assistant uses the selected source schema first, then a supplied JSON sample.
When neither is supplied, it can recover a schema from the single immediate
predecessor's output contract. It preserves declared array cardinality instead
of interpreting every child of a repeating parent as another array. Multiple
incoming predecessors are not chosen automatically. For XML sample text, select
a source XSD; a single XML example cannot establish the schema's cardinalities.

Open **AI mapping options** to choose a vocabulary:

| Vocabulary | Examples |
| --- | --- |
| General | identifier/id, telephone/phone, zip/postal, surname/lastName |
| Commerce / orders | client/customer, purchase/order, sku/productCode, qty/quantity |
| Finance / payments | transaction/payment, acct/account, amt/amount |

Add project-specific source/target term pairs when domain names differ. These
settings are saved with the Mapper. Case, camel case, underscores and hyphens
are normalized for name comparison; generated paths preserve original spelling.

Matching checks data types, parent context and all repeating ancestors. Balanced
matching uses names and hierarchy. Semantic matching gives more weight to
business terms. Strict matching requires identical types; other strategies can
accept integer-to-number widening. Exact matching uses normalized field names.
String/number parsing, date reformatting and other transformations are not guessed.

Previously **Share reviewed mappings** pairs for the same schema structure can
help suggestions. Sharing remains explicit and stores field-path preferences;
the assistant does not automatically train on payload values. Reviewed alias
paths are normalized so newly generated `last.*` mappings can be shared too.

## Preserve existing work

Authored mappings, constants, disabled rules, conditions and duplicate occurrences
are preserved. Ordinary active For-Each loops reading `last.*` can be reused to
fill missing children when all schema ancestors agree; the existing loop and
authored child rules remain unchanged. Grouped, conditional, duplicate and Copy-Of
structures protect their descendants. A new
loop is not inserted around authored child rules because that could change their
execution scope. Clear or explicitly edit that structure to remap it. Blank
direct placeholders can be filled; unapproved older suggestions are superseded
by the new analysis. A protected field is not necessarily an enabled mapping,
so required disabled targets are still reported for attention.

## Navigate large maps

**Find field** filters source paths, existing mappings, target fields and review
suggestions. **Unmapped targets only** includes disabled, unapproved and blank
mappings; descendants already covered by an active Copy-Of are excluded. Rendering
starts with 100 rows and **Show more** expands the view without removing mappings
from the project or changing runtime behavior.

All rule target inputs share one autocomplete list. The editor no longer builds
one full target dropdown per rule. **Add mapping** creates a blank rule at the
top of the view rather than preselecting an unrelated source.

## Validation and limits

Run **Run mapping test**, inspect Generated Output and resolve validation errors
before saving. Required-field warnings are conservative schema guidance;
conditional parent structures and provider-specific requirements still need
testing. Suggestions do not prove business correctness or production readiness.

Analysis supports JSON Schema properties/local references, project-selected XSD
structures (including resolved project dependencies), and JSON samples. Sample
inference examines up to 32 records per array and merges observed optional fields.
Empty/heterogeneous values cannot establish every type; select a schema for
complete information. Wrap a root array in a named object field before automatic analysis.
Format, enum and pattern constraints can require explicit functions and must still
pass the mapping test. Names containing literal dots/brackets are not automatically
mapped because the runtime's path notation would be ambiguous. Recursive or
polymorphic schemas can require a narrower explicit structure/manual mapping.

Analysis is bounded to 64 levels, 20,000 visited schema/sample values, 5,000 fields
per side and 5,000 final rules. It indexes exact names, vocabulary equivalents and
tokens, limits candidates to 1,000 per field and one million comparisons overall,
and asks for a narrower branch when these limits are reached. Conflicting loop
alignments are left unmapped rather than mixing unrelated collections.

Verification covers nested/empty collections, repeated scalar copies, aliases,
ambiguous choices, manual protection, required gaps, local references, XSDs,
generated XSLT, Studio preview and schema-validated Run/Debug/both Python archives.
Editor tests cover metadata inference and bounded, escaped review rendering.

On 2026-11-16 a synthetic 2,000-field plan took **0.070459 seconds**, examining
2,000 candidate pairs. Every mapped value was audited through complete flows:

| Mode | Elapsed seconds, including archive startup/cleanup where applicable |
| --- | ---: |
| Run | 0.027328 |
| Debug | 0.027825 |
| Direct Python archive | 0.789327 |
| Engine Python archive | 1.452183 |

These are single bulk-field measurements, not UI interaction latency, message
throughput or a long-duration memory soak. Reproduce with:

```text
python scripts/mapper-assistant-qa.py --fields 2000 --output-dir tmp/assistant-qa-new
```

See the [verification report](validation/mapper-assistant-summary-2026-11-16.json)
and [changed files](MAPPER_ASSISTANT_CHANGED_FILES.md).

## Studio browser verification and saved-flow execution

The 2026-11-16 browser retest used the supported Chromium in-app browser with
an isolated synthetic project. It exercised nested repeats, ambiguous matches,
existing authored constants and loop reuse, Discard, Undo, manual source edits,
sample edits, Save mapper and Input validation. Studio toolbar Run and Debug
both delivered a scheduler event through Call Sub Task into the saved Mapper
and completed the flow. Popup controls remained reachable at 1024 × 600 with
150% screen font as well as the normal 1280 × 720 view.

JSON samples now expose their nested object and array fields in the shared
schema tree. Samples examine up to 32 records per array; select an explicit
schema when later records may contain additional fields. Explicit JSON Schema
and compact field definitions remain supported.

New assistant rules use `${last.field}` references, which are recognized in
Input validation and source suggestions. Existing ordinary loops using bare
`last.field` references remain supported. Preview preserves these aliases so
old outer loops and new nested rules execute in the same scope.

Generated Output is cleared when mappings, test data, schemas or execution
options change, including Undo. Run the mapping test again to see current
output. An in-flight test is cancelled/ignored when its inputs change, and
outdated saved preview values are removed from the configuration.

The browser-saved rules were executed unchanged through Run, Debug, direct
Python and engine Python archives. Every output value was compared for the
nested-repeat, explicitly chosen ambiguous source and existing authored-loop
cases. The scheduler wrapper was also checked in Run and both archives;
Studio drives its Debug event lifecycle interactively.

Recheck a captured QA project containing the `nested`, `ambiguous` and `existing`
tasks with the same synthetic fixtures:

```text
python scripts/mapper-studio-saved-qa.py --project tmp/saved-project.json --output-dir tmp/saved-mapper-qa-new
node --test frontend/scripts/mapper-assistant.test.mjs
```

These are functional checks, not a production throughput or long-duration soak
claim. See [browser and execution evidence](validation/mapper-studio-ui-summary-2026-11-16.json)
and the [files changed for this retest](MAPPER_STUDIO_UI_CHANGED_FILES.md).
