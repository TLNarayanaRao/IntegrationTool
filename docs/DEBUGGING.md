# MINA Studio debugging

MINA Studio supports interactive debugging for ordinary tasks and continuous event starters.

## Execution controls

- **Continue** runs until completion, an enabled breakpoint, a handled exception when pause-on-error is enabled, or a manual pause.
- **Step In**, **Step Over**, and **Step Out** navigate activities and Call Sub Task frames.
- **Run to selected** continues until the activity selected on the canvas is about to execute.
- **Stop** cancels the debug driver and listener, rolls back open transaction groups, and releases owned native processes.

## Debug Tools

Open **Debug Tools** from the debug bar to use the following features:

- Add an optional condition to any canvas breakpoint. Conditions use the same expression syntax as transitions, for example `${last.amount} > 100` or `contains(${last.status}, "FAIL")`.
- Enable or disable pause-on-error for handled error and retry paths.
- Add watch expressions such as `${input.orderId}`, `${last.customer.id}`, or `${vars.retryCount}`.
- Inspect the current input, previous output, process variables, process context, call stack, group iterations, and last exception.
- Evaluate an expression without modifying the running task.
- While paused, change a value under `input.*`, `last.*`, or `vars.*`. JSON values are typed; other input is stored as text.

Environment properties and connector credentials are intentionally excluded from the live-variable editor.

## Continuous starters

An EMS/JMS, Kafka, Pub/Sub, SAP, timer, or file listener displays **ready · waiting for event** until an event arrives. Breakpoints, watches, and pause-on-error remain active for every event. Stopping the session also stops the listener and prevents it from re-arming.
