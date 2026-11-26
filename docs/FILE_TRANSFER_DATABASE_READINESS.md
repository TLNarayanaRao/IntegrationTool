# File transfers, database operations, and Input XPath

## XPath in every activity Input editor

Open **Input → Functions → XPath functions** for any activity, including File,
FTP, SFTP, JDBC, Call Sub Task, and End. Choose XPath 1.0 or 2.0, select a
function, enter XPath arguments, and drag the prepared expression to a field.
Double-click a function to open help for that overload. The popup shows its
signature, sample arguments, any XML or project properties the example needs,
and the result MINA returns. Clock-dependent examples show a representative
result. You can also select a function and choose **Function help**. Select
**Close** or press Escape to return to the mapping editor. Help works before
the runtime loads.

Type a function prefix such as `flo`, `token`, or `xs:da` for suggestions.
Use arrow keys and Tab or Enter to select one; functions that need arguments
retain focus inside the inserted call. Namespace prefixes are included in
completion. Data references and quoted constants remain distinct from XPath.

Use `xpath1("expression")` or `xpath2("expression")`; unversioned `xpath` in
general activity inputs uses XPath 1.0. The source defaults to the previous
activity output: XML text or an object containing `xmlString`, `xml`, `content`,
or `body`. To select another source explicitly:

```text
xpath2("sum(/orders/order/@amount)", ${input.xmlString})
xpath2("tokenize('a,b,c', ',')")
xpath1("local-name(/*)")
```

Without an XML payload, context-free functions run against an empty `<input/>`
context. Supply explicit XML for path-based expressions; an explicit invalid XML
source raises an error.

Declare namespace prefixes in the XML document for namespace-qualified paths.
DataCompose's additional XML binding configuration remains available for DataCompose.
XPath sequences become lists; exact decimal results may be strings to retain
precision. Existing restrictions on XML size, external documents, DTDs and regex
execution apply to activity Inputs. Run, Debug and both Python formats use these
evaluators; exports include XML requirements when any activity uses XPath.

## Local File activities

Read, Write, List, Poll, Copy, Rename, Delete, Create Directory and File Checksum share an implementation in Studio
and both Python formats. File I/O runs off the Studio runtime event loop.
Paths must be nonempty; an empty path never selects the working directory.
Copy and Rename require a destination, reject the same file (including hard
links), reject overlapping directory trees, and check source existence before
replacing a destination.

Non-append Write and file Copy stage complete content in the destination directory
before publishing it. File Copy applies the selected attributes to the staged copy
before replacing the destination. Overwrite uses filesystem replacement. Exclusive
creation uses a no-overwrite rename on Windows and a hard link on Linux. A failed
publication preserves the existing destination and removes the temporary file.
Append retains normal append semantics and is not transactional.

Directory Copy completes a staged tree before replacing the destination.
Directory replacement retains the old tree as `.mina-backup-*` during publication
and restores it if publication fails. A process or machine crash between the two
renames can leave a backup that must be recovered manually. Failed backup cleanup
returns `backupPath` and `cleanupWarning`; do not delete a retained backup before
checking the published tree. Avoid competing writers to the same directory.
These are filesystem safeguards, not distributed transactions or a power-loss
durability guarantee.

Read supports GZIP with the same Compression selection used for Write. Its
**Maximum decompressed read bytes** Input applies while streaming decompression,
preventing an oversized compressed payload from being expanded entirely first.
Zero is unlimited. Select the correct encoding or Binary mode. Deleting a symbolic
link removes the link itself; filesystem-root deletion is rejected.

**File Checksum** hashes the stored bytes of a regular file with SHA-256 or
SHA-512. Map the file path and an optional maximum byte limit on Input. The
activity streams the bytes and returns `algorithm`, `checksum` and `bytesRead`.
**File Poller** reports `Created`, `Modified`, or `Deleted` on each file in a batch
so a flow can route different changes separately.
Use explicit **Rename File** or **Delete File** steps after successful processing
to archive or clean up polled files. The old Poller post-action settings never
executed. They no longer appear in Studio. Directory Copy copies the full tree.
The unused recursive checkbox has been removed from File Copy.

