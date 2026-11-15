# Changed files for throughput verification

This list compares with the pre-request snapshot. Existing unrelated workspace edits were preserved. Test brokers, private profiles, temporary clients and logs remain under ignored `tmp/`. No runtime dependency versions changed.

- [backend/app/google_pubsub.py](D:/Integration-tool/IntegrationFabric/backend/app/google_pubsub.py) — Resolve project routing without rebuilding private-key credentials on cached sends.
- [backend/app/java_bridge.py](D:/Integration-tool/IntegrationFabric/backend/app/java_bridge.py) — Bounded batch Get options and event-driven listener wakeup.
- [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) — Kafka/PubSub receive responsiveness and cleanup; Pub/Sub Pull dispatch, credential reuse, JMS batch propagation.
- [backend/app/raw_python_support/connectors.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python_support/connectors.py) — Generated adapter credential reuse, JMS batch results and explicit Kafka publish partition.
- [scripts/live-messaging-soak.py](D:/Integration-tool/IntegrationFabric/scripts/live-messaging-soak.py) — Pin the Kafka fixture producer to the same partition as its receiver.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) — Include the throughput guide in Studio help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) — Index the benchmark and regression test sources.
- [frontend/scripts/field-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/field-documentation.mjs) — Explain batch limits and timeout semantics.
- [frontend/public/help/developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) — Regenerated bundled help/manual artifact.
- [frontend/public/help/documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) — Regenerated bundled help/manual artifact.
- [frontend/public/help/documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) — Regenerated bundled help/manual artifact.
- [frontend/public/help/documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) — Regenerated bundled help/manual artifact.
- [frontend/public/help/MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) — Regenerated bundled help/manual artifact.
- [frontend/public/help/MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) — Regenerated bundled help/manual artifact.
- [frontend/src/ActivityEditor.tsx](D:/Integration-tool/IntegrationFabric/frontend/src/ActivityEditor.tsx) — Expose maximum messages for EMS/JMS Get.
- [java-bridge/src/com/mina/bridge/MinaJavaBridge.java](D:/Integration-tool/IntegrationFabric/java-bridge/src/com/mina/bridge/MinaJavaBridge.java) — Receive bounded batches under one total timeout and retain each message metadata.
- [frontend/dist/index.html](D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) — Rebuilt Studio entry point.
- [scripts/activity-throughput.py](D:/Integration-tool/IntegrationFabric/scripts/activity-throughput.py) — Dedicated-resource throughput and paced-soak runner with exact payload checks.
- [backend/tests/test_messaging_throughput.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_messaging_throughput.py) — Offline behavioral regression tests; not a cloud throughput claim.
- [docs/MESSAGING_THROUGHPUT.md](D:/Integration-tool/IntegrationFabric/docs/MESSAGING_THROUGHPUT.md) — Workload, results, limitations and QA reproduction instructions.
- [docs/validation/throughput-jms-100k-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-jms-100k-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-jms-baseline-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-jms-baseline-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-jms-batch-interpolation-fixture-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-jms-batch-interpolation-fixture-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-jms-batch-modes-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-jms-batch-modes-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-kafka-100k-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-kafka-100k-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-kafka-baseline-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-kafka-baseline-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-kafka-soak-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-kafka-soak-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-mapper-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-mapper-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-modes-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-modes-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-modes-multipartition-fixture-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-modes-multipartition-fixture-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.
- [docs/validation/throughput-modes-partition-routing-2026-11-15.json](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-modes-partition-routing-2026-11-15.json) — Measured result or retained failed diagnostic run; see the guide for qualification scope.

- [Final qualification summary](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-summary-2026-11-15.json) � Measured rates, checks and outstanding live-provider qualification.
- [JMS soak result](D:/Integration-tool/IntegrationFabric/docs/validation/throughput-jms-soak-2026-11-15.json) � Complete 10-minute sustained local JMS result.
- [This changed-file index](D:/Integration-tool/IntegrationFabric/docs/MESSAGING_THROUGHPUT_CHANGED_FILES.md) � Request-specific file list.
