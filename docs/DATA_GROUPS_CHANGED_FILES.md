# Header/detail/trailer and whole-file validation changes

| File | Change |
| --- | --- |
| [backend/app/data_groups.py](D:/Integration-tool/IntegrationFabric/backend/app/data_groups.py) | Explicit HDT framing, role layouts, bounded groups, trailer checks/derivation, disk-backed file uniqueness, totals/counts and complete-file staged XSD validation. |
| [backend/app/data_stream.py](D:/Integration-tool/IntegrationFabric/backend/app/data_stream.py) | Whole-file guards in ordinary streams; grouped dispatch; full-XSD precedence over batch checks and record-only schema inference. |
| [backend/app/data_formats.py](D:/Integration-tool/IntegrationFabric/backend/app/data_formats.py) | Expose grouped/global options; enforce streaming requirement; infer fields from the record shape rather than root attributes. |
| [backend/app/raw_python.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python.py) | Selectively include the new grouping/validation module in direct Data archives. |
| [frontend/src/ActivityEditor.tsx](D:/Integration-tool/IntegrationFabric/frontend/src/ActivityEditor.tsx) | Grouping/full-file checkboxes, typed dynamic layout/rule inputs, and validation/count metadata. |
| [backend/tests/test_data_groups.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_data_groups.py) | Delimited/fixed layouts, framing, controls, derivation, rejected details, global XSD keys/keyrefs, root attributes, batch precedence, cancellation, atomic failures and four-mode flows. |
| [backend/tests/test_engine_export.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_engine_export.py) | Assert the new helper is included only for Data activities. |
| [frontend/scripts/data-stream-contract.test.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/data-stream-contract.test.mjs) | Verify typed rule/layout Inputs, checkboxes and validation metadata in actual Studio contracts. |
| [scripts/data-group-qa.py](D:/Integration-tool/IntegrationFabric/scripts/data-group-qa.py) | Reproducible 5,000-group audit through Run/Debug/both archives, including late EOF failures. |
| [docs/DATA_GROUPS_VALIDATION.md](D:/Integration-tool/IntegrationFabric/docs/DATA_GROUPS_VALIDATION.md) | Layout/rule examples, semantics, safety, resource limits and verification. |
| [docs/DATA_NESTED_STREAMING.md](D:/Integration-tool/IntegrationFabric/docs/DATA_NESTED_STREAMING.md), [docs/PARSE_RENDER_ACTIVITIES.md](D:/Integration-tool/IntegrationFabric/docs/PARSE_RENDER_ACTIVITIES.md) | Replace earlier limitations with links to grouped and whole-file functionality. |
| [docs/validation/data-groups-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/data-groups-summary-2026-11-16.json) | Test results and bulk-flow evidence. |
| [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs), [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) | Include new guide and implementation/test sources in Studio help. |
| [frontend/public/help/](D:/Integration-tool/IntegrationFabric/frontend/public/help/) | Regenerated web help, source manifest and both PDF manuals. |
| [frontend/dist/index.html](D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) | Verified production Studio bundle entry. |

Synthetic files, SQLite indexes and generated QA archives are test artifacts;
temporary copies remain under ignored [tmp/](D:/Integration-tool/IntegrationFabric/tmp/) and are not deployment dependencies.
