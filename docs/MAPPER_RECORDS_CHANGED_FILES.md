# Mapper record mediation additions — 2026-11-16

Changes in this request add grouped record metrics and snapshot reconciliation.
Earlier uncommitted Mapper work remains separate.

| File | Change |
| --- | --- |
| `backend/app/mapping_documents.py` | Bounded, non-mutating `aggregateRecords` and `reconcileRecords`; typed composite keys, stable order, strict metric/key checks and result growth limits. |
| `backend/app/mapper.py` | Dispatch both functions through the shared expression/pipeline engine. |
| `backend/app/transform_libraries.py` | Export both functions from `mina::Records` for scripts. |
| `backend/app/mapper_document_xslt.py` | Embed standalone XSLT 3.0 implementations, force full snapshot-key validation and bound result appends. Also accept scientific-notation JSON numbers without casting through binary floating point. |
| `frontend/src/mapper-functions.ts` | Shared Input/Visual Mapper palette, drag templates, pipeline defaults, descriptions and typing suggestions. |
| `backend/tests/test_mapping_records.py` | Grouped metrics, precision, changes, typed keys, empty/null data, duplicate/missing keys, mutation protection, output bounds, preview, scripts, Run, Debug and both Python archives. |
| `backend/tests/test_mapper_document_xslt.py` | Standalone binding round-trips plus preview/Run/Debug/archive execution of the new functions; scientific notation and rejection/bounds regressions. |
| `frontend/scripts/mapper-assistant.test.mjs` | Shared catalog availability and templates for both new functions. |
| `docs/MAPPER_DOCUMENT_OPERATIONS.md` | Usage, examples, key/null/error semantics, execution support and limits. |
| `docs/TRANSFORM_RUNTIME_FEATURES.md` | Updated portable script module exports. |
| `frontend/scripts/developer-documentation.mjs` | Include the record verification source in Studio developer help. |
| `docs/validation/mapper-records-summary-2026-11-16.json` | Verification results and scope. |
| `frontend/public/help/` | Regenerated web help data/build manifest and both PDF manuals. |
| `frontend/dist/index.html` | Updated verified production bundle entry. |

Verification artifacts and generated test archives remain under ignored `tmp/`.
