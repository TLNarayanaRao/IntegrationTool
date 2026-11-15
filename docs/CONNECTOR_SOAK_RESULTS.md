# Connector concurrency and memory verification — 2026-11-13

This is the **pre-fix baseline**. MINA's Windows SFTP implementation subsequently
changed to bounded persistent transport workers. See
[the follow-up fix and verification](SFTP_WINDOWS_MEMORY_FIX.md). The original
failed measurements below are preserved for comparison.

The 30-minute measured workload completed with **zero operation errors**, but
**failed the native-memory stability gate**. This is not a blanket production
certification. At the time of this baseline, the Windows SFTP dependency finding
below remained unresolved.

## Environment and workload

Windows Windows-10-10.0.26200-SP0; Python 3.11.9; Paramiko 3.5.1;
cryptography 46.0.0; pyftpdlib 2.2.0;
PyMySQL 1.2.4; psutil 7.2.2.
22 concurrent workers, 64 KiB payloads, 60-second warm-up followed by 1,800
measured seconds. FTP, verified FTPS and host-key-verified SFTP used disposable
loopback servers in another process. SQLite used WAL; MySQL used a fresh datadir
and verified TLS. No customer endpoints or databases were used.

| Lane | Workers | Measured cycles | Measured operations | Errors incl. warm-up | Recent cycle p95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| FILE | 4 | 9,768 | 39,072 | 0 | 0.781 |
| FTP | 4 | 8,873 | 26,619 | 0 | 0.875 |
| FTPS | 2 | 3,653 | 10,959 | 0 | 1.031 |
| SFTP | 4 | 5,195 | 15,585 | 0 | 1.531 |
| SQLITE | 4 | 26,537 | 79,611 | 0 | 0.141 |
| MYSQL | 4 | 13,181 | 39,543 | 0 | 0.531 |

Total measured operations: **211,389**. File cycles write/copy/read/list;
transfer cycles upload/download/delete; database cycles insert/select/delete.
Checksums and selected database values were verified. Each transfer operation
opens and closes a connection, deliberately stressing handshake and cleanup.
Latency measurements include tracing overhead and complete multi-operation
cycles. The bounded latency sample retains the most recent 4,096 cycles per lane.

## Memory and garbage collection

| Measurement | Observed |
| --- | ---: |
| Post-warm-up client RSS growth | 56.47 MiB |
| Late-half RSS slope | 1.67 MiB/min |
| Retained tracked Python growth | 1.34 MiB |
| Quiescent handle change | -7 |
| Quiescent thread change | -2 |
| Reported uncollectable objects | 0 |

Failed gates: Late RSS slope exceeds 0.5 MiB/minute.

GC was forced only for measurement normalization. Native RSS was not trimmed.
The gates are: zero errors, no more than 64 MiB RSS growth, 8 MiB retained Python
allocations, 0.5 MiB/min late RSS slope, 20 quiescent handles or 4 quiescent
threads of growth. An early short test exposed initialization effects; warm-up
and idle-to-idle resource comparisons were added before this full run. No gate
was relaxed to turn the native-memory failure into a pass.

## Isolated Windows dependency finding

A network-free reproducer performs the same X25519 key generation/exchange on
one thread or newly created/joined threads, with empty threads as a control.
Each case runs in a fresh process, warms 500 iterations, then measures 4,000.

| cryptography | Empty-thread RSS growth (MiB) | Same-thread crypto (MiB) | New-thread crypto (MiB) | Excess over controls (MiB) |
| --- | ---: | ---: | ---: | ---: |
| 46.0.0 | 0.11 | -0.09 | 13.28 | 13.17 |
| 46.0.7 | 0.14 | 0.09 | 13.23 | 13.09 |
| 50.0.2 | -0.09 | -0.13 | 25.68 | 25.77 |

Handles did not accumulate, and retained Python allocations were about 2 KiB per
case. A separate untraced SFTP test showed continuing RSS growth; removing the
subsystem handshake timer or selecting Python's malloc allocator did not remove
it. FTPS and MySQL isolation checks stabilized after initialization. These results
isolate a native allocation problem in the Windows cryptographic thread path;
they do not identify a particular C allocation or prove behavior on Linux.

The compatible patch and current cryptography releases were tested in temporary
directories only. Neither fixed the finding, so runtime dependency requirements
were not changed. No global OpenSSL cleanup, private native-symbol patch,
working-set trimming or security downgrade was introduced. OpenSSL documents
platform-dependent thread cleanup for static linking; this is relevant context,
not proof of the precise cause: [OpenSSL initialization and thread cleanup](https://docs.openssl.org/master/man3/OPENSSL_init_crypto/).

This baseline did not qualify high-churn, long-lived Windows SFTP workloads.
A fix or bounded integration mitigation must pass the controls and a fresh soak.
A multi-hour/overnight run on the deployment OS and real target servers is still
required for release qualification. A 30-minute local run does not certify all
server products or deployment durations.

## Product fixes and regression coverage

- Native JDBC connections shared by parallel transaction branches now serialize
  statement execution/fetching, commit, rollback and close using a lock owned by
  the session. Independent connections remain parallel. A real TLS MySQL test
  runs 24 concurrent inserts through eight workers sharing one session.
- SQLite and real MySQL failure tests check closed sessions/sockets while exception
  tracebacks remain retained, then verify session objects collect after releasing
  those tracebacks. No global connection or lock cache was introduced.
- The HTTP failure came from CONNECT in generated ordinary receiver defaults.
  AI receiver defaults now exclude it; listener configuration rejects unsupported
  methods explicitly. Studio displays legacy unsupported selections and provides
  a repair action that retains supported methods. Ordinary application methods
  remain tested; CONNECT tunnel handling is not implemented as a fake API reply.

The main backend suite passed 245 tests. An additional 26-test suite passed with
one live PostgreSQL test skipped because no disposable PostgreSQL DSN was supplied
(25 executed successfully), including real Java bridge compilation. A 10-test GC
and concurrency recheck passed. All 150 frontend tests passed, including method
repair. Run and Debug, Direct Python, Engine Python and Direct Python zip paths
were exercised by integration tests with real loopback FTP/FTPS/SFTP and MySQL.
Studio verification used automated component and API tests; this run did not
complete an interactive GUI verification.

Oracle, SQL Server, DB2, MariaDB, Snowflake and Databricks were not qualified
against live servers here. Adapter regressions cannot replace that qualification.

## Reproduce

From the repository root, use an isolated test Python with psutil, pyftpdlib,
pyOpenSSL, Paramiko, cryptography and PyMySQL available. Set `MINA_TEST_MYSQLD` to
an installed mysqld executable to include the disposable MySQL lane.

```text
python scripts/connector-soak.py --duration-seconds 1800 --warmup-seconds 60 --report tmp/connector-soak-report.json
python scripts/connector-native-memory.py --report tmp/connector-native-memory.json
```

Both tools return a nonzero exit code when a resource gate fails. See
the machine-readable measurements in `docs/validation/connector-soak-2026-11-13.json`
and [the operational guide](FILE_TRANSFER_DATABASE_READINESS.md). The recorded
source hashes identify the workload version measured; a later harness-only
change creates the tmp directory when a custom report path is used. Activity
implementations were unchanged throughout the measured run.
