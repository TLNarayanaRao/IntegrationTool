# Complete-flow throughput qualification

The target is **100,000 correctly transformed and delivered records within 600 seconds of total wall-clock time**, including task orchestration. This is stricter than the earlier activity-only send/receive timings in `MESSAGING_THROUGHPUT.md`. There is no extrapolation from a smaller workload.

## Workload and execution modes

`scripts/flow-throughput.py` builds ordinary MINA project/task definitions:

1. A publish task runs Start → For-Each [Mapper → Publish/Send] → End.
2. A receive task runs Start → Get/Pull → End, repeated if the provider returns a partial batch.
3. Every received payload is checked against the expected transformed object. Missing records, duplicates, corruption, wrong-branch records, task failures, unsuccessful archive shutdown or elapsed time above 600 seconds fail the case.

Four concurrent workers each use a distinct dedicated destination. Each worker processes batches of 1,000 through the complete tasks. The publish task executes eight mappings for **every** record, including trim/uppercase and summation. Messages are approximately 1 KiB. Publishing requests broker delivery confirmation. Each worker completes its send task and receive/audit task before beginning its next batch. Workers share the total 100,000-record workload; this is not 100,000 per worker.

The standalone Mapper workload uses Start → For-Each [Mapper] → End, returns the accumulated batch and checks all transformed records. It exercises group iteration, accumulation and End input mapping as well as Mapper execution.

- **Run:** `WorkflowRuntime.run`, including normal activity/group logging, transition scheduling, configuration/mapping resolution and task state. All concurrent jobs share one runtime, as in Studio.
- **Debug:** `DebugManager.start` and resume through completion, with normal Debug logs/history, group scheduling, task state and session cleanup. Concurrent sessions share the Studio-style runtime/debug manager. There are no manual breakpoint pauses.
- **Direct Python:** four persistent worker processes execute a generated ZIP via `application.main.run_task`. The actual exported tasks, groups, Mapper and connectors run in those processes.
- **Engine Python:** the same process/ZIP execution pattern using the Engine Python export.

The wall clock starts before archive generation/import and worker startup, and ends after final client/process cleanup. It includes input generation, orchestration, send, receive, IPC and exact record validation. Broker provisioning, designer editing, installer construction, browser rendering, periodic Studio status HTTP polling and control-plane transport/persistence are outside this measurement. No activity methods are substituted for complete task execution, and no production logging/caching settings are disabled to obtain a pass.

These are representative batch flows, not a qualification of every possible integration, schema or receiver-starter dispatch pattern. Mapper target XSD validation, authentication/TLS overhead, broker failover and downstream business processing are not part of this workload. Archive results use **four worker processes**; they do not establish the same rate for one serial archive process.

## Providers and results

Measured seconds for 100,000 records (limit: 600 seconds per case):

| Workload | Run | Debug | Direct Python | Engine Python |
|---|---:|---:|---:|---:|
| Kafka + Mapper | 144.1 | 153.7 | 39.7 | 66.6 |
| Local JMS + Mapper | 465.2 | 297.6 | 229.5 | 244.1 |
| Mapper only | 58.0 | 56.1 | 14.6 | 22.5 |

All 12 local cases passed, with every expected payload verified. These results apply to four concurrent workers and 1,000-record task batches. They are not serial single-worker guarantees.

The Kafka Engine archive initially took 372.7 seconds. Replacing timer-based acknowledgement waits with a native poll requesting at most 1 ms produced a final 66.6-second run, while retaining per-record delivery confirmation. Run and Debug also remain below the limit. Runs shared the host with other tests, so this is observed qualification evidence rather than a controlled hardware-normalized speedup claim.


Machine-readable results are `docs/validation/flow-<family>-<mode>-2026-11-15.json`; the final matrix is in `flow-summary-2026-11-15.json`. Only final reports containing all 100,000 verified records and a successful full elapsed-time check qualify. Reports with an `initial` suffix are retained measurement-development evidence and are not the final Studio-runtime qualification.

Kafka uses a real loopback Apache Kafka 3.9.1 broker with dedicated single-partition topics. JMS uses a real loopback Apache ActiveMQ Artemis 2.40.0 broker and persistent sends. **Artemis JMS is not vendor EMS.** GCP Pub/Sub and actual EMS require protected approved QA profiles and dedicated resources before their live full-flow target can be verified. Local test doubles are never used as throughput evidence.

## Reproduction

Use a Python environment containing MINA's backend dependencies and the selected provider SDK. The Direct Kafka archive also needs its normal optional `aiokafka` dependency. For JMS/EMS, configure the complete Java bridge and the actual provider's driver directory using normal deployment settings. Do not commit private profiles or diagnostics.

The shared benchmark host helper also requires the test-only `psutil` package. Install it in the test environment; it is not a new MINA runtime dependency.

Example protected Kafka/JMS/EMS profile:

```json
{
  "dedicatedTestResources": true,
  "connection": {"bootstrapServers": "YOUR_QA_BROKER:9092"},
  "destinations": ["qa-flow-1", "qa-flow-2", "qa-flow-3", "qa-flow-4"],
  "startOffsets": [0, 0, 0, 0]
}
```

Use the selected provider's normal connection object, not Kafka settings for a JMS/EMS connection. Pre-provision a distinct Kafka topic per worker. For a fresh single-partition topic use starting offset zero; otherwise supply the exact starting offsets for **these synthetic test records**. Fresh destinations per mode avoid mixing earlier runs. For Pub/Sub also supply a `subscriptions` array with one dedicated pre-created subscription for each corresponding topic, and the normal project/authentication configuration. Get/Pull consumes and acknowledges data, so business destinations must never be used.

```text
python scripts/flow-throughput.py --family kafka --mode run --config PRIVATE.json --records 100000 --workers 4 --batch-size 1000 --deadline 600 --output RESULT.json --diagnostics PRIVATE_LOG_DIRECTORY
python scripts/flow-throughput.py --family jms --mode debug --config PRIVATE.json --records 100000 --workers 4 --batch-size 1000 --deadline 600 --output RESULT.json --diagnostics PRIVATE_LOG_DIRECTORY
python scripts/flow-throughput.py --family mapper --mode python-direct --records 100000 --output RESULT.json --diagnostics PRIVATE_LOG_DIRECTORY
```

Repeat with `--mode run`, `debug`, `python-direct` and `python-engine`. Use `--family ems` with the actual EMS provider to qualify EMS, or `pubsub` with actual cloud resources. A pass for a different provider is not sufficient. The final JSON excludes connection values and raw provider errors; protected diagnostic files retain errors needed for investigation.

Run the harness correctness tests with `backend` on `PYTHONPATH`:

```text
python -m unittest discover -s backend/tests -p test_flow_throughput.py
```

Those small memory-broker tests verify measurement behavior and error detection; actual generated Mapper ZIP execution is also tested. Their speed is not used in the live 100,000-record qualification.
