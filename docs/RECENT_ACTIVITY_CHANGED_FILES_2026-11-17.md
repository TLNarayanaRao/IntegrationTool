# Changed files — recent activity regression verification

All paths below are relative to the repository root. Temporary brokers, private test profiles, generated test archives and logs remain under ignored `tmp/` and are not runtime dependencies.

| File | Change |
|---|---|
| `backend/app/runtime.py` | Align JMS/EMS credential and JNDI validation with provider defaults and archive behavior. |
| `java-bridge/src/com/mina/bridge/MinaJavaBridge.java` | Use the no-argument provider connection method when both credentials are empty; preserve explicit credentials. |
| `frontend/src/main.tsx` | Match JMS/EMS shared-connection form requiredness and explanatory help to the runtime. |
| `backend/tests/test_jms_connection_auth.py` | Runtime credential/JNDI regressions and compilation/execution of actual Java bridge tests. |
| `java-bridge/test/com/mina/bridge/MinaJavaBridgeAuthenticationTest.java` | Cover provider defaults and unchanged explicit credential combinations through the real bridge entry point. |
| `frontend/scripts/jms-connection-contract.test.mjs` | Test actual Studio field definitions for credentials and conditional Direct/JNDI requirements. |
| `docs/JMS_BATCH_REUSE.md` | Document authentication semantics and matching bridge rebuild/restart requirements. |
| `docs/RECENT_ACTIVITY_REGRESSION_2026-11-17.md` | Workloads, results, reproduction and qualification boundaries. |
| `docs/RECENT_ACTIVITY_CHANGED_FILES_2026-11-17.md` | This complete change manifest. |
| `docs/validation/recent-activities-summary-2026-11-17.json` | Sanitized flow results, suite/build counts and explicit limitations. |
| `frontend/scripts/build-documentation.mjs` | Include the regression guide and correct shared-connection authentication documentation. |
| `frontend/scripts/developer-documentation.mjs` | Index the new regression sources in the developer source map. |
| `frontend/public/help/documentation-data.json` | Regenerated offline user-help model. |
| `frontend/public/help/documentation-data.js` | Regenerated browser help payload. |
| `frontend/public/help/developer-data.json` | Regenerated developer source references. |
| `frontend/public/help/documentation-build.json` | Refreshed fingerprints and generated-file checksums. |
| `frontend/public/help/MINA-Documentation.pdf` | Regenerated user reference. |
| `frontend/public/help/MINA-Developer-Guide.pdf` | Regenerated developer reference. |
| `frontend/dist/index.html` | Generated build entry referencing the locally rebuilt JavaScript bundle. |

The generated `frontend/dist` entry is not a standalone deployment artifact: its bundle assets are generated/ignored. Run `npm.cmd ci --include=dev` and `npm.cmd run build` in `frontend` in another workspace, and use the normal Studio/sidecar build for the Java bridge. Rebuild and restart existing Studio installations to load the updated bridge and UI. This verification did not rebuild an installer or publish a release.
