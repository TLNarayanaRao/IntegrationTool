# Activity resource verification: changed files

Full backend verification passed: **609 tests, five skipped, zero failures**. The final focused resource/messaging/export run passed **65 tests** after the last publisher changes. Studio frontend tests passed **150/150**, Help checks **11/11**, and the production Studio build passed. The build retains its existing large-chunk advisory.

The local soak passed **600.12 measured seconds after 30 seconds of warmup**, eight workers and zero operation errors. RSS growth was **0.64 MiB**, traced Python heap growth **0.26 MiB**, peak sampled RSS **76.07 MiB**, and late RSS slope **0.004 MiB/minute**. Active handles ranged from 453 to 484 and ended at 458; active threads ranged from 33 to 38 and ended at 35. After worker shutdown they fell to 407 handles and 16 threads.

Workload cycle counts include warmup: formats 19,839; Mapper/DataWeave 527,647; Python 6,275; Excel 416. A format cycle executes all six parse/render operations; other cycles execute both implementations or transformations described in the guide. No explicit garbage collection was forced.

This is local resource verification, not live qualification of every external broker/cloud/database/SAP provider, arbitrary user code, or an interactive installed-app session. See the coverage guide for limitations.

The list below is limited to this request; earlier uncommitted work is preserved.

| File | Change |
| --- | --- |
| [backend/app/amqp.py](../backend/app/amqp.py) | AMQP receive, settlement, connection-test and Azure identity ownership. |
| [backend/app/google_pubsub.py](../backend/app/google_pubsub.py) | Close token-refresh HTTP sessions on success and failure. |
| [backend/app/raw_python_support/activities.py](../backend/app/raw_python_support/activities.py) | Close Excel workbooks and fix default header/start-row calculation. |
| [backend/app/raw_python_support/connectors.py](../backend/app/raw_python_support/connectors.py) | Bound Direct publisher caches/locks, clean up failed startup and close subscribers. |
| [backend/app/runtime.py](../backend/app/runtime.py) | Bound transaction locks, finish independent publisher cleanup and reap timed-out Java children. |
| [backend/tests/test_field_conditions.py](../backend/tests/test_field_conditions.py) | Use the same app import namespace as the backend test runner. |
| [backend/tests/test_input_loop_tree.py](../backend/tests/test_input_loop_tree.py) | Use the same app import namespace as the backend test runner. |
| [backend/tests/test_mapper_loop_names.py](../backend/tests/test_mapper_loop_names.py) | Use the same app import namespace as the backend test runner. |
| [backend/tests/test_remaining_activity_resources.py](../backend/tests/test_remaining_activity_resources.py) | 13 failure, capacity and Run/Debug/archive resource regressions. |
| [backend/tests/test_tasks_runtime.py](../backend/tests/test_tasks_runtime.py) | Require legal/SBOM assets while preserving executable-source archive assertions. |
| [docs/REMAINING_ACTIVITY_CHANGED_FILES.md](../docs/REMAINING_ACTIVITY_CHANGED_FILES.md) | This changed-file and validation report. |
| [docs/REMAINING_ACTIVITY_RESOURCE_VERIFICATION.md](../docs/REMAINING_ACTIVITY_RESOURCE_VERIFICATION.md) | Coverage matrix, reproducible checks and explicit qualification limits. |
| [docs/validation/remaining-activities-soak-2026-11-14.json](../docs/validation/remaining-activities-soak-2026-11-14.json) | Measured soak data or verification summary with source hashes. |
| [docs/validation/remaining-activities-verification-2026-11-14.json](../docs/validation/remaining-activities-verification-2026-11-14.json) | Measured soak data or verification summary with source hashes. |
| [frontend/public/help/MINA-Developer-Guide.pdf](../frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated offline reference, index or PDF with current resource guidance. |
| [frontend/public/help/MINA-Documentation.pdf](../frontend/public/help/MINA-Documentation.pdf) | Regenerated offline reference, index or PDF with current resource guidance. |
| [frontend/public/help/developer-data.json](../frontend/public/help/developer-data.json) | Regenerated offline reference, index or PDF with current resource guidance. |
| [frontend/public/help/documentation-build.json](../frontend/public/help/documentation-build.json) | Regenerated offline reference, index or PDF with current resource guidance. |
| [frontend/public/help/documentation-data.js](../frontend/public/help/documentation-data.js) | Regenerated offline reference, index or PDF with current resource guidance. |
| [frontend/public/help/documentation-data.json](../frontend/public/help/documentation-data.json) | Regenerated offline reference, index or PDF with current resource guidance. |
| [frontend/scripts/build-documentation.mjs](../frontend/scripts/build-documentation.mjs) | Include the resource verification guide in offline Help. |
| [frontend/scripts/developer-documentation.mjs](../frontend/scripts/developer-documentation.mjs) | Index the resource test and soak implementation. |
| [scripts/activity-resource-soak.py](../scripts/activity-resource-soak.py) | Repeatable eight-worker local resource soak with gates and JSON measurements. |
