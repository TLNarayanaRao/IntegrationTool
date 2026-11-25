# Mapping qualification changed files

Changes for this request only. No dependency versions or vendor binaries were added. Temporary applications, diagnostics and Python environments stay under ignored `tmp/`.

- [backend/app/script_transform.py](D:/Integration-tool/IntegrationFabric/backend/app/script_transform.py) — Lazy evaluation, comparisons, null/collection behavior, added functions, Unicode/numeric parsing, token reuse and safer XML/error handling.
- [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) — Run scripted transforms off the async event loop.
- [backend/app/raw_python.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python.py) — Allow the default Transformer operation in direct exports and declare XML-reader dependencies for both archives.
- [backend/tests/test_transform_semantics.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_transform_semantics.py) — Regression cases for semantic defects, new operations and explicit unsupported-feature errors.
- [backend/tests/test_transform_execution_parity.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_transform_execution_parity.py) — Reviewed preview/Run/Debug/archive outputs and async responsiveness.
- [backend/tests/test_flow_throughput.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_flow_throughput.py) — Add Transformer to shared flow correctness checks.
- [scripts/flow-throughput.py](D:/Integration-tool/IntegrationFabric/scripts/flow-throughput.py) — Benchmark equivalent Mapper and scripted Transformer complete flows.
- [frontend/src/ActivityEditor.tsx](D:/Integration-tool/IntegrationFabric/frontend/src/ActivityEditor.tsx) — Add object-filter/extrema templates and update Transformer help.
- [frontend/dist/index.html](D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) — Local build entry regenerated to reference the new compiled bundle; regenerate build output in another workspace rather than copying this file alone.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) — Include the comparison and qualification guide in Studio Help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) — Fingerprint the new semantic and execution tests.
- [docs/MAPPING_CONFORMANCE.md](D:/Integration-tool/IntegrationFabric/docs/MAPPING_CONFORMANCE.md) — Capability comparison, fixes, limits, sources and reproducible measurements.
- [docs/validation/mapping-conformance-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-conformance-summary-2026-11-16.json) — Aggregate evidence and explicit remaining gaps.
- [docs/validation/mapping-transformer-python-direct-before-default-export-fix-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-transformer-python-direct-before-default-export-fix-2026-11-16.json) — Retained failed pre-fix direct-export attempt.
- [docs/validation/mapping-mapper-run-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-mapper-run-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-mapper-debug-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-mapper-debug-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-mapper-python-direct-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-mapper-python-direct-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-mapper-python-engine-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-mapper-python-engine-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-transformer-run-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-transformer-run-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-transformer-debug-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-transformer-debug-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-transformer-python-direct-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-transformer-python-direct-2026-11-16.json) — 100,000-record complete-flow result.
- [docs/validation/mapping-transformer-python-engine-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/mapping-transformer-python-engine-2026-11-16.json) — 100,000-record complete-flow result.
- [frontend/public/help/documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) — Regenerated Studio Help/manual artifact.

