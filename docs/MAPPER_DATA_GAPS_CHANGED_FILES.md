# Mapper record and Data activity gap fixes — 2026-11-16

Only changes for this gap review are described below; earlier uncommitted work
in the workspace remains separate.

| File | Change |
| --- | --- |
| `backend/app/mapping_documents.py` | Align large JSON numeric equality with record keys and XSLT; normalize integral minimum/maximum results. |
| `backend/app/data_formats.py` | Match header types by name; enforce strict render field sets; retain signs with zero padding; reset cursors for layout/validation changes; reject invalid options; add opt-in full XSD record validation in Parse/Render Data. |
| `frontend/src/ActivityEditor.tsx` | Expose XSD validation checkboxes and dynamic format options; clarify strict-field/header handling and record-error limits. |
| `backend/tests/test_data_activity_gaps.py` | Header order, strict layouts, numeric padding, cursor resets, schema facets, invalid settings and validated/rejected/dynamic-off flows in Run/Debug/both archives. |
| `backend/tests/test_format_activities.py` | Verify mapped Data validation with imported shared layouts and XSD dependencies in every execution mode. |
| `backend/tests/test_mapping_records.py` | Large numeric reconciliation and min/max/sum/average consistency. |
| `backend/tests/test_mapper_document_xslt.py` | Portable JSON Diff, reconciliation and aggregate regressions for large scientific-notation numbers. |
| `frontend/scripts/developer-documentation.mjs` | Register the new Data gap test source in developer help. |
| `docs/PARSE_RENDER_ACTIVITIES.md` | Explain XSD validation, header matching, strict rendering, cursor invalidation and remaining limits. |
| `docs/MAPPER_DOCUMENT_OPERATIONS.md` | Clarify numeric comparison and aggregation behavior. |
| `docs/validation/mapper-data-gaps-summary-2026-11-16.json` | Verification results and limits. |
| `frontend/public/help/` | Regenerated web/PDF help and source fingerprints. |
| `frontend/dist/index.html` | Rebuilt production Studio bundle entry. |

Temporary logs and generated verification archives stay under ignored `tmp/`.
