# EMS/JMS send timing under load

EMS/JMS sends in the Studio/engine runtime use a dedicated four-thread executor,
separate from blocking receivers, database calls, and other default-executor work.
This removes shared-executor starvation; it does not bypass broker confirmation,
change persistent delivery, or automatically retry a possibly delivered message.
Receives and request/reply retain their existing behavior.

Inspect the send activity output's `publishTiming`:

- `queueMs`: time waiting for an available send worker.
- `bridgeMs`: the Java bridge call, including driver discovery, JVM launch,
  connection establishment, broker send, and shutdown.
- `totalMs`: total time across these stages.

A high queue time indicates sender capacity/concurrency pressure. A high bridge
time requires checking Java startup, vendor drivers, TLS/authentication, network,
and broker persistence/confirmation latency. The current bridge starts a JVM and
connection per send; this change does not introduce persistent JMS pooling.

Compare repeated sends using the same payload, destination, delivery mode, and
environment. Measure normal Run separately from debugger/test-bench wall time.
The raw Python exporter has its own connector path and is not changed by this
runtime scheduling fix. Provider stress/soak testing still requires real EMS.
