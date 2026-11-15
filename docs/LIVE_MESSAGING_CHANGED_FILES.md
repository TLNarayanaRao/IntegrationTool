# Live messaging: results and changed files

Available local live profiles passed for Kafka 3.9.1, Artemis 2.40.0 JMS and AMQP 1.0. **The requested five-service qualification is incomplete:** cloud Pub/Sub, vendor EMS and SAP still need approved QA connections, dedicated destinations and permitted vendor libraries. An Artemis JMS pass is not an EMS pass.

| Mode | Measured duration | Kafka / JMS / AMQP round trips, including warmup | Result |
| --- | --- | --- | --- |
| run | 1801.55 seconds | 3,688 / 1,693 / 3,692 | Passed continuity, operation and resource gates |
| debug | 600.80 seconds | 654 / 151 / 654 | Passed continuity, operation and resource gates |
| python-direct | 900.92 seconds | 953 / 496 / 954 | Passed continuity, operation and resource gates |
| python-engine | 900.97 seconds | 950 / 494 / 951 | Passed continuity, operation and resource gates |

All six final archive workers measured their actual interpreter rather than the Windows venv launcher and exited cleanly. Source Run RSS growth was -0.82 MiB; Debug growth was 1.95 MiB. Final per-archive-worker RSS growth was at most 0.46 MiB, with late slopes below 0.012 MiB/minute. No explicit garbage collection was forced. These results apply to the declared bounded load and measurement windows.

Validation also passed: 623 full backend tests with five environment skips; 87 final focused tests; four harness checks; four additional real AMQP/JMS protocol cases; 150 frontend tests; 11 Help checks; and the production Studio build. The existing large-chunk build advisory remains. No fresh installer or interactive installed-app soak was performed.

Earlier failures are retained. The unpaced high-rate AMQP failure and an early Direct startup failure remain unexplained. A later Windows Kafka retention rename failure was isolated in the temporary broker and avoided only by using fresh test storage and a retention window longer than the experiment. Production retention/failover is not qualified. Host-interrupted attempts and launcher-only resource measurements are explicitly failed or invalidated, not counted as passes.

See [coverage and reproduction](LIVE_MESSAGING_VERIFICATION.md) and [machine-readable qualification summary](validation/live-messaging-summary-2026-11-15.json). Temporary broker processes were stopped. Downloaded binaries, test-only dependencies, private configurations and diagnostics remain in ignored temporary storage and are not included in this change list.

This list is limited to this request; earlier uncommitted work is preserved.

