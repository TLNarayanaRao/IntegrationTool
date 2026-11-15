# Connector soak task: changed files

Only changes made during this task are listed. Existing unrelated workspace changes were preserved.

| Change | File | Purpose |
| --- | --- | --- |
| Modified | [backend/app/ai_builder.py](../backend/app/ai_builder.py) | Generate ordinary API receiver methods without CONNECT. |
| Modified | [backend/app/http_server.py](../backend/app/http_server.py) | Report unsupported listener methods explicitly. |
| Modified | [backend/app/jdbc.py](../backend/app/jdbc.py) | Serialize use and closure of shared native transaction sessions. |
| Modified | [backend/tests/test_activity_packs.py](../backend/tests/test_activity_packs.py) | Verify supported ordinary listener methods. |
| Modified | [backend/tests/test_mysql_live.py](../backend/tests/test_mysql_live.py) | Live shared-session concurrency and failed-session socket/GC regressions. |
| Added | [backend/tests/test_soak_regressions.py](../backend/tests/test_soak_regressions.py) | GC, concurrency and generated listener-method regressions. |
| Modified | [backend/tests/test_transfer_network.py](../backend/tests/test_transfer_network.py) | Isolate FTP event loops and bound fixture transport retention. |
| Added | [docs/CONNECTOR_SOAK_RESULTS.md](../docs/CONNECTOR_SOAK_RESULTS.md) | Record completed workload results and unresolved native-memory failure. |
| Modified | [docs/FILE_TRANSFER_DATABASE_READINESS.md](../docs/FILE_TRANSFER_DATABASE_READINESS.md) | Document shared-session behavior and resource qualification. |
| Added | [docs/validation/connector-soak-2026-11-13.json](../docs/validation/connector-soak-2026-11-13.json) | Portable machine-readable measurements and dependency controls. |
| Modified | [frontend/dist/index.html](../frontend/dist/index.html) | Regenerated frontend production build; hashed assets are replaced together. |
| Modified | [frontend/public/help/MINA-Developer-Guide.pdf](../frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/MINA-Documentation.pdf](../frontend/public/help/MINA-Documentation.pdf) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/developer-data.json](../frontend/public/help/developer-data.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-build.json](../frontend/public/help/documentation-build.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-data.js](../frontend/public/help/documentation-data.js) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-data.json](../frontend/public/help/documentation-data.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/scripts/build-documentation.mjs](../frontend/scripts/build-documentation.mjs) | Include the verification report in Studio Help. |
| Modified | [frontend/scripts/developer-documentation.mjs](../frontend/scripts/developer-documentation.mjs) | Index the qualification tools, session lock and regression tests. |
| Modified | [frontend/src/ActivityEditor.tsx](../frontend/src/ActivityEditor.tsx) | Warn about and repair legacy unsupported HTTP method selections. |
| Modified | [frontend/tests/connector-production.test.mjs](../frontend/tests/connector-production.test.mjs) | Verify the method repair retains supported selections. |
| Added | [scripts/connector-native-memory.py](../scripts/connector-native-memory.py) | Network-free native cryptography thread-memory controls. |
| Added | [scripts/connector-soak.py](../scripts/connector-soak.py) | Reusable 22-worker sustained workload and memory/resource gates. |

This file, `docs/CONNECTOR_SOAK_CHANGED_FILES.md`, was also added as the task-specific change report.

The production build regenerated its hashed bundle and index. Generated asset files follow the repository ignore rules. No source files were deleted.

Validation: 245 main backend tests; 25 additional tests passed with one live PostgreSQL skip; 10 GC rechecks; 150 frontend tests; 11 Help tests; production frontend build passed. The 30-minute soak completed 211,389 measured operations without an operation error but failed the native-memory slope gate. See the recorded results before release.
