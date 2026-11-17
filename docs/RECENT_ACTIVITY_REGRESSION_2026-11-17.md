# Recent activity regression verification — 2026-11-17

The checked-out Mapper, Transformer, Data, Kafka, Pub/Sub and EMS/JMS changes were exercised with automated regression tests and complete flows. A JMS credential/default-factory inconsistency was found and fixed. This is a bounded regression qualification, not a guarantee of every provider, workload or deployment.

## Verification matrix

Each flow below ran in **Run, Debug, Python direct archive and Python engine archive**. Archive tests generate and execute the archives. Run/Debug use the runtime and debug manager used by Studio; this verification did not include a fresh interactive browser session.

| Area | Fresh workload per mode | Environment and result |
|---|---|---|
| Mapper | 10,000 streamed records | Source/target validation and output auditing passed |
| Transformer | 10,000 streamed records | Scripting-library transformation and schema-validated output passed |
| Parse/Render Data | 35,000 records / 72,963,904 bytes | Nested streaming round-trip and byte/hash audit passed |
| Grouped Parse/Render Data | 1,000 header/detail/trailer groups, 2,000 details | Grouping, totals, uniqueness, XSD identity constraints and invalid-EOF output preservation passed |
| Kafka | 2,000 records | Actual isolated Apache Kafka 3.9.1 broker; publish/readback and exact-payload audit passed |
| Pub/Sub | 2,000 records | Official local Pub/Sub emulator; publish/readback and payload audit passed |
| JMS activity | 2,000 records | Actual isolated Artemis 2.40.0 broker, provider-default credentials; passed |
| EMS activity | 2,000 records | Actual Artemis through the configured JMS factory, exercising the EMS activity path; passed |

The full backend suite completed **747 tests: 736 passed, 11 skipped**, before the final JMS-only correction. The post-fix messaging subset completed **40 tests, all passed**, including the actual Java bridge authentication/reflection regressions and runtime credential-validation tests. The full suite covers mapping, transformation, XML/JSON/Data formats, nested repeats, archive execution and connector regressions beyond the fresh workload matrix. Skipped tests require external services or unavailable tools; they are not successful qualifications.

Studio contract tests now cover optional provider credentials and conditional JNDI settings for both JMS and EMS. The complete frontend script tests and production Studio build are rerun after documentation regeneration; results are recorded in the validation summary.

## Fix and compatibility

When both JMS credentials are blank, the bridge now calls `createConnection()` so the provider can use factory defaults. Previously it always passed two empty strings. Explicit credentials still use `createConnection(username, password)` unchanged. Studio and Run/Debug no longer reject a provider-default configuration that direct archives could accept. JNDI requires naming/factory settings rather than an unused direct URL; naming credentials are optional unless the provider requires them. No broker authentication policy is weakened by this change.

Regression coverage checks missing/empty credentials, explicit username/password, a blank password, password-only and whitespace-username cases. Runtime tests also verify required JNDI fields and configuration preservation. Live tests use a newly compiled Java bridge. Rebuild the normal Studio/sidecar Java bridge and restart Studio to use the fix in an existing installation.

An initial temporary broker launch omitted its JAAS configuration argument. That test-harness setup issue was corrected separately; the retained final results use the properly configured broker. Earlier failed attempts are not counted as passing runs.

## Limits and reproduction

Actual vendor EMS and hosted GCP were unavailable. Artemis proves the shared JMS/EMS activity code path, not EMS-provider compatibility or throughput. The Pub/Sub emulator does not prove cloud IAM, quotas, regional latency or service behavior. Kafka used a loopback single-node PLAINTEXT broker. TLS, failover, production security, vendor-specific settings and network topologies need their own qualification.

These fresh workloads do not repeat the prior 100,000-record/10-minute soak qualification and do not establish that memory leaks are impossible. Both Python archive formats were generated and executed on this Windows host with the required dependencies and provider drivers, rather than on a second clean machine. This work does not rebuild the Windows installer.

Use `scripts/kafka-local-qa.py`, `scripts/pubsub-emulator-qa.py`, `scripts/transform-stream-qa.py`, `scripts/data-stream-qa.py`, `scripts/data-group-qa.py` and `scripts/flow-throughput.py` for the corresponding tests. Use only dedicated temporary resources, matching Java/provider drivers, and a correctly configured local broker. The full backend command is `python -m unittest discover -s backend/tests -v` with the backend/dependency directories on `PYTHONPATH`. Studio checks are `node --test frontend/scripts/*.test.mjs` and `npm.cmd run build` in `frontend` after rebuilding help.

The sanitized machine-readable results are in `docs/validation/recent-activities-summary-2026-11-17.json`. Detailed local logs and generated test packages are under ignored `tmp/recent-*-20261117*`; they are test evidence, not deployable dependencies and do not need to be copied to another workspace.
