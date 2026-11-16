# Pub/Sub optimization changed files

Changes for this request only; existing unrelated edits were preserved. No new MINA runtime dependency versions were added. Downloaded emulator binaries, temporary profiles and diagnostics remain under ignored tmp/.

- [backend/app/runtime.py](D:/Integration-tool/IntegrationFabric/backend/app/runtime.py) — Async SDK confirmation waits, fully qualified resource routing and bounded Pull batch sizing.
- [backend/app/raw_python_support/connectors.py](D:/Integration-tool/IntegrationFabric/backend/app/raw_python_support/connectors.py) — Direct async confirmation/enqueue, bounded publisher backpressure, regional endpoints, receive timeout and Auto Pull acknowledgement.
- [backend/tests/test_pubsub_throughput.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_pubsub_throughput.py) — Executor availability, acknowledgement mode, endpoint/flow-control and resource-name regressions.
- [backend/tests/test_flow_throughput.py](D:/Integration-tool/IntegrationFabric/backend/tests/test_flow_throughput.py) — Protect Debug cleanup from bounded-history eviction while cleanup awaits.
- [scripts/flow-throughput.py](D:/Integration-tool/IntegrationFabric/scripts/flow-throughput.py) — Match Studio stopping-state lifecycle before awaiting cleanup; preserve normal retention.
- [scripts/pubsub-emulator-qa.py](D:/Integration-tool/IntegrationFabric/scripts/pubsub-emulator-qa.py) — Own a loopback-only temporary official emulator, provision/clean resources and run four modes plus strict soak.
- [docs/PUBSUB_THROUGHPUT.md](D:/Integration-tool/IntegrationFabric/docs/PUBSUB_THROUGHPUT.md) — Final results, code changes, temporary environment provenance, reproduction and hosted-cloud limits.
- [docs/SENDER_PERFORMANCE.md](D:/Integration-tool/IntegrationFabric/docs/SENDER_PERFORMANCE.md) — Link earlier sender evidence to the new emulator qualification.
- [frontend/scripts/build-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) — Add the Pub/Sub guide to Studio help.
- [frontend/scripts/developer-documentation.mjs](D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) — Fingerprint the new test and QA launcher sources.
- [frontend/public/help/documentation-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) — Regenerated help/manual artifact.
- [frontend/public/help/documentation-data.js](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) — Regenerated help/manual artifact.
- [frontend/public/help/developer-data.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) — Regenerated help/manual artifact.
- [frontend/public/help/documentation-build.json](D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) — Regenerated help/manual artifact.
- [frontend/public/help/MINA-Documentation.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) — Regenerated help/manual artifact.
- [frontend/public/help/MINA-Developer-Guide.pdf](D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) — Regenerated help/manual artifact.
- [docs/validation/pubsub-emulator-flow-debug-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-flow-debug-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [docs/validation/pubsub-emulator-flow-debug-cleanup-fixture-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-flow-debug-cleanup-fixture-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [docs/validation/pubsub-emulator-flow-python-direct-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-flow-python-direct-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [docs/validation/pubsub-emulator-flow-python-engine-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-flow-python-engine-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [docs/validation/pubsub-emulator-flow-run-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-flow-run-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [docs/validation/pubsub-emulator-soak-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-soak-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [docs/validation/pubsub-emulator-summary-2026-11-16.json](D:/Integration-tool/IntegrationFabric/docs/validation/pubsub-emulator-summary-2026-11-16.json) — Measured emulator result or retained initial cleanup-fixture failure; use the summary for qualification.
- [This file index](D:/Integration-tool/IntegrationFabric/docs/PUBSUB_THROUGHPUT_CHANGED_FILES.md) — Request-specific changed-file list.
