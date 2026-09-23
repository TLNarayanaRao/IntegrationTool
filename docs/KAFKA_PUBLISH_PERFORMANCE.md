# Kafka send performance

Kafka already reuses producers, defaults to zero linger, and isolates publishing
from the shared executor used by blocking connectors. This update removes another
head-of-line blocking case: four confirmed sends could occupy all four Kafka
workers until their broker acknowledgements arrived, delaying new buffered sends.

Cached, non-transactional sends now enqueue on a Kafka worker and wait for their
own delivery report asynchronously. Short, nonblocking polls service callbacks;
the event loop yields between polls. Broker errors still fail the activity, and
confirmation timeouts explicitly warn that delivery may still occur. No automatic
resend is added, since a timeout does not prove the message was not delivered.

Transactions retain their serialized begin/commit/abort lifecycle. Uncached
one-shot producers retain their existing bounded flush behavior. Neither broker
acknowledgement settings nor the user's linger/batching settings are weakened.

## Applies to

- Studio Run and Debug using WorkflowRuntime.
- Newly generated engine-based Python packages containing that runtime.
- Direct Python exports already use an asynchronous aiokafka producer; they do
  not use this worker-pool confirmation path and are unchanged.

Rebuild/reinstall packaged Studio and regenerate/redeploy existing engine archives
to pick up the fix. Restart source-based runtime services after updating.

## Measuring

Inspect Kafka activity output:

- `publisherQueueMs`: delay before a send worker starts.
- `producerSetupMs`: producer lookup/creation cost.
- `sendAndWaitMs`: enqueue plus acknowledgement wait when requested.
- `publishLatencyMs`: total activity publishing time.
- `deliveryConfirmed`: whether a successful delivery report was received.

Buffered completion (`queued=true`, `deliveryConfirmed=false`) is not proof of
broker delivery. Enable `waitForDelivery` when measuring acknowledgement latency.
Compare warm sends separately from the first send, which can include connection,
authentication, and topic metadata setup. Broker load and network latency remain
external factors; this change does not guarantee sub-300 ms broker delivery.

Regression tests hold four acknowledgements pending and require a fifth buffered
send to enqueue within 300 ms, then verify that all confirmed sends complete only
after acknowledgements are released. Error, timeout, producer reuse, transaction,
default-executor saturation, debug, and engine-export tests also pass. These are
simulated connector tests, not a live Kafka throughput certification.

Callback behavior follows the [Confluent Python producer API](https://docs.confluent.io/platform/current/clients/confluent-kafka-python/html/index.html): delivery callbacks are serviced by poll/flush.
