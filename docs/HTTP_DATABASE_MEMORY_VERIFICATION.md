# HTTP and database memory/concurrency verification

The 30-minute HTTP/database soak **passed both client and listener resource gates**:
**131,385 measured operations**, zero unexpected operation errors, and
2,348 intentional response-limit failures followed by successful requests.
These negative checks are expected; they are not hidden unexpected failures.

## Confirmed fixes

- HTTP per-destination permits previously retained a semaphore for every contacted
  destination. They now retain active requests and waiters only, removing an idle
  route without creating a second gate while another request still waits. A
  5,000-destination regression leaves no idle route history. Timeout and policy
  failures release references too.
- Scoped HTTP cleanup attempts all client closes and removes owned token entries
  even if one close fails, while preserving other scopes and reporting the first
  close failure. Shared clients still have their existing quota and connection limits.
- Reset/aborted HTTP connections now cancel keepalive timers unconditionally.
- The HTTP/1 status-line application wrapper no longer captures its owning
  protocol, releasing closed connections without waiting for cyclic GC.
- HTTP listener setup now releases warmed executors if TLS/configuration setup or
  worker warm-up fails. Warm-up failure aborts its barrier so waiting workers can exit.
- JSON schema validation now reuses a bounded set of draft-specific validator
  types. Each call still gets a fresh schema-bound instance, offline registry and
  isolated ContextVar budget; schemas and input values are not cached. This removes
  per-validation class creation and reduces collectable metadata/GC pressure.
- JDBC metadata browsing closes table and column cursors explicitly, including
  exceptions, before closing the owned session. Snowflake connection tests,
  metadata and operations likewise close their cursors and connections.
- Automatically generated Snowflake CSV files close and delete on writer, PUT,
  COPY/load and normal completion paths. User-supplied files are preserved.
- Direct JDBC archives now include the Snowflake helper even without a separate
  Snowflake activity. Both archive formats declare native driver prerequisites
  and Java/JDBC prerequisites from the configured mode. Driver/mode property
  choices are resolved together per environment, avoiding false native Oracle
  requirements created by mixing separate profiles. Native-only flows retain
  their existing behavior without a Java prerequisite.

The final activity implementations were unchanged throughout this reported soak.
Exporter fixes also passed separate archive tests. No dependency versions changed.

## Listener reference cycle and first-pass findings

The first 30-minute pass met client gates but showed listener RSS rising as high
as 243.3 MiB before falling back near its starting level. Inspection found
`protocol.app -> closure -> protocol` in MINA's status-line wrapper. Capturing
only the h11 connection removes that cycle. An additional inherited reset path
left a keepalive callback retaining a closed protocol. MINA now always cancels
that timer on disconnect, including errors. Its GC-disabled regression failed
before the fix and passed afterward. A regression with cyclic GC disabled
failed before the fix and passed afterward: the protocol now releases through
reference counting. A second pressure source was per-call validator class creation. Draft-specific
bounded type reuse removes that churn, retaining per-call schemas and budgets.
No forced server GC or global GC tuning was added.

A fresh full 30-minute pass below uses the final wrapper and adds separate
listener resource gates. Its listener peak RSS was
68.7 MiB; idle RSS changed
-4.94 MiB, handles
+3, and threads
+0. The first-pass samples are preserved in
`docs/validation/http-database-first-pass-2026-11-13.json`.

## Sustained workload and environment

Tested on Windows-10-10.0.26200-SP0, Python 3.11.9, HTTPX 0.28.1,
HTTPcore 1.0.9 and cryptography 46.0.0.
The production MINA listener implementation hosted separate HTTP and verified-TLS
HTTPS endpoints in another process. Outbound HTTP Request and OpenAPI-based REST
Invoke echoed and checked 64 KiB JSON payloads. SQLite WAL and a fresh disposable
TLS MySQL instance performed bound INSERT/SELECT/DELETE cycles and checked values.
No existing database or customer endpoint was used.

Warm-up was 120 seconds, followed by **1,800 measured seconds with 20 concurrent
workers**. The longer warm-up covers HTTP/TLS/parser setup and client-pool startup.
Every 25th HTTP/HTTPS/REST cycle first triggers a small response-byte limit, checks
its fault, then performs a normal successful request.

| Lane | Workers | Measured cycles | Operations | Unexpected errors incl. warm-up | Recent cycle p95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| HTTP | 4 | 21,383 | 22,240 | 0 | 0.282 |
| HTTPS | 4 | 18,726 | 19,477 | 0 | 0.359 |
| REST | 4 | 18,476 | 19,216 | 0 | 0.359 |
| SQLITE | 4 | 17,571 | 52,713 | 0 | 0.329 |
| MYSQL | 4 | 5,913 | 17,739 | 0 | 1.250 |

