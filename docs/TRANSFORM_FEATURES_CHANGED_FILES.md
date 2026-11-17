# Transformation feature changed files

Files changed for this follow-up. Earlier workspace edits were retained. No vendor binaries or dependency version changes were added. Temporary synthetic inputs, generated archives, output files and diagnostic logs remain under ignored `tmp/`.

- [backend/app/transform_engine.py](D:/Integration-tool/IntegrationFabric/backend/app/transform_engine.py) — Shared schema resolution, transactional output plans, record mapping contexts and cooperative worker cancellation.
- [backend/app/transform_libraries.py](D:/Integration-tool/IntegrationFabric/backend/app/transform_libraries.py) — Configured modules/constants and explicit built-in module exports, lexical scope and import limits.
- [backend/app/transform_stream.py](D:/Integration-tool/IntegrationFabric/backend/app/transform_stream.py) — Incremental bounded JSON/JSONL/CSV readers and atomic streaming file writers.
- [backend/app/transform_visual.py](D:/Integration-tool/IntegrationFabric/backend/app/transform_visual.py) — Script/object mapping conversion with expression-preserving fallbacks.
- [backend/app/dataweave.py](D:/Integration-tool/IntegrationFabric/backend/app/dataweave.py) — Qualified module identifiers, multiline declarations, import binding and module function calls.
- [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) — Use the shared transformation pipeline and expose transformed message attributes to mappings.
- [backend/app/raw_python_support/core.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python_support/core.py) — Match runtime output commits, streaming references, contexts and attributes in direct archives.
- [backend/app/raw_python.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python.py) — Package transitive modules, selected schemas and deployment requirements; preserve literal script/library definitions.
- [backend/app/schema_validation.py](D:/Integration-tool/IntegrationFabric/backend/app/schema_validation.py) — Accept an explicitly provided offline project schema registry.
- [backend/app/main.py](D:/Integration-tool/IntegrationFabric/backend/app/main.py) — Shared preview configuration and safe visual/script API endpoints.
- [backend/tests/test_transform_features.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_transform_features.py) — Library, output, schema, preview, visual, streaming, rollback/cancellation and cross-mode regressions.
- [backend/tests/test_transform_semantics.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_transform_semantics.py) — Update unsupported-import regression for the new module allowlist.
- [backend/tests/test_transform_execution_parity.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_transform_execution_parity.py) — Preserve responsiveness coverage through the shared planner.
- [backend/tests/test_engine_export.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_engine_export.py) — Verify the expanded, capability-selected transformation dependency closure.
- [scripts/flow-throughput.py](D:/Integration-tool/IntegrationFabric/scripts/flow-throughput.py) — Expose the archive interpreter's self-reported PID for accurate memory sampling.
- [scripts/transform-stream-qa.py](D:/Integration-tool/IntegrationFabric/scripts/transform-stream-qa.py) — Repeatable eight-mode 100,000-record file-stream audit with source/target contracts and RSS sampling.
- [frontend/src/TransformerFeatures.tsx](D:/Integration-tool/IntegrationFabric/frontend/src/TransformerFeatures.tsx) — Module, output, stream and synchronized script controls with stale-response protection.
- [frontend/src/ActivityEditor.tsx](D:/Integration-tool/IntegrationFabric/frontend/src/ActivityEditor.tsx) — Connect the new editors, XSD structure selection and complete output preview.
- [frontend/src/activity-editor.css](D:/Integration-tool/IntegrationFabric/frontend/src/activity-editor.css) — Readable dark-red visual-mapping diagnostics.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) — Include the runtime feature guide in Studio Help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) — Fingerprint shared implementation and qualification sources.
- [docs/TRANSFORM_RUNTIME_FEATURES.md](D:/Integration-tool/IntegrationFabric/docs/TRANSFORM_RUNTIME_FEATURES.md) — Feature instructions, supported inventories, limits and measured results.
- [docs/MAPPING_CONFORMANCE.md](D:/Integration-tool/IntegrationFabric/docs/MAPPING_CONFORMANCE.md) — Update the earlier capability assessment with the completed feature areas.
- [docs/validation/transform-features-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-features-summary-2026-11-16.json) — Aggregate feature, test and streaming qualification evidence.
- [frontend/dist/index.html](D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) — Generated local build entry; rebuild in another workspace instead of copying this file alone.
- [docs/validation/transform-stream-mapper-run-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-mapper-run-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-mapper-debug-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-mapper-debug-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-mapper-python-direct-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-mapper-python-direct-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-mapper-python-engine-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-mapper-python-engine-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-dataweave-run-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-dataweave-run-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-dataweave-debug-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-dataweave-debug-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-dataweave-python-direct-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-dataweave-python-direct-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [docs/validation/transform-stream-dataweave-python-engine-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/transform-stream-dataweave-python-engine-2026-11-16.json) — Sanitized complete-stream output audit and interpreter RSS samples.
- [frontend/public/help/documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) — Regenerated Studio Help/manual artifact.
- [frontend/public/help/MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) — Regenerated Studio Help/manual artifact.