| File | Change |
| --- | --- |
| [backend/app/amqp.py](../backend/app/amqp.py) | Correct Proton TTL units/defaults, receive signature, automatic/manual settlement and fault propagation. |
| [backend/app/google_pubsub.py](../backend/app/google_pubsub.py) | Preserve Google credential constructor/copy behavior, bound wrapper classes and release failed TLS transports; SDK-only verification. |
| [backend/app/java_bridge.py](../backend/app/java_bridge.py) | Report the configured timeout budget after interruptions and reap forcibly killed scoped JVMs. |
| [backend/app/raw_python.py](../backend/app/raw_python.py) | Normalize Kafka Send/Get and Pub/Sub Subscribe aliases before export code selection. |
| [backend/app/raw_python_support/connectors.py](../backend/app/raw_python_support/connectors.py) | Apply Direct Kafka initial-offset/partition/seek options and protect consumer startup cleanup. |
| [backend/app/runtime.py](../backend/app/runtime.py) | Remove producer-only request-timeout settings from Kafka consumers to prevent warning churn. |
| [backend/tests/test_live_messaging_regressions.py](../backend/tests/test_live_messaging_regressions.py) | Installed-SDK, export-alias, credential-copy, transport and Java timeout/cleanup regressions. |
| [backend/tests/test_live_messaging_services.py](../backend/tests/test_live_messaging_services.py) | Opt-in real AMQP expiry/header/settlement and JMS request/reply cases with dedicated resources. |
| [backend/tests/test_live_soak_harness.py](../backend/tests/test_live_soak_harness.py) | Bounded measurement, interrupted-window, awake-state restoration and interpreter-PID tests. |
| [docs/LIVE_MESSAGING_CHANGED_FILES.md](../docs/LIVE_MESSAGING_CHANGED_FILES.md) | This result and changed-file report. |
| [docs/LIVE_MESSAGING_VERIFICATION.md](../docs/LIVE_MESSAGING_VERIFICATION.md) | Exact coverage, failures, limits, protected QA configuration and reproducible commands. |
| [docs/validation/kafka-windows-storage-failure-2026-11-14.txt](../docs/validation/kafka-windows-storage-failure-2026-11-14.txt) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-2026-11-14.json](../docs/validation/live-messaging-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-2026-11-15.json](../docs/validation/live-messaging-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-direct-2026-11-14.json](../docs/validation/live-messaging-archive-direct-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-direct-2026-11-15.json](../docs/validation/live-messaging-archive-direct-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-direct-first-pass-2026-11-14.json](../docs/validation/live-messaging-archive-direct-first-pass-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-direct-launcher-measurement-2026-11-15.json](../docs/validation/live-messaging-archive-direct-launcher-measurement-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-direct-second-pass-2026-11-14.json](../docs/validation/live-messaging-archive-direct-second-pass-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-engine-2026-11-14.json](../docs/validation/live-messaging-archive-engine-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-engine-2026-11-15.json](../docs/validation/live-messaging-archive-engine-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-engine-first-pass-2026-11-14.json](../docs/validation/live-messaging-archive-engine-first-pass-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-archive-engine-launcher-measurement-2026-11-15.json](../docs/validation/live-messaging-archive-engine-launcher-measurement-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-broker-failure-2026-11-14.json](../docs/validation/live-messaging-broker-failure-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-debug-2026-11-14.json](../docs/validation/live-messaging-debug-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-debug-2026-11-15.json](../docs/validation/live-messaging-debug-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-edge-cases-2026-11-15.json](../docs/validation/live-messaging-edge-cases-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-first-pass-2026-11-14.json](../docs/validation/live-messaging-first-pass-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-modes-2026-11-14.json](../docs/validation/live-messaging-modes-2026-11-14.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [docs/validation/live-messaging-summary-2026-11-15.json](../docs/validation/live-messaging-summary-2026-11-15.json) | Credential-free measured result, failure/invalidated evidence or qualification summary. |
| [frontend/public/help/MINA-Developer-Guide.pdf](../frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated offline Help data, build metadata or PDF with current guidance. |
| [frontend/public/help/MINA-Documentation.pdf](../frontend/public/help/MINA-Documentation.pdf) | Regenerated offline Help data, build metadata or PDF with current guidance. |
| [frontend/public/help/developer-data.json](../frontend/public/help/developer-data.json) | Regenerated offline Help data, build metadata or PDF with current guidance. |
| [frontend/public/help/documentation-build.json](../frontend/public/help/documentation-build.json) | Regenerated offline Help data, build metadata or PDF with current guidance. |
| [frontend/public/help/documentation-data.js](../frontend/public/help/documentation-data.js) | Regenerated offline Help data, build metadata or PDF with current guidance. |
| [frontend/public/help/documentation-data.json](../frontend/public/help/documentation-data.json) | Regenerated offline Help data, build metadata or PDF with current guidance. |
| [frontend/scripts/build-documentation.mjs](../frontend/scripts/build-documentation.mjs) | Include live messaging qualification in Studio Help/PDF guides. |
| [frontend/scripts/developer-documentation.mjs](../frontend/scripts/developer-documentation.mjs) | Index live qualification implementations, lifecycle and measurement tests. |
| [frontend/scripts/field-documentation.mjs](../frontend/scripts/field-documentation.mjs) | Clarify AMQP expiration milliseconds. |
| [scripts/live-messaging-archive-soak.py](../scripts/live-messaging-archive-soak.py) | Sustained generated ZIP workers with actual-interpreter metrics and clean shutdown verification. |
| [scripts/live-messaging-debug-soak.py](../scripts/live-messaging-debug-soak.py) | Repeated real Debug sessions with the same scoped native teardown as Studio Stop. |
| [scripts/live-messaging-soak.py](../scripts/live-messaging-soak.py) | Live round trips, declared load, bounded timing storage, interruption/resource gates and temporary awake requests. |
| [scripts/live-messaging-verify.py](../scripts/live-messaging-verify.py) | Actual Run/Debug and both generated CLI applications against fresh destinations. |
| [scripts/sap-production-soak.py](../scripts/sap-production-soak.py) | Bound SAP latency/error retention while preserving full-run counters and aggregate statistics; no live SAP result. |
