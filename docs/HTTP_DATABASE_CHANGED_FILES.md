# HTTP/database resource task: changed files

This report compares against the start of this task. Prior unrelated workspace changes were preserved.

| Change | File | Purpose |
| --- | --- | --- |
| Modified | [backend/app/http1_protocol.py](../backend/app/http1_protocol.py) | Release closed protocol wrappers and cancel keepalive timers on all disconnects. |
| Modified | [backend/app/http_server.py](../backend/app/http_server.py) | Shut down worker pools on listener configuration and warm-up failures. |
| Modified | [backend/app/http_transport.py](../backend/app/http_transport.py) | Release idle route gates and clean all scoped clients/tokens despite close failures. |
| Modified | [backend/app/jdbc.py](../backend/app/jdbc.py) | Close owned metadata cursors explicitly. |
| Modified | [backend/app/raw_python.py](../backend/app/raw_python.py) | Include Snowflake JDBC helper and mode/profile-aware database dependency checks. |
| Modified | [backend/app/schema_validation.py](../backend/app/schema_validation.py) | Reuse bounded draft validator types with fresh schema instances and isolated per-call budgets. |
| Modified | [backend/app/snowflake.py](../backend/app/snowflake.py) | Close cursors and remove owned generated CSV files on every exit path. |
| Added | [backend/tests/test_http_database_resources.py](../backend/tests/test_http_database_resources.py) | Cleanup, concurrency, startup, file ownership and archive regressions. |
| Modified | [docs/FILE_TRANSFER_DATABASE_READINESS.md](../docs/FILE_TRANSFER_DATABASE_READINESS.md) | Document database cursor/file ownership and follow-up checks. |
| Added | [docs/HTTP_DATABASE_MEMORY_VERIFICATION.md](../docs/HTTP_DATABASE_MEMORY_VERIFICATION.md) | Recorded results, native probes, test scope and remaining live qualifications. |
| Modified | [docs/HTTP_REST_CAPABILITIES.md](../docs/HTTP_REST_CAPABILITIES.md) | Document route/client/listener lifecycle and per-request memory limits. |
| Modified | [docs/PYTHON_EXPORT.md](../docs/PYTHON_EXPORT.md) | Document native/Java JDBC prerequisites and archive closure behavior. |
| Added | [docs/validation/http-database-first-pass-2026-11-13.json](../docs/validation/http-database-first-pass-2026-11-13.json) | Preserve the first-pass client measurements and listener GC-pressure baseline. |
| Added | [docs/validation/http-database-memory-2026-11-13.json](../docs/validation/http-database-memory-2026-11-13.json) | Machine-readable metrics, source fingerprints and validation results. |
| Modified | [frontend/public/help/MINA-Developer-Guide.pdf](../frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/MINA-Documentation.pdf](../frontend/public/help/MINA-Documentation.pdf) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/developer-data.json](../frontend/public/help/developer-data.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-build.json](../frontend/public/help/documentation-build.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-data.js](../frontend/public/help/documentation-data.js) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-data.json](../frontend/public/help/documentation-data.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/scripts/build-documentation.mjs](../frontend/scripts/build-documentation.mjs) | Include the new verification guide in Studio Help. |
| Modified | [frontend/scripts/developer-documentation.mjs](../frontend/scripts/developer-documentation.mjs) | Index the new workload and resource regressions. |
| Added | [scripts/http-database-soak.py](../scripts/http-database-soak.py) | Repeatable 20-worker real HTTP/HTTPS/REST and database sustained resource checks. |

This report, `docs/HTTP_DATABASE_CHANGED_FILES.md`, was also added. No runtime dependency versions were changed. See [the verification report](HTTP_DATABASE_MEMORY_VERIFICATION.md) for coverage and qualification limits.
