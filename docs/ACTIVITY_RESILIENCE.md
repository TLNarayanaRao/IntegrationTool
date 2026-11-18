# Activity circuit breakers

Use **Activity → Advanced → Activity circuit breaker** on an outbound database,
messaging, file-transfer or SAP activity to give a failing dependency time to
recover. The policy starts disabled. HTTP, REST and SOAP keep their existing
transport settings. Listener, reply and settlement activities keep their normal
execution paths.

1. Enable the breaker and set the threshold and recovery delay. The defaults are
   five failures and 30 seconds.
2. Optionally enter fault types, codes or exception class names to count. A
   blank filter counts all ordinary failures. Use observed connector fault names
   when business or validation errors should leave the breaker unchanged.
3. Add an Error transition or select a Catch handler for `CircuitOpen`. The
   existing activity Errors policy can also return the fault or continue with the
   previous value. Run and Debug log when a breaker opens, blocks an attempt
   or closes after recovery. Debug follows the same task-level Catch handlers
   as Run. Enable **Pause on Error** to inspect the fault before the handler runs.

Each qualifying connector attempt counts, including activity retries. A
successful attempt clears the counter. The attempt that reaches the threshold
retains its original fault and stops retrying. Later calls raise `CircuitOpen`
before contacting the connector. After the recovery delay, one call probes the
dependency. A successful probe closes the circuit and a qualifying failure
starts another cooldown. Cancellation releases a probe slot. Calls already in
flight finish under their connector's own timeout and cannot close a circuit
that opened after they started.

State is in memory per runtime instance, project, execution mode, environment,
task and activity. Use separate activities for dependencies that must fail
independently. Debug and Run use independent circuits. Both Python archives
apply the same policy across task invocations within the life of the Python
process. Separate workers apply independent limits. Each registry bounds its
state to 4,096 circuits and reclaims inactive entries after one hour as needed.
If every slot is occupied, new protected activities raise
`CircuitBreakerCapacity` through the existing fault path.

See the [circuit breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
for the relationship between retries and recovery probes.
