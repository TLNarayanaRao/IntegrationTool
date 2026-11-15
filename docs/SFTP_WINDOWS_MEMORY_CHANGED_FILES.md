# Windows SFTP memory fix: changed files

This list compares file contents with the start of this task; prior unrelated workspace changes were preserved.

| Change | File | Purpose |
| --- | --- | --- |
| Modified | [backend/app/sftp.py](../backend/app/sftp.py) | Bound Windows SSH transport execution to lazy persistent workers; preserve fresh sessions, trust and timeouts. |
| Added | [backend/tests/test_sftp_transport_workers.py](../backend/tests/test_sftp_transport_workers.py) | Capacity, failure recovery, GC, key authentication, multi-server streaming and archive regressions. |
| Modified | [backend/tests/test_transfer_network.py](../backend/tests/test_transfer_network.py) | Allow a disposable public-key-authenticated test server. |
| Modified | [docs/CONNECTOR_SOAK_RESULTS.md](../docs/CONNECTOR_SOAK_RESULTS.md) | Mark the prior failed measurements as the pre-fix baseline and link the follow-up. |
| Modified | [docs/ENVIRONMENT_VARIABLES.md](../docs/ENVIRONMENT_VARIABLES.md) | Document the Windows transport limit and timeout behavior. |
| Modified | [docs/FILE_TRANSFER_DATABASE_READINESS.md](../docs/FILE_TRANSFER_DATABASE_READINESS.md) | Document bounded workers, preserved security and managed native-memory checks. |
| Added | [docs/SFTP_WINDOWS_MEMORY_FIX.md](../docs/SFTP_WINDOWS_MEMORY_FIX.md) | Record the fix, completed soak, controls, functional checks and scope. |
| Added | [docs/validation/sftp-windows-memory-fixed-2026-11-13.json](../docs/validation/sftp-windows-memory-fixed-2026-11-13.json) | Machine-readable environment fingerprints, samples, controls and results. |
| Modified | [frontend/public/help/MINA-Developer-Guide.pdf](../frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/MINA-Documentation.pdf](../frontend/public/help/MINA-Documentation.pdf) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/developer-data.json](../frontend/public/help/developer-data.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-build.json](../frontend/public/help/documentation-build.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-data.js](../frontend/public/help/documentation-data.js) | Regenerated Studio Help/manual content. |
| Modified | [frontend/public/help/documentation-data.json](../frontend/public/help/documentation-data.json) | Regenerated Studio Help/manual content. |
| Modified | [frontend/scripts/build-documentation.mjs](../frontend/scripts/build-documentation.mjs) | Include the follow-up guide and SFTP activity operational notes in Help. |
| Modified | [frontend/scripts/developer-documentation.mjs](../frontend/scripts/developer-documentation.mjs) | Index the bounded transport implementation and regression tests. |
| Modified | [scripts/connector-native-memory.py](../scripts/connector-native-memory.py) | Gate the bounded worker path while preserving the raw native failure control. |

This file, `docs/SFTP_WINDOWS_MEMORY_CHANGED_FILES.md`, was also added as the task-specific change report.

No runtime dependency versions were changed. The reusable connector soak workload and gates were unchanged. See [the detailed results](SFTP_WINDOWS_MEMORY_FIX.md) for qualification scope and the retained upstream native control.
