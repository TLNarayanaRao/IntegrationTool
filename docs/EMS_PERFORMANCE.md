# EMS/JMS send timing under load

EMS/JMS sends in the Studio/engine runtime use a dedicated four-thread executor,
separate from blocking receivers, database calls, and other default-executor work.
This removes shared-executor starvation; it does not bypass broker confirmation,
change persistent delivery, or automatically retry a possibly delivered message.
Receives and request/reply retain their existing behavior.

Sends now reuse a persistent Java worker, connection, and session per resolved
connection configuration and execution scope. Each worker keeps up to 32 destination
producers. Sends are serialized on a session for JMS thread safety. At most eight
workers are cached; additional configurations use the existing one-shot path.
Workers idle for 60 seconds are eligible for cleanup (checked every 30 seconds).
Debug Stop closes only its execution scope's cached senders; application shutdown
closes all cached senders. Driver changes require restarting/rebuilding the runtime.

The first send (and the first send after idle eviction, failure, or a new session)
still incurs startup and authentication costs. A failed/uncertain send is never
automatically replayed; a subsequent send creates a new worker. Persistent delivery,
priority, expiry, headers, and message properties retain their existing behavior.

Inspect the send activity output's `publishTiming`:

- `queueMs`: time waiting for an available send worker.
- `bridgeMs`: the Java bridge call. Cold calls include driver discovery, JVM launch,
  and connection establishment; warm calls reuse these resources.
- `totalMs`: total time across these stages.

A high queue time indicates sender capacity/concurrency pressure. A high bridge
time requires checking Java startup, vendor drivers, TLS/authentication, network,
and broker persistence/confirmation latency. The output also exposes `senderReused`
and `providerSendMs` (time inside the provider's synchronous send call). These help
distinguish cold setup from broker/network delay. A sub-300 ms latency target cannot
be guaranteed without qualification on the target EMS server and network.

Compare repeated sends using the same payload, destination, delivery mode, and
environment. Measure normal Run separately from debugger/test-bench wall time.
New raw Python archives that include this native Java bridge also use sender reuse;
the dedicated Studio/engine send executor is separate from raw connector scheduling.
Existing archives/installers must be rebuilt to include both the Python changes and
the newly compiled Java classes. Provider stress/soak testing still requires real EMS.
