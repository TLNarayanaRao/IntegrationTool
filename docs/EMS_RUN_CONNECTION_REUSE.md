# EMS/JMS sender reuse in Run mode

Run previously included the unique job execution ID in the persistent sender
cache key. Each incoming event therefore opened another Java worker/EMS connection.
After eight cached configurations, additional jobs fell back to one-shot JVMs.
Debug used a stable session ID and did not normally encounter this problem.

The runtime now gives EMS/JMS an application-scoped sender identity, separate from
the job ID. Jobs keep unique IDs for logging and tracing. Subtasks and parallel
branches inherit their caller's sender scope; Debug retains its own session scope.
Different applications and runtime instances remain isolated. Connection settings
still participate in the cache key, so changed credentials/settings are not ignored.

Studio project Stop cancels execution and force-closes that application's senders.
Restart can establish a fresh sender. Idle eviction, bounded caching, serialized
JMS session access, and the existing no-replay-on-uncertain-send behavior remain.

The fix applies to Windows and Linux execution through WorkflowRuntime, including
new engine-based exports. Rebuild/reinstall Studio and regenerate/redeploy engine
archives to replace older bundled code. Direct Python connector exports use a
different connection path and are not modified by this fix.

Verification uses the actual Java bridge and a local test JMS provider: twelve
separate Run jobs retain one sender, application Stop is isolated, restart works,
and provider failures are not automatically replayed. Debug, scheduling, runtime,
and engine-export regression suites also pass. Real EMS throughput still requires
measurement against the target broker; no fixed delivery latency is guaranteed.

For diagnosis inspect `senderReused`, `providerSendMs`, and `publishTiming`
(`queueMs`, `bridgeMs`, `totalMs`) in send output. A healthy warm send should reuse
its sender. Upstream event rate, broker persistence, network latency, and payload
logging can still constrain end-to-end application throughput.
