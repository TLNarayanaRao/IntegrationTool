# Kafka publishing performance

Studio and engine-backed exports reuse Kafka producers and run publishing on a dedicated four-thread executor. Long-running receivers, SAP/JCo calls, and other default-executor work therefore do not hold up Kafka enqueue operations. Producer cleanup closes this executor with the runtime. Direct Python exports reuse an asynchronous producer per connection/configuration and event loop.

Publish output includes `publishLatencyMs` plus:

- `publisherQueueMs` (Studio/engine): time waiting for a Kafka worker thread.
- `producerSetupMs`: producer lookup/creation time; direct Python includes initial broker connection setup and waiting for the creation lock.
- `sendAndWaitMs`: serialization/enqueue/delivery work after producer lookup; this is not a pure network-latency measurement.
- `producerReused` (direct Python): whether the existing asynchronous producer was reused.

With `waitForDelivery` enabled, completion includes broker acknowledgement. Kafka transactions also wait for delivery and commit in the Studio engine. With it disabled, `queued: true` and `deliveryConfirmed: false` indicate local queue acceptance, not confirmed broker delivery. This change does not alter acknowledgement settings or transaction semantics.

For remaining delays, compare the first publish with subsequent publishes using the same connection. High setup time on the first direct Python publish can involve metadata, DNS, TLS, or authentication. High send/wait time can include configured linger, queue backpressure, broker replication, retries, and network latency. Capture these timing fields alongside the effective producer settings and broker metrics before changing reliability options. Rebuild installed Studio and regenerate exported Python archives to use the updated implementation.

The automated tests cover thread-pool saturation, producer reuse, queued and acknowledged sends, and transaction initialization reuse. They do not establish throughput or latency against a real Kafka broker.
