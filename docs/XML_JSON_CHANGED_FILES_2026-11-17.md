# XML/JSON changed files — 2026-11-17

Paths are relative to the repository root. Generated test archives and logs under `tmp/` are not deployment dependencies.

The isolated native fixture uses `tmp/bw613-xml-json-20261117/configure.py --extended` and the resulting `tmp/bw613-xml-json-20261117/workspace/MinaFormatCompare/Processes/MinaFormatCompare/Main.bwp`. The local `extended-import-qa.py` exercises the recovered activities, and `compare-extended.py` checks native and MINA output pairs. The repository tests cover the imported formats independently of this local workspace.

| File | Change |
|---|---|
| `backend/app/bw_process.py` | Import qualified CDATA selectors and recognize the native XML render input binding. |
| `backend/app/data_formats.py` | Mapped JSON input precedence, typed simple content, null handling, namespaced schema lookup, XML style checks, encoding-safe CDATA, and dynamic encoding from imported XML render bindings. |
| `backend/app/xsd_openapi.py` | Project simple-content primitive types through inheritance and retain typed text metadata and valid examples. |
| `frontend/src/ActivityEditor.tsx` | Expose inherited simple-content text in schema trees and match XSD Parse JSON source paths to normalized runtime aliases, preserving Native JSON names. |
| `backend/tests/test_xml_json_conformance.py` | Fourteen regressions, including qualified CDATA and the mapped encoding override in all four modes. |
| `backend/tests/test_format_activities.py` | Import regressions for binary XML render bindings and the native wrapped JSON setting. |
| `frontend/scripts/xml-json-contract.test.mjs` | Actual Studio schema-tree/control/path contract tests with XML DOM traversal support. |
| `docs/PARSE_RENDER_ACTIVITIES.md` | Updated user guidance for conversion, mapping, nil values, namespace ordering and encoding. |
| `docs/XML_JSON_VERIFICATION_2026-11-17.md` | Verification scope, results, reproduction and limitations. |
| `docs/XML_JSON_CHANGED_FILES_2026-11-17.md` | This manifest. |
| `docs/validation/xml-json-summary-2026-11-17.json` | Final focused-suite, broader-suite, frontend/build results and reference sources. |
| `docs/validation/xml-json-live-comparison-2026-11-17.json` | Installed runtime output, fixture validation, browser checks and archive comparisons from the follow-up. |
| `docs/validation/xml-json-extended-comparison-2026-11-17.json` | Native ASCII XML and wrapped JSON outputs, EAR validation, and comparison results from all four MINA execution modes. |
| `frontend/scripts/developer-documentation.mjs` | Add the regression sources to Studio's developer source map. |
| `frontend/public/help/documentation-data.json` | Regenerated offline user-help model. |
| `frontend/public/help/documentation-data.js` | Regenerated browser help payload. |
| `frontend/public/help/developer-data.json` | Refreshed developer references. |
| `frontend/public/help/documentation-build.json` | Generated-file fingerprints and checksums. |
| `frontend/public/help/MINA-Documentation.pdf` | Regenerated user reference. |
| `frontend/public/help/MINA-Developer-Guide.pdf` | Regenerated developer reference. |
| `frontend/dist/index.html` | Generated entry referencing the locally rebuilt JavaScript bundle. |

The generated `dist` entry requires its generated bundle assets; rebuild the frontend in another workspace using `npm.cmd ci --include=dev` and `npm.cmd run build`. Rebuild/restart Studio or the backend and refresh the web UI, and re-export Python archives to carry the updated shared conversion code. No installer or release was published.
