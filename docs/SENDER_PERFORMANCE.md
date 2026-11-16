# Sender performance investigation — 16 November 2026

For subsequent Pub/Sub fixes and official-emulator full-flow/soak qualification, see [Pub/Sub throughput](PUBSUB_THROUGHPUT.md). Hosted GCP performance remains a separate qualification.

For the subsequent batch-Get optimization and deadline-qualified 100,000-record soak, see [JMS batch reuse](JMS_BATCH_REUSE.md). This page and its original reports retain the earlier measurement scope.

Sender rates depend on delivery semantics, round-trip latency, persistence, payload size and concurrency. A buffered enqueue rate must not be presented as broker delivery throughput. The sender benchmark waits for final Kafka flush and independently verifies every complete payload, including missing/duplicate detection. EMS/JMS persistent sends retain provider completion semantics. Pub/Sub live results require an approved cloud topic/subscription; local SDK tests do not qualify cloud throughput.

## Changes and verification

- `activity-throughput.py --confirm-delivery` now supports Kafka confirmation on **each** send. Without it, Kafka buffers normally but final flush and full readback are still required. `perSendConfirmation` explicitly records this distinction in the report. Use `--concurrency 1` to measure a serial sender and compare with the same workload at concurrency eight.
- Pub/Sub's explicit batch delay `0` was incorrectly replaced by the 10 ms default through truthiness checks. Runtime, SDK client construction and Direct Python now preserve that override, using MINA's existing 1 ms minimum. Missing/empty settings still default to 10 ms. An activity override of zero takes precedence over a shared connection setting. Authentication, delivery confirmation and persistence defaults are unchanged.
- Three regression tests validate the zero-delay behavior through runtime configuration, actual SDK BatchSettings and the generated-adapter implementation. These are offline correctness tests, not measurements of Pub/Sub service capacity.

Fresh real loopback Kafka topics and a real Artemis JMS queue are used. Reports are `docs/validation/sender-*-2026-11-16.json`. The earlier complete-flow qualification remains documented in `COMPLETE_FLOW_THROUGHPUT.md`; the new measurements isolate sender behavior and do not substitute for those flow measurements. Artemis JMS is not vendor EMS. Actual EMS and Pub/Sub need dedicated QA connection profiles and the affected project/task to reproduce the reported slow integration.

The initial Kafka fixture failed on restart while Windows held an old retention index open. That attempt did not produce a sender qualification. A new empty test data directory was formatted instead of modifying production configuration or deleting old data. Test-only retention covers the entire soak window.

## Diagnosing slow projects

1. Record Run versus Debug, payload bytes, observed records/second, destination, environment, confirmation settings and number of active jobs. Use a dedicated test destination.
2. For Kafka, inspect activity `publisherQueueMs`, `producerSetupMs`, `sendAndWaitMs` and `publishLatencyMs`. Repeated setup time suggests dynamic connection/producer settings or lifecycle churn. A high confirmation time with low queue/setup time points toward the broker/network/acknowledgement path. Do not disable broker acknowledgements to hide a delivery problem.
3. For EMS/JMS, inspect `publishTiming.queueMs`, `bridgeMs`, `totalMs` and native `providerSendMs`. Provider persistence/round trips, sender queue contention and repeated Java-worker creation have different remedies. Per-record new Debug sessions can pay startup/cleanup costs that a single For-Each task session avoids. Retain persistent delivery where the integration requires it.
4. For Pub/Sub, serial confirmed sends may pay batching delay plus network/service latency on every record. Choose the batching delay and concurrency intentionally. Buffered publishing changes when the activity returns; use it only when the flow accepts queued completion and delivery is verified separately. The delay fix does not remove network or provider latency.
5. Avoid changing shared connection/producer options per record unless required: those settings define client cache identity. Keep normal authentication/TLS and delivery requirements during qualification.

## Repeatable test commands

Use the protected dedicated-resource profile format from `MESSAGING_THROUGHPUT.md`. For a fresh single-partition Kafka topic, start at offset zero. Use a new topic for each independent case or set the exact protected `startOffset` for the synthetic test records. Never consume a business topic as an audit step.

```text
python scripts/activity-throughput.py --family kafka --operation publish --config PRIVATE.json --records 100000 --concurrency 1 --confirm-delivery --output SERIAL.json
python scripts/activity-throughput.py --family kafka --operation publish --config PRIVATE.json --records 100000 --concurrency 8 --confirm-delivery --output PARALLEL.json
python scripts/activity-throughput.py --family kafka --operation publish --config PRIVATE.json --records 100000 --concurrency 8 --output BUFFERED.json
python scripts/activity-throughput.py --family kafka --operation publish --config PRIVATE.json --records 1000 --concurrency 8 --confirm-delivery --soak-seconds 600 --cycle-interval 5 --output SOAK.json
```

The paced soak repeats fully verified send/readback cycles and closes clients between cycles. It measures sustained correctness and lifecycle churn; it is not an unpaced maximum-capacity test. Final RSS comparisons alone do not prove absence of all leaks. SDKs, broker configuration and network geography can change results substantially.