**Omit last-modified metadata** removes `lastModified` from activity results.
It leaves directory sort order and change detection intact. Existing projects
retain timestamps unless this new option is enabled.

**Create Directory** takes a mapped directory path and can create missing parent
directories. Enable **Allow an existing directory** for retries. The output
reports whether the activity created a new directory. An existing file still
causes an error. **Write File** in Binary mode accepts Base64 text or bytes.
If Binary content is omitted, incoming bytes can be written directly.
**File Exists** checks a mapped file or directory path and returns `exists`
and metadata when available. A missing path returns `false` with null metadata.
Permissions and other filesystem errors still fail the activity. Use the result
to branch on a missing file. The file may still change before a later activity
uses it.

## FTP, FTPS and SFTP

Use an FTP shared connection for FTP/FTPS and an SFTP shared connection for SSH
transfers. Get, Put, Directory, Change Directory and Delete support dynamic paths.
Binary Put accepts base64 text or bytes; Get returns `contentBase64` and `size`.
Select Binary for arbitrary binary payloads.

FTP connection options include Passive mode, Timeout, Use verified TLS (FTPS),
Implicit TLS, a trusted CA bundle/directory, and optional client certificate/key
files. FTPS verifies server identity, requires TLS 1.2 or later, and protects both
control and data channels. Explicit TLS normally uses port 21; implicit uses 990.
Plain FTP remains available but does not encrypt credentials or file data.
CA directories use the OpenSSL hashed-directory layout; use a CA bundle file
for an ordinary PEM bundle.

SFTP rejects unknown host keys by default. Supply a Known hosts file and password
or private-key authentication. Timeouts cover connection, banner, authentication,
channel opening and transfer I/O. Disabling host verification accepts an
unverified server identity.

Get exposes **Maximum download bytes** in Input: zero leaves downloads unlimited;
a positive integer stops a transfer that exceeds the limit. Set **Download directly
to local file** (`localPath`) to stream without assembling the payload in memory.
The file is staged locally and published only after a successful transfer; a size
limit or network failure preserves an existing destination. Set Overwrite and
Create directories explicitly. File mode returns `localPath` and `size`, with null
`content`/`contentBase64`. Without `localPath`, the activity returns in-memory data.

Put can stream a **Local file to upload** instead of inline content. **Publish
upload by remote rename** (`atomicUpload`) writes a unique sibling temporary file
before renaming it to the requested name. Failures attempt to remove that temporary
file. FTP rename overwrite semantics depend on the server. SFTP replacement with
Overwrite requires the server's POSIX rename extension; it fails without deleting
the destination when unsupported. A killed process or broken connection can leave
a `.mina-*.tmp` remote file for later cleanup. Remote publication does not guarantee
disk durability or exactly-once delivery. Design retries around idempotent names
and business acknowledgements.

Invalid operations, missing paths and remote-path control characters fail before
connecting. Connections close on authentication, transfer and cleanup failures.

## Database activities

Query, Insert, Update, Delete, Dynamic/Direct SQL, Truncate and Stored Procedure
operations depend on the selected driver's support. Use bound parameters for
values; do not concatenate untrusted data into SQL. Prepared parameter types are
applied before execution. Integer parameters reject fractional/nonfinite values;
Boolean parameters reject unrecognized text. Positional parameters and positional
batch records use the declared types as well as named parameter records.
For unnumbered `?` placeholders and object-shaped inputs, JDBC follows the
order of the prepared parameter declarations. Provide every declared parameter
or use an array if the input is already in statement order. Named placeholders
continue to bind by SQL name.
Declared decimal values retain decimal precision in native Oracle, SQL Server,
MySQL/MariaDB and Java JDBC bindings rather than passing through a binary float.

**JDBC Metadata** reads a shared connection's catalog and exposes the driver,
tables and column metadata as activity output. Map an optional schema override.
It uses its own connection outside a JDBC Transaction group. Native SQLite
supports the `main` schema. Catalog contents depend on the driver and credentials.
Give result columns unique SQL aliases. JDBC raises `DuplicatedFieldNameException`
when a result set contains repeated labels. Snowflake Query also rejects repeated
labels before returning rows. SQLite Truncate accepts a quoted or
schema-qualified table name and removes all rows from that table.
Snowflake Query translates positional question-mark parameters without changing
question marks in SQL string literals, quoted identifiers, or comments.

