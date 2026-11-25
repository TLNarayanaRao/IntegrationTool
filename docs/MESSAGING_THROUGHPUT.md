# Messaging and DataCompose throughput qualification

The acceptance target is **100,000 records per direction within 600 seconds**, or at least 166.67 records/second. Lower elapsed time is better. Results are workload- and environment-specific; this is not a universal performance guarantee.

For the subsequent **complete-flow** qualification, including task orchestration and 100,000-record archive execution, see [Complete-flow throughput](COMPLETE_FLOW_THROUGHPUT.md). The activity-only and small compatibility reports below retain their original scope and are historical evidence, rather than the final full-flow matrix.

## Reproducible workload

`scripts/activity-throughput.py` calls MINA's actual `WorkflowRuntime.execute` send and Get activities against dedicated broker resources. Each message is a 1,024-byte JSON payload containing a unique run identifier, sequence number and padding. Eight concurrent send calls are used; receives request batches of up to 1,000. Every record is independently read back and its complete payload checked for corruption, duplication and missing sequence numbers. Kafka publishing includes a successful delivery flush; it does not count enqueueing alone as completed delivery. Pub/Sub publishing explicitly requests delivery confirmation. Seeding is outside the receive timer; readback is outside the publish timer.

These activity benchmarks exclude the Studio UI, whole-task graph orchestration, execution-log collection, downstream business work and network latency beyond the local broker. They do not measure persistent receiver-starter dispatch, individual-record latency, failover or TLS authentication overhead. A batch Get result is not a measurement of 100,000 independently launched Get activities.

DataCompose uses eight mappings, including trim/uppercase, sum, direct paths and nested targets, on approximately 1 KiB records. Every result is checked. Target XSD validation is not enabled in that workload; complex schemas, loops, XSLT and larger documents require separate capacity tests.

## Runtime changes

- Kafka Get performs its blocking provider work outside the asyncio event loop. It waits for the first record and drains immediately available records, instead of paying a complete timeout for every empty slot. Consumer setup/decoding failures close the consumer; manual confirmation retains ownership until confirmation.
- Generated Kafka publishers honor an explicitly selected partition for buffered and confirmed sends. The qualification fixture pins both send and receive to partition zero; otherwise an auto-created multi-partition topic can make a one-partition read miss the published record.
- EMS/JMS Get accepts `maxMessages` from 1 to 10,000, defaulting to one for existing projects. One total receive timeout bounds the batch. `body` and legacy headers refer to the first record; `messages` and `count` expose the complete batch. Run and generated Python adapters retain all received bodies. Use batching to amortize Java bridge startup; default single-message Gets do not meet the stated throughput target on this test host.
- Shared native listeners wake the asyncio consumer when a delivery arrives, replacing a fixed 50 ms polling sleep. Cancellation removes its waiter without abandoning a blocked executor thread. This is correctness-tested; a high-rate receiver-starter SLA is not yet qualified.
- Pub/Sub cached publishers no longer reconstruct service-account credentials/private keys before reusing the cached client. Authentication validation still happens when a new client is created. Pull is recognized as a receive operation, runs blocking provider work outside the event loop, and closes failed receives. Manual confirmation retains the subscriber until its last acknowledgement. These changes are regression-tested but require actual cloud measurement before a throughput claim.

## Results and scope

Machine-readable reports are in `docs/validation/throughput-*-2026-11-15.json`. The Kafka broker is Apache Kafka 3.9.1 on loopback. JMS tests use Apache ActiveMQ Artemis 2.40.0 with persistent sends and the JMS bridge. **Artemis is not vendor EMS**. Live GCP Pub/Sub and vendor EMS require approved QA connections and dedicated topics/subscriptions/queues; their 100,000-record targets remain unverified.

The JMS pre-change baseline of 20 single-message Gets took 32.03 seconds. That small baseline is diagnostic evidence, not an acceptance test. The 1,000-record Kafka baseline is likewise not the 100,000-record qualification.

DataCompose completed a continuous 600-second soak, processing and checking 4,995,087 records. Its first 100,000 took 11.491 seconds (8,702.7 records/second). Final process RSS was essentially unchanged (-0.016 MiB); this endpoint comparison alone does not prove absence of all leaks.

Kafka's 100,000 confirmed publishes took 24.036 seconds (4,160.5/second). Receiving and checking those records took 3.208 seconds (31,176.8/second). See the separate paced-soak report for sustained cycling; a paced soak is not an unpaced maximum-capacity measurement.

The Kafka paced soak completed 120 verified send/readback cycles over 601.03 seconds: 120,000 records checked, no record failures, and +2.66 MiB final RSS. Local JMS confirmed 100,000 persistent sends in 433.727 seconds (230.56/second), then received and checked them in 205.504 seconds (486.61/second), using batches of 1,000. Final RSS growth was +1.75 MiB. Both directions met the separate 600-second target. Their combined sequential elapsed time exceeds 600 seconds; this does not establish a simultaneous end-to-end task SLA.

The final small live round-trip compatibility checks passed for Kafka and JMS in Run, Debug, Direct Python and Engine Python. These checks execute generated applications, but are not 100,000-record archive benchmarks. Earlier failed compatibility reports are retained with `multipartition-fixture` and `partition-routing` suffixes; the first exposed a fixture mismatch and the follow-up identified the generated publisher's missing explicit-partition handling. Use the unsuffixed final report for the corrected results.

## Running against dedicated QA resources

Create a protected JSON file outside Git:

```json
{
  "dedicatedTestResources": true,
  "connection": {"projectId": "YOUR_QA_PROJECT"},
  "destination": "YOUR_DEDICATED_TOPIC",
  "subscription": "YOUR_DEDICATED_SUBSCRIPTION"
}
```

Use the corresponding shared connection configuration for Kafka or EMS/JMS. For Pub/Sub, provision the subscription before publishing, use the same project and supply normal ADC or protected service-account configuration. The benchmark publishes synthetic messages and consumes/acknowledges them. Never point it at business traffic.

```text
python scripts/activity-throughput.py --family pubsub --operation publish --config PRIVATE.json --records 100000 --concurrency 32 --batch-size 1000 --output RESULT.json
python scripts/activity-throughput.py --family ems --operation receive --config PRIVATE.json --records 100000 --batch-size 1000 --output RESULT.json
python scripts/activity-throughput.py --family mapper --operation map --records 100000 --soak-seconds 600 --output RESULT.json
```

Both broker-direction timings are recorded in a single run. Confirm that **both** are within 600 seconds. `passed` evaluates the selected `--operation`. A receive-only run still publishes its own unique data first, so no pre-existing business messages are consumed intentionally.

For a paced broker soak, add `--records 1000 --soak-seconds 600 --cycle-interval 5`. The same queue/subscription is reused after verified consumption; Kafka uses a single-partition dedicated topic and advances its custom offset between cycles. Set protected profile `startOffset` if the dedicated topic is not initially empty. Report duration includes client cleanup and pacing. No forced garbage collection is performed.

Run offline regressions with `python -m unittest discover -s backend/tests -p test_messaging_throughput.py`, with `backend` on `PYTHONPATH`. These test doubles protect behavior and do not establish cloud or vendor throughput.
