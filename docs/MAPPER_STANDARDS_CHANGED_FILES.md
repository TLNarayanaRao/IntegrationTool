# Mapper document and record capabilities — changed files

This report covers the eight new Mapper functions added on 2026-11-16. Earlier
Mapper/Transformer changes already present in the workspace remain separate.

## Implementation

| File | Change |
| --- | --- |
| [mapping_documents.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapping_documents.py) | Bounded JSON Pointer, Patch, Merge Patch, diff, indexed joins, deduplication, redaction and masking |
| [mapper.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapper.py) | Shared function dispatch before string conversion; function validation inventory |
| [runtime.py](/D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) | Parse literal function arguments in generic Inputs; propagate failed End and HTTP Response operations |
| [raw_python.py](/D:/Integration-tool/IntegrationFabric/backend/app/raw_python.py) | Include the document-operation module in exported native Mapper dependencies |
| [transform_libraries.py](/D:/Integration-tool/IntegrationFabric/backend/app/transform_libraries.py) | Expose Documents, Records and Privacy script modules |
| [mapper-functions.ts](/D:/Integration-tool/IntegrationFabric/frontend/src/mapper-functions.ts) | Eight palette/typeahead descriptors, examples, and Document/Privacy categories |

## Verification

| File | Change |
| --- | --- |
| [test_mapping_documents.py](/D:/Integration-tool/IntegrationFabric/backend/tests/test_mapping_documents.py) | Semantics, limits, immutability, preview, generic Inputs, Run/Debug and both archives |
| [test_engine_export.py](/D:/Integration-tool/IntegrationFabric/backend/tests/test_engine_export.py) | Verify exported module closure |
| [mapper-standards-qa.py](/D:/Integration-tool/IntegrationFabric/scripts/mapper-standards-qa.py) | Reproducible complete-flow bulk join benchmark with output audit and sampled memory |
| [Validation summary](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-standards-summary-2026-11-16.json) | Functional and build checks plus benchmark results |
| [Run report](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-standards-run-2026-11-16.json) | 100,000 joined records verified |
| [Debug report](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-standards-debug-2026-11-16.json) | 100,000 joined records verified |
| [Direct Python report](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-standards-python-direct-2026-11-16.json) | 100,000 joined records verified |
| [Engine Python report](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-standards-python-engine-2026-11-16.json) | 100,000 joined records verified |

## Documentation and generated Studio assets

| File | Change |
| --- | --- |
| [Mapper guide](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_DOCUMENT_OPERATIONS.md) | Usage, examples, standards references, bounds and benchmark limitations |
| [Transformer guide](/D:/Integration-tool/IntegrationFabric/docs/TRANSFORM_RUNTIME_FEATURES.md) | New script module inventory and Mapper guide link |
| [build-documentation.mjs](/D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) | Include the new guide in Studio Help |
| [developer-documentation.mjs](/D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) | Include implementation, regression tests and QA script in developer Help |
| [documentation-data.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) | Regenerated activity/function Help with 111 functions |
| [documentation-data.js](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) | Regenerated offline Help data |
| [developer-data.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) | Regenerated developer Help |
| [documentation-build.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) | Updated documentation fingerprints |
| [MINA-Documentation.pdf](/D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) | Regenerated user documentation |
| [MINA-Developer-Guide.pdf](/D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated developer documentation |
| [dist/index.html](/D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) | Studio production build entry point; regenerate build assets in another workspace |
| [This report](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_STANDARDS_CHANGED_FILES.md) | Request-specific changed-file inventory |

## Results and limits

- Full backend suite: 697 tests, 11 skipped, no failures. Skips do not establish live-service coverage.
- Final focused regression suite: 30 tests passed, including failed terminal HTTP Response propagation.
- Help tests: 15 passed. TypeScript and Studio production build passed.
- Documents/Records/Privacy script imports passed in Run, Debug and both archive formats.
- Complete Start → bulk Mapper join → End flow: 100,000 records per side, all output records checked in all four modes, 2.42–5.33 seconds on this machine.
- This benchmark is not per-message orchestration or a long-duration memory soak. Debug sampled peak memory was 548.63 MiB.
- Follow-up implementation now supplies generated XSLT 3.0 functions and JSON Patch root removal. See [the XSLT follow-up report](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_XSLT_CHANGED_FILES.md) for its changed files and verification; benchmark timings above remain the earlier native bulk-join measurement.