Batch writes roll back on error when the activity owns the transaction. A JDBC
Transaction group owns commit/rollback for its member operations. Paging, row
limits, INSERT RETURNING, empty-string handling, update-with-insert fallback,
and procedures depend on the provider. Boolean options supplied as `"false"`
are disabled. SQLite per-activity busy timeouts are restored on shared connections.

With **Fault on batch failure** enabled, Snowflake Insert runs its DML batches in
one transaction and attempts rollback when a batch fails. Table creation, if enabled,
is DDL and occurs before the insert transaction. With the setting disabled, the
activity continues and reports batch failures.
Oracle native call timeouts and SQL Server ODBC query timeouts are applied and
restored per activity. MySQL/MariaDB shared connections expose socket Read and
Write timeouts, defaulting to the connection timeout when blank; these are socket
wait bounds, not a server-side statement cancellation guarantee. Providing a
MySQL/MariaDB CA certificate enables certificate and hostname verification.

Stored Procedure configuration includes **Add procedure parameter**, datatype and
IN/OUT/INOUT direction. OUT-only parameters are excluded from required Input fields
and appear as typed `outParameters.<name>` outputs. MySQL/MariaDB retrieves OUT
values from the server after draining procedure results; native Oracle uses typed
driver variables; Oracle/SQL Server JDBC uses CallableStatement and registered OUT
parameters. PostgreSQL CALL returns its output row. Procedure names must be qualified
identifiers rather than SQL fragments. Parameter names must be unique identifiers.
Overriding transaction behavior requires a JDBC Transaction group; standalone
activities cannot report success while closing an uncommitted private transaction.

Connection probes use Oracle DUAL, DB2 VALUES, or SELECT 1 as appropriate.
**JDBC Health Check** exposes this probe as an activity. It returns `ok` and
`message` on success and raises an error the flow can catch when the connection
or probe fails. It opens its own connection outside JDBC Transaction groups.
On SQLite, a positive activity timeout now also interrupts long-running SQL.
The activity raises `ActivityTimedOutException` when its execution deadline
is reached and removes the deadline handler before reusing the connection.
MySQL/MariaDB metadata uses the selected database. Configure supported driver
versions, timeouts, verified TLS, least-privilege credentials and server-side
access rules. External driver JARs and certificates remain deployment inputs.

## Verification scope

### Memory and cancellation controls

File Read returns content in memory; set `maxReadBytes` or use Exclude file content
for metadata-only reads. In-memory FTP/SFTP Get also needs `maxDownloadBytes`.
For large transfers, set `localPath` so Get/Put streams through a local file.
Base64 output and decoded text require additional allocations when returned
in memory. Inline File Write/Put content is already part of the process payload;
use local-file streaming or File Copy for large file-to-file work.

File List/Poll and FTP/SFTP Directory accept `maxEntries`. A positive limit fails
the operation when exceeded, rather than silently truncating a polling snapshot.
Zero preserves unlimited legacy behavior. Simple filename patterns stream local
directory scanning; complex path-glob patterns use the platform glob implementation
and can allocate additional scan buffers. Recursive scans do not follow symbolic
links or Windows directory reparse points in the streaming path. Files that
disappear during a local listing are skipped.

Stop/Cancel signals background I/O at chunk and publication checkpoints in Studio
and both Python formats. A cancelled staged copy/download is not published and
its temporary file is removed. A blocked socket can still take up to its socket
timeout to return to a checkpoint. SFTP subsystem negotiation also has an explicit
deadline. Cancellation cannot undo an already completed rename/delete, an append,
or bytes already written by a non-atomic remote upload; filesystem primitives
already executing cannot be forcibly interrupted safely.

