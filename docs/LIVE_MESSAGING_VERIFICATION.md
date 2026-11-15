# Live messaging verification

## What was actually exercised

Real Kafka 3.9.1 and Artemis 2.40.0 broker processes were started in an isolated temporary directory. They listened on loopback test ports with dedicated topics and queues; existing project destinations were not used. Kafka, JMS and AMQP 1.0 each passed a real round trip in Run, Debug, Direct Python and Engine Python: twelve checks in total. The exported applications were run through their command-line entry points, including connector shutdown.

This verifies JMS against Artemis, **not vendor EMS**. It also does not verify Google Cloud Pub/Sub, SAP, RabbitMQ AMQP 0.9.1, Azure Service Bus, SASL/TLS variants, clustered failover or maximum throughput. Those need the corresponding environments and dedicated approved test resources. A saved connection alone does not identify which existing business destinations may be used for a soak.

The local setup follows the [Kafka KRaft quickstart](https://kafka.apache.org/39/getting-started/quickstart/). [Artemis](https://artemis.apache.org/) supplies the real JMS/AMQP test broker. Their binary distributions were checked against the official SHA-512 files and kept under ignored `tmp/`; no broker binaries or downloaded SDKs were added to the repository or installer.

## Issues found and fixed

- AMQP 1.0 sends passed `None` to Proton's TTL setter, which failed even with default options. No-expiration sends now omit TTL, and positive expiration values convert activity milliseconds to Proton seconds.
- AMQP receive passed an unsupported `auto_accept` keyword to the blocking client. Automatic receive now explicitly settles the received delivery. Manual acceptance/rejection uses the blocking SDK's argument-free methods and closes owned resources afterwards.
- Only an actual Proton timeout means no message. Other receive failures now propagate as adapter faults instead of being hidden as an empty queue.
- Absent AMQP content-type/correlation fields are omitted from the SDK constructor instead of being explicitly passed as `None`.
- Kafka consumers no longer inherit the producer-only request-timeout setting that emitted a native warning on every polling operation.
- Direct export specialization now normalizes Kafka Send/Get and Pub/Sub Subscribe aliases before selecting code. Previously it could remove the receive/pull branch and fail with `Unsupported Kafka operation: receive` in a real exported application.
- Direct Kafka receive now honors the configured initial offset policy and custom partition/seek options. Consumer startup is inside its cleanup scope.
- The Pub/Sub custom-CA credential wrapper preserves Google's SDK constructor/copy contract for scope, JWT-access and quota-project copies. Wrapper types are bounded to 32 cached combinations. An explicitly created TLS transport closes if client construction fails. These changes are verified with the installed Google SDK and local failure injection, **not live cloud authentication**.
- SAP soak instrumentation now retains at most 10,000 latency samples and 1,000 error samples, with separate total counters and exact running min/mean/max. This is an instrumentation correction; it is not evidence of a live SAP test.
- Scoped Java process termination now waits after a forced kill. Java timeout errors report the configured budget rather than a negative remaining timeout exposed by Windows after an interruption.

## Sustained-load evidence and its limit

The first unpaced run stopped after 169 measured seconds, following 60 seconds of warmup. It completed 18,482 Kafka, 10,460 AMQP and 209 JMS round trips before a connection failure. It did **not** pass duration/error gates. Native connection errors occurred across the local brokers during the high-churn workload; Windows ephemeral-port pressure is a hypothesis, not a confirmed root cause or a fixed production issue. The failed result is retained in `docs/validation/live-messaging-first-pass-2026-11-14.json`.

A later bounded-rate attempt and its two archive attempts failed when the temporary Windows Kafka broker shut down. With logging enabled, recovery reproduced a retention-cleanup failure renaming a locked `.index` file, followed by all log directories being marked failed. The retained diagnostic is `docs/validation/kafka-windows-storage-failure-2026-11-14.txt`; failed reports include `live-messaging-broker-failure-2026-11-14.json` and both `live-messaging-archive-*-first-pass-2026-11-14.json` files. This establishes a broker storage failure for that later outage; it does not prove the cause of the earlier unpaced AMQP failure.

The final attempt uses a fresh temporary Kafka data directory, test-only retention of one day and a 1 GiB per-partition byte threshold, outside this small test workload. No existing broker data was deleted and no production retention setting was changed. This avoids exercising the failing Windows retention path; it does not fix or qualify that broker path. Production Kafka storage, retention and failover still require qualification on the target platform.

The final sustained run uses six workers, 60 seconds of warmup, 1,800 measured seconds, and a minimum cycle interval of one second per worker. That caps each worker at one round trip per second; JVM-based JMS may be slower. Its result is `docs/validation/live-messaging-2026-11-15.json`. A pass at this declared load does not resolve or qualify the unpaced high-rate failure.

The runner checks sent/received tokens, duration, unexpected errors, client RSS growth, late RSS slope, handles and threads. It samples child-process counts and RSS separately. Client gates are at most 128 MiB RSS growth, 0.5 MiB/minute late RSS slope, 24 additional handles and 8 additional threads. It does not force garbage collection. Broker RSS, disk growth and child-process resource trends must also be reviewed; the client gates alone are not complete server qualification. Counts include warmup. Latency retention is bounded.

The November 14 attempts were interrupted and remain failed. Windows power events were present during that test window, and sampled activity stopped well before the requested continuous duration even though wall-clock elapsed times grew to roughly an hour. Final continuous attempts are recorded under `2026-11-15` filenames. On Windows the runner now holds a temporary thread-scoped system execution request during the test and restores the prior state on exit; it does not change the power plan or require the display to remain on. A new continuity gate requires samples near both ends of the requested measurement window and rejects sample gaps exceeding 60 seconds. Manual suspension or infrastructure interruption still invalidates a run.

## Running against approved QA resources

Keep a resolved connection configuration in a protected local JSON file outside Git. Supply one dedicated pre-created destination per worker; do not use business topics, queues or subscriptions. The runner does not delete or purge remote resources. A Kafka destination must be a fresh single-partition topic for offset-zero sequential checks. AMQP queues must exist before the first send; a broker may accept a message to an address with no queue and discard it according to its routing policy.

```json
{
  "durationSeconds": 1800,
  "warmupSeconds": 60,
  "minimumCycleSeconds": 1,
  "scope": "Approved QA system and declared load",
  "families": [
    {
      "type": "kafka",
      "connection": {"bootstrapServers": "QA_HOST:9092"},
      "destinations": ["DEDICATED_FRESH_TOPIC_WORKER_1"]
    }
  ]
}
```

Supported round-trip runner families are `kafka`, `jms`, `ems` and `amqp`. Connections use MINA's existing connection configuration keys. JMS/EMS also need a compatible Java runtime, compiled bridge and the provider's permitted client libraries. The scripts require the backend environment and test-only `psutil`; Direct Kafka also needs `aiokafka`. Use deployment secret practices for real authentication values. The sample above is structural, not a usable connection.

```powershell
Set-Location <checkout>
python scripts/live-messaging-soak.py --config <private-qa-config.json> --output <private-report.json> --private-diagnostics <private-log-directory>
```

For mode verification, supply exactly four separate fresh destinations per family, in Run/Debug/Direct/Engine order:

```powershell
python scripts/live-messaging-verify.py --config <private-mode-config.json> --output <private-mode-report.json> --private-diagnostics <private-log-directory>
```

Public reports omit connections, credentials, payloads and provider exception text. Optional private diagnostics contain provider/runtime details and must remain protected. Resolve credentials locally; do not send passwords or tokens in chat.

### Sustained generated-archive execution

`scripts/live-messaging-archive-soak.py` builds each selected format into a private ZIP, imports it in a separate Python process per worker, and repeatedly calls its generated task in one event loop. Kafka, JMS and AMQP use real network connections. Each child closes its SDK clients and Java sender workers before exiting; an unclosed-resource diagnostic or forced shutdown fails qualification.

The generated process reports its own PID so resource samples refer to the actual interpreter. On this Windows virtual environment the launcher PID returned by `Popen` is a different, small process. Earlier launcher-only measurements were explicitly invalidated and retained as `live-messaging-archive-*-launcher-measurement-2026-11-15.json`; they cannot establish application memory stability. Final reports must show `actualInterpreterIdentified: true` for every worker.

Give each format its own fresh destinations. The final local archive runs use one worker per family, 60 seconds of warmup and 900 measured seconds per format, with the same one-second minimum cycle interval. In addition to controller metrics, each generated Python process has separate gates: at most 64 MiB RSS growth, 16 extra handles, 4 extra threads and 0.5 MiB/minute late RSS slope. These gates cover the generated Python processes; nested Java process trends remain a separate measurement/qualification concern.

```powershell
python scripts/live-messaging-archive-soak.py --mode python-direct --config <private-direct-config.json> --output <private-direct-report.json>
python scripts/live-messaging-archive-soak.py --mode python-engine --config <private-engine-config.json> --output <private-engine-report.json>
```

The final local results are `docs/validation/live-messaging-archive-direct-2026-11-15.json` and `docs/validation/live-messaging-archive-engine-2026-11-15.json`. A failed child resource gate means that archive run failed even if individual message round trips succeeded. A separate Direct startup failure on the fresh broker is retained in `live-messaging-archive-direct-second-pass-2026-11-14.json`; its original child traceback was not retained, so its cause is unresolved. Subsequent runs retain private diagnostics. Do not treat a later pass as explaining that earlier failure.

### Repeated automated Debug sessions

`scripts/live-messaging-debug-soak.py` uses the same real-broker flows through `DebugManager.start`, resume and stop, repeatedly creating and closing sessions. The final local Debug run uses one worker per family, 60 seconds of warmup and 600 measured seconds, with a one-second minimum cycle interval. Its result is `docs/validation/live-messaging-debug-2026-11-15.json`. This exercises the Debug service and its session cleanup, not an interactive installed Studio GUI.

The initial Debug harness omitted Studio Stop's scoped native-process termination. That harness omission retained sender workers until cache/idle cleanup; it was corrected before the final November 15 attempt. It is not evidence that Studio's Stop endpoint omitted that cleanup.

### Additional live protocol cases

The opt-in `backend/tests/test_live_messaging_services.py` checks default AMQP expiry/auto-settlement, positive expiry in milliseconds, custom properties/content type/priority/correlation, manual settlement, actual message expiry, and JMS request/reply through a temporary reply destination with correlation preserved. The local run passed all four tests against Artemis. These are separate protocol checks, not additional cloud or EMS evidence.

To run them, set `MINA_LIVE_EDGE_CONFIG` to a protected JSON file containing `approvedTestDestinations: true`, `amqpConnection`, three dedicated existing `amqpQueues`, `jmsConnection`, and a dedicated `requestReplyQueue`, then run `python -m unittest tests.test_live_messaging_services -v` from `backend`. With no explicit configuration, discovery skips these live checks. Do not point them at business queues.

```powershell
python scripts/live-messaging-debug-soak.py --config <private-debug-config.json> --output <private-debug-report.json> --private-diagnostics <private-log-directory>
```

## Services still needing live qualification

| Service | Required to proceed |
| --- | --- |
| Cloud Pub/Sub | Approved QA project, publisher/subscriber credentials or ADC setup, dedicated topic/subscription, IAM permissions and certificate requirements |
| Vendor EMS | Approved server, provider Java client JARs, credentials, dedicated queues/topics and acknowledgement/transaction requirements |
| SAP | Approved QA system, permitted JCo JAR/native library, credentials, allowed test RFC such as an approved connection-test function, and declared listener/IDoc test scope |

The existing `scripts/sap-production-soak.py` accepts a protected configuration based on `docs/sap-soak-config.example.json`. Do not run posting, update, IDoc or failure-injection cases without the corresponding QA scope. Its percentile fields describe the retained window; total counts and min/mean/max describe the whole run.

Until those inputs are supplied, these services are **not live-verified**. Unit doubles, an emulator or an alternative JMS provider must not be reported as a cloud, EMS or SAP pass.