| Resource measurement | Observed |
| --- | ---: |
| Post-warm-up client RSS growth | 5.91 MiB |
| Client late-half RSS slope | 0.072 MiB/min |
| Retained tracked Python growth | -0.60 MiB |
| Quiescent handle change | -7 |
| Quiescent thread change | -2 |
| Client uncollectable objects | 0 |
| Listener process late-half RSS slope | 0.083 MiB/min |

Client gates were unchanged: zero unexpected errors; at most 64 MiB RSS growth,
8 MiB retained Python growth, 0.5 MiB/min late RSS slope, 20 additional quiescent
handles and 4 additional quiescent threads. Warmed idle-to-idle measurements and
periodic forced GC normalize samples. Production activities do not force GC after
each operation. Listener-process RSS, threads and handles are recorded separately;
the same RSS/slope/handle/thread bounds now gate that process too. Test processes
and disposable services are shut down after the run.

Cycle latency includes tracing, complete request/response/schema work and three
statements for a database cycle. It is not a per-statement throughput guarantee
or a controlled comparison against the earlier File/SFTP workload.

## Short-lived native thread checks

Separate real-service probes each created 2,600 fresh threads: verified HTTPS
with connection reuse disabled, and a new verified-TLS MySQL connection issuing
SELECT 1. Samples below compare post-warm-up active states. The probes then close
their owned clients. They did not reproduce the SFTP-style per-thread growth.

| Probe | Fresh threads/calls | Sampled RSS change | Sampled handle change | Errors |
| --- | ---: | ---: | ---: | ---: |
| HTTPS | 2,600 | -0.32 MiB | +0 | 0 |
| MYSQL | 2,600 | -0.18 MiB | +0 | 0 |

This does not repair the upstream cryptography raw-thread control documented in
the SFTP investigation, nor certify arbitrary native extensions or caller-created
cryptographic threads. It checks these actual HTTP/TLS and MySQL paths.

## Execution and archive checks

- The final backend suite ran 231 tests: **230 passed**, with the live
  PostgreSQL test explicitly skipped because no disposable DSN was configured.
- After the protocol fix, all **70 HTTP/resource tests** passed, including
  actual status-line/hosted API and archive regressions.
- The final suite includes **58 archive/resource tests**, including **17 focused
  resource/schema cases**. These include shared-gate concurrency, startup failure,
  CSV cleanup, preservation of user files, driver-mode preflight and executing the
  Snowflake JDBC helper in fresh Direct and Engine archive processes with an
  injected driver. Injected Snowflake checks are not live cloud qualification.
- Real HTTP/HTTPS, HTTP/REST response handling, SQLite and MySQL checks exercise
  Run, Debug, Direct Python, Engine Python and Direct zip execution. HTTP/2, HTTP/3,
  SSE/WebSocket and authentication policies have functional regressions in the
  suite; they are not the sustained profile above.
- All **150 frontend component tests** passed. Interactive GUI and a fresh
  Windows installer build were not part of this backend/resource change.

Oracle, SQL Server, PostgreSQL, DB2, Snowflake, Databricks and MariaDB were not
qualified against live providers here. Driver/adaptor and compiled Java bridge
regressions cannot substitute for their real authentication, procedures, paging,
failover and long-duration workloads. External OAuth/LDAP/proxy/Redis services
also require deployment-specific sustained qualification. Thirty local minutes
do not establish multi-day production behavior.

## Reproduce and operational limits

Use a source checkout and an isolated test Python with the backend dependencies,
psutil, cryptography and (for MySQL) PyMySQL. Set `MINA_TEST_MYSQLD` to an installed
mysqld executable to enable a fresh loopback datadir; otherwise that lane is omitted.
Run from the repository root:

```text
python scripts/http-database-soak.py --duration-seconds 1800 --warmup-seconds 120 --report tmp/http-db-soak.json
```

The harness returns nonzero if a client resource gate fails. Source fingerprints,
resource samples and native probe measurements are in
`docs/validation/http-database-memory-2026-11-13.json`.

Limits apply per request/query, not to the entire process. Large decoded objects,
Debug snapshots and concurrent result sets multiply peak memory. Set sensible
maximum rows/subset sizes, body limits and connection/thread limits; use file
streaming when the response contract allows it. Native TLS connections did not
need the SFTP-specific transport-worker workaround in these tests.

See [HTTP capabilities](HTTP_REST_CAPABILITIES.md),
[connector readiness](FILE_TRANSFER_DATABASE_READINESS.md) and
[Python archive modes](PYTHON_EXPORT.md).
