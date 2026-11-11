# MINA Studio debugging

MINA Studio supports interactive debugging for ordinary tasks and continuous event starters.

## Execution and logs pane

Click **Run** or **Debug** to open **Execution / Debug** automatically in the lower pane, replacing the activity Configuration and Input tabs. The canvas remains visible above it. Run logs update while the task executes; debug logs update as you step or continue. Listener endpoints and generated outputs appear beside the logs.

The pane stays open while Debug is paused or a receiver is listening. It closes when execution completes, fails, or is stopped, restoring the selected activity tab. Its splitter resizes the lower pane; the expand and full-screen controls provide more space. To inspect retained logs after a session ends, choose **Window → Execution & Debug**.

Click an activity on the canvas to replace the execution pane with that activity's **Configuration** tab. Its **Input** and **Output** tabs remain available for inspecting the mappings and schemas. Debugging continues in its current running or paused state; activity selection does not stop or restart the session. Use **Execution Logs** on the debug ribbon, or **Window → Execution & Debug**, to return to the live logs.

When running Studio in a browser from a source checkout, the runtime serves `frontend/dist`. After updating the source, run `npm.cmd run build` from the `frontend` directory, then reload Studio in the browser (Ctrl+Shift+R in Firefox). A build written to a separate test output directory does not update the browser-served Studio. Short tasks can finish and close the pane immediately; use **Window → Execution & Debug** to review their retained logs, or set a breakpoint before debugging to keep the session paused.

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
