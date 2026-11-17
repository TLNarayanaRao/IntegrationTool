# Nested and streaming Data activities — changed files

| File | Change |
| --- | --- |
| [backend/app/data_stream.py](D:/Integration-tool/IntegrationFabric/backend/app/data_stream.py) | Nested JSON Pointer layouts, schema column inference, bounded logical-row recovery, JSON Lines input/output, byte-limited batches and atomic file publication. |
| [backend/app/data_formats.py](D:/Integration-tool/IntegrationFabric/backend/app/data_formats.py) | Nested parsing/rendering and JSON columns; seek-cookie checkpoints; streaming dispatch; asynchronous cooperative cancellation; fixed-field newline protection. |
| [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) | Await responsive Data execution and cancellation. |
| [backend/app/raw_python.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python.py) | Include async Data dispatch and selectively package streaming helpers only for Data activities. |
| [backend/app/raw_python_support/activities.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python_support/activities.py) | Shared async Data helper in direct archives. |
| [backend/app/raw_python_support/core.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python_support/core.py) | Await Data operations instead of blocking the archive event loop. |
| [frontend/src/ActivityEditor.tsx](D:/Integration-tool/IntegrationFabric/frontend/src/ActivityEditor.tsx) | Nested/streaming checkboxes, dynamic paths/limits/recovery controls, file metadata output and nested schema trees. |
| [backend/tests/test_data_stream.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_data_stream.py) | Nested/XSD/JSON paths, repeating children, malformed quote replay, byte batches, UTF-16/separators, atomic failures, source changes, cancellation and four-mode flows. |
| [backend/tests/test_data_activity_gaps.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_data_activity_gaps.py) | Update malformed-quote expectation to the new explicit recovery behavior. |
| [backend/tests/test_engine_export.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_engine_export.py) | Assert selective streaming helper linkage for Data exports. |
| [frontend/scripts/data-stream-contract.test.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/data-stream-contract.test.mjs) | Verify actual Studio contract fields, nested path types, streaming metadata and legacy record mode. |
| [scripts/data-stream-qa.py](D:/Integration-tool/IntegrationFabric/scripts/data-stream-qa.py) | Reproducible large-file complete-flow audit, hashes and sampled process RSS. |
| [docs/DATA_NESTED_STREAMING.md](D:/Integration-tool/IntegrationFabric/docs/DATA_NESTED_STREAMING.md), [docs/PARSE_RENDER_ACTIVITIES.md](D:/Integration-tool/IntegrationFabric/docs/PARSE_RENDER_ACTIVITIES.md) | Usage, streaming/recovery contracts, validation scope, limits and measurements. |
| [docs/validation/data-stream-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/data-stream-summary-2026-11-16.json) | Focused tests and large-file evidence. |
| [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs), [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) | Include the guide and implementation/test sources in Studio help. |
| [frontend/public/help/](D:/Integration-tool/IntegrationFabric/frontend/public/help/) | Regenerated web data, source fingerprints and both PDF manuals. |
| [frontend/dist/index.html](D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) | Verified production bundle entry. |

Synthetic large files, temporary logs and generated test archives remain under
ignored [tmp/](D:/Integration-tool/IntegrationFabric/tmp/) and are not runtime dependencies.
