# JMS optimization changed files

Changes for this request only. Existing unrelated workspace edits were preserved. No new runtime dependencies were added. Private profiles, brokers and raw diagnostics remain in ignored tmp/.

- [backend/app/java_bridge.py](D:/Integration-tool/IntegrationFabric/backend/app/java_bridge.py) — Bounded, scope/destination/filter-isolated batch-Get workers; separate sender/receiver capacity; explicit-client-ID compatibility.
- [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) — Include receive-only applications in application/shutdown worker cleanup.
- [java-bridge/src/com/mina/bridge/MinaJavaBridge.java](D:/Integration-tool/IntegrationFabric/java-bridge/src/com/mina/bridge/MinaJavaBridge.java) — Reusable receive RPC with a consumer closed after every Get; reuse the original destination in the one-shot path.
- [backend/tests/fixtures/FakeJmsFactory.java](D:/Integration-tool/IntegrationFabric/backend/tests/fixtures/FakeJmsFactory.java) — Native consumer/selector/close instrumentation for real Java bridge contract tests.
- [backend/tests/test_jms_sender_worker.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_jms_sender_worker.py) — Verify receive reuse, consumer closure, selector isolation and no replay/error impact on senders.
- [backend/tests/test_messaging_throughput.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_messaging_throughput.py) — Verify batch routing, bounds and legacy explicit-client-ID ownership.
- [backend/tests/test_jms_soak_gate.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_jms_soak_gate.py) — Deadline-count, receive-only cleanup, independent receive and sender-capacity safeguards.
- [scripts/activity-throughput.py](D:/Integration-tool/IntegrationFabric/scripts/activity-throughput.py) — Enforce minimum verified records inside the soak window and report the threshold time.
- [docs/JMS_BATCH_REUSE.md](D:/Integration-tool/IntegrationFabric/docs/JMS_BATCH_REUSE.md) — Implementation, measured results, deployment prerequisites, reproducibility and provider limits.
- [docs/SENDER_PERFORMANCE.md](D:/Integration-tool/IntegrationFabric/docs/SENDER_PERFORMANCE.md) — Link earlier results to the strict follow-up qualification.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) — Include the new guide in Studio help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) — Fingerprint the new regression test source.
- [frontend/public/help/documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) — Regenerated help/manual artifact.
- [frontend/public/help/documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) — Regenerated help/manual artifact.
- [frontend/public/help/developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) — Regenerated help/manual artifact.
- [frontend/public/help/documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) — Regenerated help/manual artifact.
- [frontend/public/help/MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) — Regenerated help/manual artifact.
- [frontend/public/help/MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) — Regenerated help/manual artifact.
- [docs/validation/jms-optimized-flow-debug-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-flow-debug-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-flow-python-direct-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-flow-python-direct-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-flow-python-engine-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-flow-python-engine-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-flow-run-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-flow-run-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-flow-run-before-queue-isolation-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-flow-run-before-queue-isolation-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-flow-run-broker-stopped-fixture-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-flow-run-broker-stopped-fixture-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-soak-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-soak-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [docs/validation/jms-optimized-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/jms-optimized-summary-2026-11-16.json) — Final measured qualification or retained initial/fixture evidence; use the summary for acceptance.
- [This file index](D:/Integration-tool/IntegrationFabric/docs/JMS_BATCH_REUSE_CHANGED_FILES.md) — Request-specific list.
