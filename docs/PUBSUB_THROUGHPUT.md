# Pub/Sub throughput and temporary environment

## Qualification scope

An official Google Pub/Sub emulator was provisioned locally because no GCP QA environment was available. This is a real gRPC/client-library integration test against Google's emulator, not an in-memory MINA message queue or mocked SDK speed test. It **does not qualify hosted GCP throughput**, IAM, service-account token refresh, TLS, regional network latency, quotas, failover or exactly-once delivery. Google's documented emulator limitations apply: [Testing locally](https://docs.cloud.google.com/pubsub/docs/emulator).

Temporary environment: emulator component **0.8.38**, fetched from Google's SDK component manifest, archive SHA-256 `f55bde05f616816e44da6e237e82cd41b6e43ba0c6cdca7c479179681ebe1168`. The server bound only to `127.0.0.1:18085`, used project `mina-qa`, anonymous emulator credentials and fresh synthetic topics/subscriptions. No cloud project, billable resource or global credential/environment setting was created. Emulator binaries and private diagnostics remain under ignored `tmp/` and are not redistributed with MINA.

## Measured results

Each complete flow processed and checked **100,000 records** within the **600-second limit**:

| Mode | Seconds | Result |
|---|---:|---|
| Run | 369.4 | Passed |
| Debug | 371.5 | Passed |
| Direct Python archive | 319.1 | Passed |
| Engine Python archive | 333.1 | Passed |

Four concurrent workers process 1,000-record task batches. The publish task executes Start → For-Each [eight-field DataCompose → confirmed Publish] → End. A receive task executes Start → Pull → End, repeating for partial batches. Every sequence number and complete transformed payload is checked for missing records, duplication, corruption and wrong-branch routing. Run/Debug share the Studio-style runtime/debug manager. Archives execute their actual generated ZIP contents in four persistent processes. Timings include archive generation/import/startup where applicable, task orchestration, normal logging, SDK calls, IPC, full readback validation and cleanup. Browser rendering and control-plane persistence are excluded. This qualifies these batch Pull flows, not every schema or streaming/manual-ack starter topology.

The separate 10-minute soak used 32 concurrent confirmed send callers, 2,000-record cycles and a ten-second minimum cycle interval. It reached **100,000 fully verified records at 491.369 seconds** and counted **120,000 before the 600-second window ended**. Total duration was 600.382 seconds. Client creation/cleanup and audit are included; late cycles cannot satisfy the strict count gate. No forced garbage collection was used. Endpoint RSS growth alone cannot establish absence of all leaks.

Results: `docs/validation/pubsub-emulator-*-2026-11-16.json`. The initial Debug cleanup-fixture failure is retained separately and excluded from qualification. The harness now marks a completed session as stopping before awaiting native cleanup, matching Studio Stop ordering, so bounded history cannot evict it mid-cleanup. Retention settings remain enabled.

## Runtime and export changes

- Confirmed sends await real SDK futures through asyncio instead of occupying shared executor threads for the duration of network acknowledgement. This preserves message IDs, confirmation and error propagation. Timeout/cancellation does not cancel an uncertain underlying send; late exceptions are consumed. Rare uncached one-shot clients retain their existing synchronous completion/cleanup path.
- Direct Python publisher enqueueing runs off its event loop. Its message/byte flow-control limits use bounded SDK backpressure, matching the engine settings; the regional endpoint override is passed to the SDK. Defaults for queued versus confirmed completion are unchanged.
- Direct Pull now acknowledges received records in Auto mode. Previously unacknowledged records could be redelivered and consume throughput. Explicit Client/manual modes are not auto-acknowledged; application acknowledgement handling remains required and is outside this qualification.
- Pull batching respects the service's 1,000-message response limit, and Direct Pull honors the configured receive timeout. Source/engine accept fully qualified topic/subscription paths without prefixing them twice. See [Pub/Sub limits](https://docs.cloud.google.com/pubsub/quotas) and [Pull semantics](https://docs.cloud.google.com/pubsub/docs/reference/rest/v1/projects.subscriptions/pull).

No delivery default was changed to obtain these results. This test requests confirmation for each publish and audits readback; buffered enqueueing alone is not counted as delivered work. Subscriber clients retain their existing per-Pull/manual-ack ownership behavior; no shared subscriber cache was introduced.

## Reproducing a temporary environment

Use an appropriate Java runtime, MINA backend dependencies, Google Pub/Sub Python client and the benchmark's test-only `psutil` dependency. Obtain the official emulator JAR through the Google Cloud SDK component installer or its official component manifest. Do not commit the downloaded emulator binary.

The reusable launcher owns its emulator process, creates unique topics/subscriptions, runs all four modes, deletes completed-case resources and restores its process environment. It refuses to reuse an occupied port or stop another server. A supplied JAR is required; the launcher does not install system-wide software.

```text
python scripts/pubsub-emulator-qa.py --jar PATH_TO_OFFICIAL_EMULATOR_JAR --java PATH_TO_JAVA --port 18085 --records 100000 --workers 4 --soak-seconds 600 --output-dir tmp/pubsub-qa
```

Smoke check of the launcher and all four modes:

```text
python scripts/pubsub-emulator-qa.py --jar PATH_TO_OFFICIAL_EMULATOR_JAR --java PATH_TO_JAVA --port 18086 --records 10 --workers 1 --soak-seconds 0 --output-dir tmp/pubsub-smoke
```

For hosted GCP qualification, use approved dedicated QA topics/subscriptions with the protected profile formats and flow commands from `COMPLETE_FLOW_THROUGHPUT.md`. Remove `PUBSUB_EMULATOR_HOST`, supply normal GCP authentication, and rerun the same exact count/deadline gates. Never infer hosted performance from emulator timings or consume business subscriptions during an audit.
