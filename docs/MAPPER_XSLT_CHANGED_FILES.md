# Mapper XSLT and JSON Patch root removal — changed files

Follow-up to the document/record functions added on 2026-11-16. Existing unrelated
workspace changes are preserved. This report lists changes for this request.

## Runtime and Studio

| File | Change |
| --- | --- |
| [mapper_document_xslt.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapper_document_xslt.py) | New self-contained XSLT 3.0 library for all eight document, record and privacy functions; public function overloads; typed keys, Unicode case folding and resource guards |
| [mapper_binding.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapper_binding.py) | Generate XSLT 3.0 for these functions; compile nested expressions, JSON literals, dynamic arguments and function pipelines; preserve editable round-trips and existing XSLT 2.0 generation |
| [mapping_documents.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapping_documents.py) | Support absent-root removal, root recreation and correct failures when later operations address a missing root |
| [mapper_xml.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapper_xml.py) | Accept XSLT 3.0 in the restricted Saxon worker; resolve ZIP import roots absolutely before switching worker directories |
| [raw_python.py](/D:/Integration-tool/IntegrationFabric/backend/app/raw_python.py) | Package the new library and declare Saxon for manual XSLT 3.0 as well as generated bindings |
| [ActivityEditor.tsx](/D:/Integration-tool/IntegrationFabric/frontend/src/ActivityEditor.tsx) | Show XSLT 3.0 as a supported runtime binding version |
| [mapper-functions.ts](/D:/Integration-tool/IntegrationFabric/frontend/src/mapper-functions.ts) | Explain root removal, null policy and XSLT support in JSON Patch palette help |

## Tests

| File | Change |
| --- | --- |
| [test_mapper_document_xslt.py](/D:/Integration-tool/IntegrationFabric/backend/tests/test_mapper_document_xslt.py) | New parity suite: 28 function cases, six join modes, standalone Saxon, generated/manual bindings, editable round-trips, dynamic/nested calls, XSD validation, error/limit cases, Run/Debug and both archives |
| [test_mapping_documents.py](/D:/Integration-tool/IntegrationFabric/backend/tests/test_mapping_documents.py) | Root removal for objects, arrays, scalars and null; recreation and failures after removal |
| [test_engine_export.py](/D:/Integration-tool/IntegrationFabric/backend/tests/test_engine_export.py) | Verify the new module is included in the engine dependency closure |
| [Validation summary](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-xslt-summary-2026-11-16.json) | Recorded verification results and scope |

## Documentation and generated assets

| File | Change |
| --- | --- |
| [Mapper guide](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_DOCUMENT_OPERATIONS.md) | XSLT generation/manual use, JSON-in-XML representation, root absence/null policy, limits and verification |
| [Earlier change report](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_STANDARDS_CHANGED_FILES.md) | Replace superseded restrictions with a link to this follow-up |
| [developer-documentation.mjs](/D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) | Add new implementation and regression-test source navigation |
| [documentation-data.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) | Regenerated Studio Help |
| [documentation-data.js](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) | Regenerated offline Help data |
| [developer-data.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) | Regenerated developer Help |
| [documentation-build.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) | Updated documentation fingerprints |
| [MINA-Documentation.pdf](/D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) | Regenerated user guide |
| [MINA-Developer-Guide.pdf](/D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated developer guide |
| [dist/index.html](/D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) | Production Studio build entry point; regenerate assets when building another checkout |
| [This report](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_XSLT_CHANGED_FILES.md) | Request-specific changed-file inventory |

## Interpretation

- XSLT takes JSON documents/arrays from XML text fields and emits object/array/null results as JSON text in a string-valued target XML field. It does not infer an XML element schema from JSON keys.
- A patch that leaves the root absent returns null at MINA's value boundary. Subsequent operations within the patch still see an absent document. Native Mapper's configured null policy controls omission/preservation of the target field.
- Generated stylesheets require the XSLT 3.0/JSON facilities verified with Saxon 13. Existing bindings without the new functions retain XSLT 2.0 generation.
- Verification here is functional regression coverage, not a new throughput/soak benchmark or a claim of certification against every XSLT processor.

## Verification results

- Final focused suite: **24 tests passed**, including the 28 function cases and generated/manual XSD-validated flows in Run, Debug, direct Python and engine Python archives.
- Full backend repeat: **703 tests, 11 skipped, no failures** (388.729 seconds). The first full run encountered an SFTP handshake failure; all seven SFTP tests passed on isolated recheck, followed by the passing full repeat. No SFTP source was changed.
- Studio Help: **15 tests passed**. TypeScript and production build passed; documentation source coverage and PDF/web fingerprints verified.
- The production bundler still reports its existing large-chunk advisory; the build succeeds.
