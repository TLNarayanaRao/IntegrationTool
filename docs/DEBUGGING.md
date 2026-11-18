# MINA Studio debugging

MINA Studio supports interactive debugging for ordinary tasks and continuous event starters.

## Execution and logs pane

Click **Run** or **Debug** to open **Execution / Debug** automatically in the lower pane, replacing the activity Configuration and Input tabs. The canvas remains visible above it. Run logs update while the task executes; debug logs update as you step or continue. Listener endpoints and generated outputs appear beside the logs.

The pane stays open while Debug is paused or a receiver is listening. It closes when execution completes, fails, or is stopped, restoring the selected activity tab. Its splitter resizes the lower pane; the expand and full-screen controls provide more space. To inspect retained logs after a session ends, choose **Window → Execution & Debug**.

Click an activity on the canvas to replace the execution pane with that activity's **Configuration** tab. Its **Input** and **Output** tabs remain available for inspecting the mappings and schemas. Debugging continues in its current running or paused state; activity selection does not stop or restart the session. Use **Execution Logs** on the debug ribbon, or **Window → Execution & Debug**, to return to the live logs.

When running Studio in a browser from a source checkout, the runtime serves `frontend/dist`. After updating the source, run `npm.cmd run build` from the `frontend` directory, then reload Studio in the browser (Ctrl+Shift+R in Firefox). A build written to a separate test output directory does not update the browser-served Studio. Short tasks can finish and close the pane immediately; use **Window → Execution & Debug** to review their retained logs, or set a breakpoint before debugging to keep the session paused.

## Execution controls

- **Continue** runs until completion, an enabled breakpoint, a handled exception when pause-on-error is enabled, or a manual pause.
- **Ignore Breakpoints** continues for this command with breakpoints suppressed. Pause-on-error still applies and saved breakpoints remain enabled.
- **Pause** waits for the in-flight activity to finish and stops at the next activity boundary. **Pausing…** shows that the request is pending.
- **Step In** opens a Call Sub Task frame. **Step Over** executes through the call until the caller is ready to continue. **Step Out** resumes until the caller is reached. Breakpoints and pause-on-error can interrupt a call.
- **Run to Selected** targets the selected activity in its task. **Go to Current Activity** opens the activity the debugger is about to execute or is executing.
- **Break on Next Event** pauses after a live starter receives one event and before the downstream path executes. Continue to finish processing the delivery and re-arm the listener. For HTTP, a caller may time out while the debug session is paused.
- **Stop** cancels the debug driver and listener, rolls back open transaction groups, and releases owned native processes.

Choose **Run → Debug with Input** to enter a JSON object and start the selected task paused. This mode leaves live listeners unopened. Use the Activity Test Bench to preview the starter, supply mock output, or explicitly test the real activity. **Record thread paths** controls path detail for the session. Metrics are collected in either setting.

## Thread paths and metrics

Open **Thread Paths** or **Debug Metrics** from the ribbon. After completion or Stop, open **Window → Debug Trace & Metrics** to review the latest session in the current project.

- Each received event or one-shot flow has a job number. The trace shows its workflow threads for the entry flow, parallel branches, partial joins, and called subtasks. Select a thread to see its parent and its recorded path. Debug steps parallel branches in order and inspects Call Sub Task inline, including calls configured to spawn in Run. Worker TID identifies the thread that recorded the step. Connector internals and their worker threads have separate instrumentation.
- The trace lists visits, elapsed offsets, taken transitions by ID, error paths, loop/retry redirects, forks through their child threads, joins, and subtask calls and returns. Older Events pages through retained entries. Click an activity to open its canvas and Configuration. The canvas highlights recent transitions taken in the current task.
- Metrics include completed, failed and stopped jobs, last and longest job times, completed jobs per active and elapsed second, activity visits per active second, and activity totals, averages, minimums and maximums. An activity visit records failures, mocks and received events separately. Rates count workflow jobs and visits. A job may process a batch of business records.
- Active time includes activity and scheduler time while the debugger is driving the workflow. It excludes time paused, idle between listener events, and spent in standalone tests. The elapsed window runs from the first job start to the last job finish, or to the current time while a job is active. It includes pauses and delivery gaps inside that window. Subtask body time is attributed to the child activities, and the call row measures setup.
- **Download report (JSON)** includes retained thread summaries, events, and aggregate metrics. It includes activity and transition metadata. The report excludes captured payloads, variables and connector configuration.

Trace data is kept in the runtime session. `MINA_DEBUG_TRACE_LIMIT` controls recent event capacity and defaults to 5,000. Up to 500 thread summaries and 1,000 per-activity counters are retained per session. The pane reports when older details expire. Session totals continue accumulating. Export a report before the session expires or the runtime restarts.

## Debug Tools

Open **Debug Tools** from the debug bar to use the following features:

- Add an optional condition to any canvas breakpoint. Conditions use the same expression syntax as transitions, for example `${last.amount} > 100` or `contains(${last.status}, "FAIL")`.
- Enable or disable pause-on-error for handled error and retry paths.
- Add watch expressions such as `${input.orderId}`, `${last.customer.id}`, or `${vars.retryCount}`.
- Inspect the current input, previous output, process variables, process context, call stack, group iterations, and last exception.
- Evaluate an expression without modifying the running task.
- While paused, change a value under `input.*`, `last.*`, or `vars.*`. JSON values are typed; other input is stored as text.
- Set the Run-once timeout from 0.1 to 60 seconds in the Activity Test Bench. Preview and mock actions leave external connectors untouched.

Environment properties and connector credentials are intentionally excluded from the live-variable editor.

## Continuous starters

An EMS/JMS, Kafka, Pub/Sub, SAP, timer, or file listener displays **ready · waiting for event** until an event arrives. Breakpoints, watches, and pause-on-error remain active for every event. Stopping the session also stops the listener and prevents it from re-arming.
