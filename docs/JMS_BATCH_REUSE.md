# JMS batch Get reuse and strict soak qualification

The target is at least **100,000 persistent-send/readback records fully audited before the 600-second soak window ends**. This is stronger than the earlier paced correctness soak, which processed 92,000 roundtrips over approximately 605 seconds. Records finishing after the new window are excluded from its acceptance count.

## Measured results

The strict soak passed: **100,000 verified roundtrips by 589.394 seconds**. The complete run ended at 603.155 seconds with 102,000 records audited; the final 2,000 records were excluded from the deadline-qualified count. The prior comparable lifecycle soak audited only 92,000 records over about 605 seconds.

Complete flows, 100,000 records each (limit 600 seconds):

| Mode | Seconds | Result |
|---|---:|---|
| run | 414.1 | Passed; all payloads verified |
| debug | 323.2 | Passed; all payloads verified |
| python-direct | 137.3 | Passed; all payloads verified |
| python-engine | 151.3 | Passed; all payloads verified |

Profiles, timing limits and the actual-provider qualification boundary below are part of these results. Rates are workload/host-specific, not a universal production SLA. Reports and the final matrix are `docs/validation/jms-optimized-*-2026-11-16.json`.

## Runtime optimization

Batch Gets (`maxMessages > 1`) reuse a bounded, scope-isolated Java worker, physical provider connection and auto-acknowledge session. Previously each Get started a JVM and established a new connection. A separate receive-worker cache identity prevents a waiting receive from occupying the sender's worker/session. The existing eight-worker sender budget is preserved, with a separate four-worker batch-Get budget. Receive fanout cannot exhaust publisher cache capacity; excess configurations within each role retain the one-shot fallback. Idle reaping, application/Debug Stop and process cleanup release workers.

Connections with an explicit JMS `clientId` retain one-shot Get ownership, respecting provider-wide client-ID uniqueness/lifetime rules. The qualification profile does not configure a client ID.

Receive cache identity includes destination, selector and queue/topic/JNDI mode. A waiting Get on an empty destination/filter therefore does not occupy a different destination/filter's cached session. The role-specific bounds and one-shot fallback still apply.

Each Get creates its own consumer, applies that call's destination and selector, and **closes the consumer before returning**. It does not keep an active consumer holding prefetched messages between calls. Every batch retains its original total receive timeout and bounded maximum of 10,000 messages. The default single-message Get and request/reply still use the original one-shot path. Persistent send settings, priority/TTL reset, acknowledgement defaults and ordering of calls on a session are preserved. Uncertain sends or receives are never automatically replayed after bridge failure.

`receiverReused` identifies subsequent batch Gets served by an existing receiver worker. Existing `body`, headers, properties, messages and count remain available. Receive-only Run applications now participate in application/shutdown worker cleanup too.

Both Python formats include the updated Python bridge support. **Rebuild the Java bridge with the matching source** when rebuilding Studio or deploying the archives; an older bridge lacks the receive RPC command. Normal provider driver and complete Java runtime prerequisites still apply.

## Test workload

The strict activity soak uses real loopback Artemis JMS 2.40.0, persistent sends, approximately 1 KiB records, eight concurrent send callers, 2,000 records per cycle and Gets of up to 1,000. Its existing ten-second minimum cycle interval remains in place. Every payload and sequence number is checked for corruption, duplication, omission and cross-run contamination. The benchmark includes cycle startup, teardown and readback. A cycle contributes to `verifiedWithinWindow` only when its complete audit and cleanup have finished by 600 seconds. The final cycle may finish later, but cannot inflate the acceptance count.

Complete flows independently execute Start → For-Each [eight-field Mapper → persistent Send] → End, then Start → batch Get → End with exact payload auditing. Four workers process a shared total of 100,000 records. Run/Debug share the Studio-style runtime/debug manager. Each archive is generated, imported and run in four persistent worker processes. Archive generation/startup, task orchestration, input generation, IPC, payload checks and shutdown are inside each full-flow timer. The limit is 600 seconds per mode.

These are automated runtime/Debug engine tests, not browser rendering or control-plane persistence tests. Other schemas, single-record flows, receiver-starter dispatch, TLS, failover and different provider/network topologies require their own qualification. The local broker is **Artemis JMS, not the actual EMS provider**. The shared code supports both MINA activity types, but actual EMS throughput remains unverified without an approved EMS QA connection and queues.

## Reproduction

Use the dedicated private profiles documented in `SENDER_PERFORMANCE.md` and `COMPLETE_FLOW_THROUGHPUT.md`, with fresh queues for independent runs. Never use business queues. Rebuild the Java bridge first using the normal Studio/sidecar build, or compile its source into the configured test bridge classes directory. Use the normal provider driver directory and Java executable settings.

```text
python scripts/activity-throughput.py --family jms --operation publish --config PRIVATE.json --records 2000 --batch-size 1000 --concurrency 8 --soak-seconds 600 --cycle-interval 10 --minimum-soak-records 100000 --output SOAK.json
python scripts/flow-throughput.py --family jms --mode run --config PRIVATE_FOUR_QUEUES.json --records 100000 --workers 4 --batch-size 1000 --deadline 600 --output FLOW.json --diagnostics PRIVATE_LOG_DIRECTORY
```

Repeat the flow command for `debug`, `python-direct` and `python-engine`. Use `--family ems` and the actual approved EMS provider configuration to qualify that provider; local JMS results are not a substitute. The runtime soak now fails explicitly if its minimum record count is not reached inside the requested window.

Native contract tests compile the real Java bridge with a disposable JMS fixture. They check reuse, per-call consumer closure/selector handling, independent sender/receiver pools and no replay on receive error. These offline cases establish correctness, not live provider performance. Reports are under `docs/validation/jms-optimized-*-2026-11-16.json`.

The pre-isolation Run result and a stopped-broker fixture failure are retained separately for traceability and excluded from the final matrix.
