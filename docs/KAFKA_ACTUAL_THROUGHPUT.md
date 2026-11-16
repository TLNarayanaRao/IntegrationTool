# Actual Kafka complete-flow qualification

This qualification uses actual Apache Kafka 3.9.1 in a fresh, single-node KRaft
environment on this Windows development machine. It uses Kafka's real Java broker
and the actual Python client, not a mock, emulator or substituted messaging service.
The environment follows the [Apache Kafka KRaft quick start](https://kafka.apache.org/39/getting-started/quickstart/).
The existing local `kafka_2.13-3.9.1.tgz` was checked against
[Apache's published SHA-512 checksum](https://archive.apache.org/dist/kafka/3.9.1/kafka_2.13-3.9.1.tgz.sha512)
and matched. No new broker distribution was downloaded or installed system-wide.

## Workload and acceptance

Each of Run, Debug, direct Python archive and engine Python archive must finish
100,000 records in at most 600 seconds. Four concurrent task workers each use a
separate fresh single-partition topic, with approximately 1 KiB per record and
1,000 records per task batch. Every record passes through a For-Each group and
an eight-field Mapper, including trim, uppercase and sum transformations, then
through a Kafka publish activity with delivery confirmation. A receive task reads
the records back. Full payloads and unique sequence numbers are checked, including
cross-branch isolation and missing/duplicate detection. Normal Run/Debug logging
and final runtime/client cleanup remain enabled. Both archive tests generate and
execute new archives in separate Python processes; generation, import, startup
and IPC are included in their elapsed times.

The tests call the same WorkflowRuntime and DebugManager used by Studio. They do
not automate mouse interaction with the installed Windows app or measure UI render
latency. The receiver path tested here is Get; continuous receiver triggers,
consumer rebalances, failover, transactions and multi-broker replication are outside
this qualification. A fast 100,000-record test is not a long-duration soak or proof
that every production topology will meet the same deadline.

## Reproduce in another workspace

Keep `scripts/kafka-local-qa.py` and `scripts/flow-throughput.py` in Git. Do not copy
temporary broker stores, generated applications or Python environments. Install
the project's development dependencies, the `aiokafka` client (used by the direct
archive and provisioning), `confluent-kafka` (used by the runtime) and `psutil` for
the benchmark. Supply Java 17 and an extracted Apache Kafka 3.9 distribution, then
run from the repository root:

```text
python scripts/kafka-local-qa.py --kafka-home <extracted-kafka-home> --java <java-executable> --records 100000 --output-dir tmp/kafka-qualification-new
```

The helper launches only its own broker on loopback ports 29092/29093, creates new
topics for every mode, runs the four existing complete-flow benchmarks sequentially
and stops only its broker. It refuses occupied ports and existing report paths.
Override `--port` and `--controller-port` together when necessary. Test-only
PLAINTEXT listeners, replication factor one and 24-hour retention are deliberate
local fixture settings; they do not qualify TLS/SASL or replicated deployments.
Fresh storage avoids reopening old Windows Kafka indexes. Storage and private
diagnostics remain under the ignored output directory for investigation; the
helper does not delete previous test data or modify installed broker configuration.

Read each mode's JSON result and private diagnostic log when a test fails. A
nonzero child exit or failed payload/deadline audit prevents a passing summary.
The broker distribution is a local prerequisite and is not bundled with MINA.

## Results

On 2026-11-16 all four modes passed with 100,000 unique full payloads verified in
each mode (400,000 records in total):

| Mode | Elapsed seconds | Verified records/second | Result |
| --- | ---: | ---: | --- |
| Run | 85.159 | 1,174.3 | Pass |
| Debug | 90.577 | 1,104.0 | Pass |
| Direct Python archive | 27.995 | 3,572.1 | Pass |
| Engine Python archive | 39.844 | 2,509.8 | Pass |

The minimum required rate is 166.7 records/second. Run retained 701,800 log entries
across completed task results; Debug retained 501,500 across those results. These
counts are accumulated observations, not the number of entries resident at once.
The environment used Java 17, Python 3.11.9, aiokafka 0.12.0 and confluent-kafka
2.16.1. Broker logs contained no ERROR/FATAL entries during these tests.

A 100-record smoke test also passed in all four modes. Thirty focused flow,
messaging-throughput, sender-setting and connector regression tests passed.
Launcher checks confirmed occupied-port refusal and existing-report preservation.
The temporary broker was stopped and ports 29092/29093 were confirmed closed.
No new runtime performance or correctness defect was found by this workload;
no runtime code changes were necessary for this qualification.

See the [aggregate report](validation/kafka-actual-summary-2026-11-16.json) and
its four linked per-mode report filenames for the sanitized measurements.
Actual EMS qualification remains separate and blocked on its server distribution;
Kafka results do not establish EMS or hosted Pub/Sub performance.