Owned read/transfer buffers and network/file handles are closed on success and
failure, including when exception tracebacks remain retained for debugging.
Automated checks cover a 32 MiB streamed download with under 2 MiB of tracked
Python allocations, repeated reads without retained payload growth, failure-buffer
closure, cancellation cleanup in portable archives, listing limits and a stalled
SFTP subsystem. These are bounded regression checks, not a whole-process RSS,
native-library leak or deployment-duration soak certification. Process inputs,
outputs and debug history intentionally retain data while their execution records
remain available. Configure concurrency and retention for the intended workload.

Completed/failed/stopped debug-session history is bounded to eight sessions by
default (`MINA_DEBUG_HISTORY_LIMIT`). Debug log buffers default to 10,000 entries
(`MINA_DEBUG_LOG_LIMIT`) and drop the oldest entries while recording
`logEntriesDropped` in the debug API. Set positive integer environment values on
the Studio backend to change these limits. Active sessions are never evicted by
the completed-session limit; stop sessions that are no longer needed. Count limits
are not byte quotas: large payloads still need the file/transfer limits above.

Automated tests exercise local files, actual loopback FTP/FTPS/SFTP transfers, binary
data, host-key rejection, failure cleanup, download limits, generic Input XPath,
SQLite CRUD/batch rollback and database adapter/probe behavior. Integration tests
cover Run, Debug, Direct Python, Engine Python and Direct Python zip execution.
Tests inject replacement failures and concurrent destination creation, enforce
decompression/download limits, verify trusted and untrusted FTPS certificates,
and compile the real Java bridge for CallableStatement behavior. Studio component
tests cover dynamic transfer/read controls, procedure editing, duplicate-name
warnings and typed OUT fields.

The opt-in MySQL fixture starts a new loopback-only server with a private datadir
and generated CA/server certificates. It checks real CRUD, positional batch
coercion and rollback, paging, procedures with OUT values, socket timeout and
transaction-group rollback, including Run, Debug and both Python formats. Existing
MySQL installations and their data are never used by this fixture.

These tests do not certify every production server, database release or network.
The PostgreSQL sample suite requires `MINA_TEST_POSTGRES_DSN` for a disposable
database and explicitly skips live tests when absent. Oracle, SQL Server, DB2,
MariaDB, Snowflake and Databricks require live services, drivers and credentials
to qualify production interoperability. Test TLS chains, procedures/OUT parameters,
isolation, large transfers, failure recovery and concurrency on the target systems.

Native JDBC sessions shared by parallel branches in one transaction serialize
statement execution, result fetching, commit, rollback and close on that session.
DB-API connections must not receive overlapping protocol requests. Separate
connections remain independent; use batches or a transaction group when reducing
connection handshakes matters. The session owns its lock, with no global registry
retaining closed sessions. Failure cleanup tests retain exception tracebacks to
check that sockets close before those tracebacks are released, then check that
session objects can be garbage collected.

JDBC metadata browsing explicitly closes the table and column cursors before
closing its connection, including failed browse requests. Snowflake query,
metadata and connection-test paths close their cursors as well as connections.
Automatically generated bulk-load CSV files are closed and removed after success,
writer failures and upload/load failures. A user-supplied `filePath` remains owned
by the user and is never removed by that cleanup.

The follow-up [HTTP/database resource verification](HTTP_DATABASE_MEMORY_VERIFICATION.md)
covers sustained SQLite and verified-TLS MySQL traffic, HTTP/HTTPS listeners and
outbound HTTP/REST calls. Other vendor adapters require their own live qualification.

### Concurrent and sustained resource checks

Run `scripts/connector-soak.py` from a source checkout with test-only `psutil`,
`pyftpdlib`, `pyOpenSSL`, Paramiko and PyMySQL available in the test Python
environment. These test tools are not added to shipped runtime requirements.
The optional `MINA_TEST_MYSQLD` executable enables a fresh loopback TLS MySQL
instance with a disposable datadir. The harness does not use existing databases.

```text
python scripts/connector-soak.py --duration-seconds 1800 --warmup-seconds 60 --report tmp/connector-soak-report.json
```

