# Sender performance changed files

Existing unrelated edits were preserved. No runtime dependencies or delivery defaults changed. Test brokers, profiles and raw logs remain in ignored tmp/.

- [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) — Preserve explicit Pub/Sub delay zero when applying activity/shared-connection settings.
- [backend/app/google_pubsub.py](D:/Integration-tool/IntegrationFabric/backend/app/google_pubsub.py) — Apply the preserved delay using the existing 1 ms minimum in SDK BatchSettings.
- [backend/app/raw_python_support/connectors.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python_support/connectors.py) — Apply the same zero-delay override in generated Direct Python.
- [backend/tests/test_sender_settings.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_sender_settings.py) — Regression checks for runtime, real SDK BatchSettings and the actual pruned exported adapter.
- [scripts/activity-throughput.py](D:/Integration-tool/IntegrationFabric/scripts/activity-throughput.py) — Compare per-send Kafka confirmation with final-flush buffered sending; record the mode and emit bounded soak progress.
- [docs/SENDER_PERFORMANCE.md](D:/Integration-tool/IntegrationFabric/docs/SENDER_PERFORMANCE.md) — Sender diagnostics, safe tuning, test methodology and qualification limits.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) — Include the sender guide in Studio help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) — Include the new test source in help fingerprints.
- [frontend/public/help/developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) — Regenerated Studio help/manual artifact.
- [frontend/public/help/documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) — Regenerated Studio help/manual artifact.
- [frontend/public/help/documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) — Regenerated Studio help/manual artifact.
- [frontend/public/help/documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) — Regenerated Studio help/manual artifact.
- [frontend/public/help/MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) — Regenerated Studio help/manual artifact.
- [frontend/public/help/MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) — Regenerated Studio help/manual artifact.
- [docs/validation/sender-jms-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-jms-2026-11-16.json) — Measured sender or soak result.
- [docs/validation/sender-kafka-buffered-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-kafka-buffered-2026-11-16.json) — Measured sender or soak result.
- [docs/validation/sender-kafka-parallel-confirmed-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-kafka-parallel-confirmed-2026-11-16.json) — Measured sender or soak result.
- [docs/validation/sender-kafka-serial-confirmed-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-kafka-serial-confirmed-2026-11-16.json) — Measured sender or soak result.
- [docs/validation/sender-kafka-soak-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-kafka-soak-2026-11-16.json) — Measured sender or soak result.

- [docs/validation/sender-jms-soak-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-jms-soak-2026-11-16.json) — Final verified sender/soak evidence and scope.

- [docs/validation/sender-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/sender-summary-2026-11-16.json) — Final verified sender/soak evidence and scope.

- [Changed-file index](D:/Integration-tool/IntegrationFabric/docs/SENDER_PERFORMANCE_CHANGED_FILES.md) — This request-specific list.
