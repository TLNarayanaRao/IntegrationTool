# Actual Kafka qualification changed files

Changes for this request only; earlier EMS/JMS and Pub/Sub edits are preserved.
No runtime dependencies or application behavior were changed for this qualification.

- [scripts/kafka-local-qa.py](D:/Integration-tool/IntegrationFabric/scripts/kafka-local-qa.py): provision a fresh actual loopback Kafka broker, unique topics and four complete-flow workloads; stop only the owned broker and retain diagnostics locally.
- [docs/KAFKA_ACTUAL_THROUGHPUT.md](D:/Integration-tool/IntegrationFabric/docs/KAFKA_ACTUAL_THROUGHPUT.md): workload, results, reproduction steps and qualification limits.
- [docs/validation/kafka-actual-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/kafka-actual-summary-2026-11-16.json): aggregate results and cleanup status.
- [Run report](D:/Integration-tool/IntegrationFabric/docs/validation/kafka-actual-flow-run-2026-11-16.json): complete-flow measurement.
- [Debug report](D:/Integration-tool/IntegrationFabric/docs/validation/kafka-actual-flow-debug-2026-11-16.json): complete-flow measurement.
- [Direct archive report](D:/Integration-tool/IntegrationFabric/docs/validation/kafka-actual-flow-python-direct-2026-11-16.json): generated direct Python application measurement.
- [Engine archive report](D:/Integration-tool/IntegrationFabric/docs/validation/kafka-actual-flow-python-engine-2026-11-16.json): generated engine Python application measurement.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs): include the qualification guide in Studio Help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs): include the launcher in documentation source fingerprints.
- [documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) and [documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js): generated Studio Help content.
- [developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json): generated developer help.
- [documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json): updated documentation fingerprints.
- [MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) and [MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf): regenerated manuals.

Downloaded Kafka binaries, fresh broker storage, generated archives, private profiles
and diagnostic logs stay under ignored `tmp/`; they do not need to move through Git.