The workload uses 22 workers when MySQL is enabled: File 4, FTP 4, FTPS 2,
SFTP 4, SQLite 4 and MySQL 4. Transfers use 64 KiB payloads and verify checksums;
database cycles bind parameters and verify retrieved values. Servers run in a
separate process. Metrics include client/server RSS, client handles and threads,
tracked Python allocations, GC collection counts, uncollectable counts and cycle
latencies. Instrumented latencies include complete cycles and profiling overhead;
they are not single-operation throughput guarantees.

Warm-up and quiescent before/after measurements separate native library
initialization from retained handles. The harness checks operation errors, retained
Python allocations, RSS growth and its late-run slope, handles and threads. Forced
GC is used for measurement normalization; production activities do not force a
collection after every operation. RSS includes native libraries, allocator caches
and profiling overhead, so a flat Python heap alone cannot establish that native
memory is stable. See the recorded soak results for the tested environment and
any resource-growth findings and follow-up verification.

On Windows, SFTP uses a bounded set of persistent daemon transport workers through
Paramiko's `transport_factory`. A new authenticated SSH connection is still opened
and closed for every operation. Workers retain no completed connection/job target,
payload or credentials. This bounds the native per-thread cryptography state that
grew when every transport created a new thread. Host-key checks, algorithms,
authentication, socket waits and subsystem negotiation timeouts remain enabled.
Linux/macOS continue using the normal Paramiko transport implementation.

`MINA_SFTP_TRANSPORT_WORKERS` defaults to 32 and accepts 1–128. Workers start
lazily and remain idle between jobs; their count is intentionally bounded, rather
than returning to zero after every transfer. Once all are occupied, a new
connection waits up to its configured timeout, then raises an SFTP capacity timeout.
It does not close another connection to make room. Choose a limit appropriate to
the deployment's simultaneous transfers and set it before the first connection;
restart to change it. An invalid value is a configuration error, with no silent
fallback to unbounded threads. See the Windows SFTP memory verification report.

To isolate cryptography allocations from SSH, networking and MINA, run:

```text
python scripts/connector-native-memory.py --managed --report tmp/connector-native-memory.json
```

This uses fresh processes for empty threads, cryptographic work on one thread,
the same work on newly created/joined threads, and MINA's bounded worker path.
With `--managed`, the gate applies to the bounded worker result and the raw
upstream result remains in the report. Without it, the gate still diagnoses the
upstream new-thread behavior, which MINA's Windows SFTP path now avoids. It records RSS,
Python allocations, handles and GC information after warm-up. A failed native
growth gate remains a release-qualification failure even if functional tests pass.
Do not call global OpenSSL cleanup or trim the process working set to hide growth;
neither is a safe per-transfer resource fix.

AI-generated ordinary REST receivers use application methods, excluding CONNECT.
The listener rejects unsupported method names explicitly. Older configurations
containing unsupported methods show a warning and a **Remove unsupported methods**
action in Studio, preserving the supported selections. Successful CONNECT requires
tunnel semantics and is not implemented as an ordinary hosted API response.
See [HTTP CONNECT semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.6).

For test-only FTP coverage, install `pyftpdlib` in an isolated environment; it is
not a shipped runtime dependency. Run from `backend`:

```text
python -m unittest tests.test_input_xpath_and_connectors tests.test_transfer_network tests.test_amqp_jdbc_excel_command tests.test_product_hardening tests.test_snowflake tests.test_postgresql_examples
```

Additional qualification tests:

```text
python -m unittest tests.test_connector_production tests.test_jdbc_callable tests.test_mysql_live
```

Set `MINA_TEST_MYSQLD` to an installed `mysqld` executable to enable the disposable
MySQL tests. Without it, those tests explicitly skip. The test environment needs
PyMySQL and cryptography; FTPS tests additionally need test-only pyftpdlib and
pyOpenSSL. The JDBC harness requires `java` and `javac`. Rebuild the Java bridge
with the standard Studio build scripts when distributing the updated JDBC code.

References: [Python FTP/FTPS](https://docs.python.org/3/library/ftplib.html),
[Paramiko SFTP](https://docs.paramiko.org/en/stable/api/sftp.html),
[Paramiko SSH](https://docs.paramiko.org/en/stable/api/client.html), and
[Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
