# Activity resource verification

This review extends the File/FTP/SFTP and HTTP/database checks to the remaining activity families. It checks resource ownership, failure cleanup, bounded caches, concurrency and generated Python behavior. Passing local checks does not establish production readiness for every external provider or workload.

## Fixes

- Pub/Sub service-account refresh closes its temporary Requests session on success and failure. Runtime publisher shutdown closes the transport even if publisher stop fails; a JMS shutdown failure does not skip other owned clients.
- Kafka transaction locks use at most 64 stripes rather than retaining every dynamic configuration fingerprint.
- AMQP receive and connection-test resources close on empty results, automatic acknowledgement, setup errors, receive errors and settlement errors. Manual acknowledgement transfers ownership to the returned settlement callback. Azure identity credentials created by MINA close with their client, including constructor failures. These changes are shared by generated Direct and Engine AMQP adapters.
- Direct Excel closes its read-only workbook in a finally block. The default start-row calculation no longer refers to an uninitialized header-row variable. Run, Debug and both generated archive entry points are covered with a real XLSX file.
- Java invocation waits for the killed process to exit on timeout before deleting its temporary compilation directory.
- Direct Pub/Sub pull closes its subscriber transport on success and failure.
- Direct Kafka and Pub/Sub retain at most 32 publisher clients each. Additional configurations use one-shot clients and close them after use. Overflow Pub/Sub publishes wait for provider confirmation before releasing the transport, even when the normal mode is buffered. Kafka startup failure or cancellation stops the partially initialized producer. Direct Kafka initialization locks use at most 64 stripes per event loop; application shutdown clears the registry. Cache keys contain hashes instead of serialized credentials.

## Coverage and limits

| Family | Evidence | Qualification still needed |
| --- | --- | --- |
| Mapper, transforms, DataWeave and six XML/JSON/data format activities | Full backend regressions, Run/Debug/archive parity cases, concurrent local soak | Representative customer schema sizes and sustained deployment workloads |
| Tasks, subtasks, groups, forks/joins, faults, mapping deletion and basic activities | Full backend suite, including 100-branch join and generated execution tests | Application-specific failure and recovery policies |
| Excel, Python and Java invocation | Real XLSX Run/Debug/archive regression, Java process timeout cleanup, Python/Excel local soak | User-supplied code behavior and large workbooks |
| Kafka and Pub/Sub | Publisher reuse, failure injection, bounded dynamic-configuration checks and generated adapter tests | Live broker/cloud soak, TLS/SASL/IAM, ordering, redelivery and failover |
| JMS/EMS and AMQP | Existing memory-mode/bridge regressions and adapter ownership tests with doubles | Live broker/provider libraries, settlement, transaction and failover qualification |
| SAP RFC/BAPI/IDoc | Existing parser, listener/session and generated-adapter regressions | Licensed live SAP connectivity, native-library memory and reconnect soak |
| SOAP, HTTP and REST | Complete backend regressions plus the earlier live local HTTP/HTTPS sustained verification | Remote provider and deployed ingress configuration |
| File, FTP, SFTP and databases | Earlier live local connector soaks plus full regression suite | Database vendors and remote servers unavailable in this environment |
| Timers, durable state and replay | Existing runtime/export and state regressions | Deployment scheduler behavior, retention sizing and recovery after infrastructure loss |

The Studio checks are automated designer/Help tests and backend execution paths. An interactive installed-app session and a fresh Windows installer are not part of this verification.

Python Invoke executes user code in a thread. Its timeout stops awaiting the result; Python cannot forcibly stop arbitrary code already running in that thread. Use a separately supervised worker for untrusted or potentially nonterminating code. This review does not claim that changing garbage-collector settings makes such code safe.

Mapping, parsing and Excel results are materialized in memory. Their memory requirement scales with payload/result size; this check uses bounded representative payloads and does not establish constant-memory processing for arbitrarily large documents. Buffered publisher delivery and unconfirmed manual acknowledgements must also be sized and monitored for the deployment.

## Reproducible checks

Use the backend environment with its optional connector dependencies and test-only psutil/openpyxl. No customer credentials are needed for the new resource tests.

```powershell
Set-Location <checkout>\backend
python -m unittest tests.test_remaining_activity_resources tests.test_publisher_reuse tests.test_raw_python tests.test_engine_export -v
Set-Location ..
python scripts/activity-resource-soak.py --seconds 600 --warmup 30 --output tmp/activity-resource-soak.json
Set-Location frontend
node --test tests/*.test.mjs
node --test scripts/documentation.test.mjs
npm.cmd run build
```

The eight-worker soak concurrently exercises Mapper/DataWeave, six format operations, source and Direct Excel, and source and Direct Python invocation. It records actual operation counts, errors, RSS, traced Python heap, OS handles and threads. It does not force garbage collection. Gates are at most 64 MiB RSS growth, 8 MiB Python heap growth, 8 additional handles, 2 additional threads, and a late RSS slope at most 0.5 MiB/minute. Sampling starts after warmup. A ten-minute local check is not a long-duration remote-provider soak.

Measured results are stored in `docs/validation/remaining-activities-soak-2026-11-14.json`. The final regression summary and changed-file list are in `docs/REMAINING_ACTIVITY_CHANGED_FILES.md`.
