# Windows SFTP native memory fix and verification

The Windows SFTP connection-churn issue is mitigated in MINA by bounded,
persistent SSH transport workers. The fresh 30-minute, 22-worker soak **passed
all original gates**, completing **217,489 measured operations with zero errors**.
The upstream raw-thread behavior still reproduces; the MINA SFTP path avoids it.

## Implementation and compatibility

Previously each SSH transport created a new thread. A network-free X25519 control
reproduced native memory growth on Windows despite stable Python allocations and
handles. Replacing cryptography with two newer versions did not fix that pattern.

MINA now supplies a transport class through Paramiko's documented
[transport_factory extension point](https://docs.paramiko.org/en/3.5/api/client.html#paramiko.client.SSHClient.connect).
The class runs the normal SSH protocol loop on a bounded set of lazy daemon
workers. Its start, completion and join behavior follows each individual transport.
Workers survive between connections; completed targets are cleared so they do not
retain transports, credentials, keys or payloads. Unexpected job termination
releases capacity without killing the persistent worker.

Each activity still opens, authenticates and closes a **fresh connection**.
Host-key verification, authentication methods, key exchange/cipher choices,
configured socket waits and the subsystem handshake deadline are preserved.
There is no authenticated connection cache, global OpenSSL cleanup, working-set
trimming, forced per-operation GC or native-symbol patch. Linux and macOS retain
their normal transport path. No runtime dependency versions were changed.

`MINA_SFTP_TRANSPORT_WORKERS` defaults to **32**, accepts **1–128**, and is read
when the Windows transport factory is first created. Set it before the first
connection and restart the runtime to change it. At capacity, an incoming
connection waits up to its configured timeout, then fails without closing other
sessions. An invalid setting fails explicitly. Persistent idle worker threads are
intentional and bounded; the factory is initialized once even during concurrent
first connections.

The shared helper is included by the existing Direct and Engine archive module
closures, so no exporter/runtime fork or deployment dependency was needed.

## Sustained verification

Tested on Windows-10-10.0.26200-SP0, Python 3.11.9, Paramiko 3.5.1 and cryptography 46.0.0.
Servers ran in a separate disposable loopback process. MySQL used a fresh datadir
and verified TLS; SQLite used WAL. FTP/FTPS and SFTP used real protocol servers,
with verified FTPS certificates and SFTP host keys. No customer services were used.

Warm-up: 60 seconds. Measured duration: 1,800 seconds. Payload: 64 KiB.
Gates and 22-worker counts were unchanged from the failed baseline.

| Lane | Workers | Measured cycles | Measured operations | Errors incl. warm-up | Recent cycle p95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| FILE | 4 | 10,108 | 40,432 | 0 | 0.640 |
| FTP | 4 | 9,164 | 27,492 | 0 | 0.734 |
| FTPS | 2 | 3,797 | 11,391 | 0 | 0.969 |
| SFTP | 4 | 5,407 | 16,221 | 0 | 1.360 |
| SQLITE | 4 | 27,021 | 81,063 | 0 | 0.141 |
| MYSQL | 4 | 13,630 | 40,890 | 0 | 0.438 |

| Resource metric | Before fix | After fix |
| --- | ---: | ---: |
| Post-warm-up client RSS growth | 56.47 MiB | 6.54 MiB |
| Late-half RSS slope | 1.67 MiB/min | 0.15 MiB/min |
| Retained tracked Python growth | 1.34 MiB | 1.30 MiB |
| Quiescent handle change | -7 | -7 |
| Quiescent thread change | -2 | -2 |
| Uncollectable objects | 0 | 0 |
| Resource gate outcome | failed | passed |

The gates remain: zero operation errors; at most 64 MiB RSS growth, 8 MiB retained
Python allocations, 0.5 MiB/min late RSS slope, 20 quiescent handles and 4
quiescent threads of growth. Measurements normalize GC and compare warmed idle
states. Instrumented cycle p95 includes multi-operation cycles and tracing;
it is not a throughput promise. The baseline and follow-up had different
background test loads, so latency differences are not a controlled benchmark.

An additional **10-minute untraced real-SFTP** diagnostic used two concurrent
workers against the disposable server and completed 5,521
upload/download/delete cycles without errors. Its late RSS slope was
0.110 MiB/min. This supports stability outside tracemalloc.
Server metrics are separate: the raw Paramiko test-server fixture is not MINA's
SFTP client and still uses the upstream thread-per-connection server path.

## Native controls and functional coverage

Each cryptography version was tested in fresh control processes: empty threads,
same-thread crypto, raw new-thread crypto and the MINA bounded-worker path.
Each case warms 500 iterations and measures 4,000. The raw failure remains
visible; `--managed` gates the mitigated path against the controls.

| cryptography | Raw new-thread RSS growth (MiB) | MINA bounded-worker growth (MiB) | Managed gate |
| --- | ---: | ---: | --- |
| 46.0.0 | 12.82 | -0.65 | passed |
| 46.0.7 | 12.81 | -0.24 | passed |
| 50.0.2 | 25.25 | -0.13 | passed |

- All **252 main backend tests** passed, including real FTP/FTPS/SFTP transfers,
  Run, Debug, Direct Python, Engine Python and Direct Python zip execution;
  HTTP, database and compiled Java JDBC bridge regressions also passed.
- All **7 focused SFTP tests** passed: bounded capacity and recovery after failure,
  concurrent factory lookup, closed-transport collection, capacity timeout without
  disturbing a live connection, invalid settings, encrypted RSA key authentication,
  incorrect-passphrase rejection, and parallel 2 MiB streamed payloads on distinct
  SSH servers with host-key isolation. Key-auth checks also execute in Run, Debug
  and both archive formats.
- Separate tests with **Paramiko 5.1.0** passed (7 network/lifecycle checks,
  6 key-auth/lifecycle checks, and the added multi-server streaming check). These
  used an isolated test directory; MINA's pinned package was not replaced.
- All **150 frontend component tests** passed. Interactive GUI validation and a
  fresh Windows installer build were not performed for this backend-only change.

A 30-minute local soak and 10-minute diagnostic do not certify every server,
Windows release or multi-day workload. Validate deployment OS, keys, host trust,
network failures, intended concurrency and large files on the target service.
The measured activity/helper source hashes are recorded in
`docs/validation/sftp-windows-memory-fixed-2026-11-13.json`.

## Reproduce

Use an isolated test Python with the test dependencies described in the connector
operational guide. Set `MINA_TEST_MYSQLD` to a mysqld executable to include the
fresh disposable MySQL lane. From the source repository root:

```text
python scripts/connector-soak.py --duration-seconds 1800 --warmup-seconds 60 --report tmp/sftp-fixed-soak.json
python scripts/connector-native-memory.py --managed --report tmp/sftp-fixed-native.json
```

The original raw-dependency diagnostic remains available by omitting `--managed`.
It may fail while the bounded MINA path passes; that is why both results are
recorded. See [the pre-fix baseline](CONNECTOR_SOAK_RESULTS.md),
[the operational guide](FILE_TRANSFER_DATABASE_READINESS.md) and
[the environment variable reference](ENVIRONMENT_VARIABLES.md).
