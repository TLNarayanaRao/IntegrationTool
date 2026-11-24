# MINA Studio debugging

Use the workspace breadcrumb to reveal the current project, a package, or the
open task in Project Explorer. The **Navigate** ribbon group keeps up to 15
previous locations for the open project. **Back** and **Forward** return to
tasks, selected activities, packages, connections, and schemas. Use **Recent
locations** beside them to jump directly to a previous location or one still
available through Forward. The dropdown lists the newest steps first and
omits the current location and any deleted destinations. **Up** opens
the selected Call Sub Task target. If a task calls several subtasks, select the
call you want to follow. Connection and schema editors also have these history
controls in their headers.

Open **Project Search** from the **Navigate** ribbon, the **Edit** menu, or
with **Ctrl+Shift+F** (**Cmd+Shift+F** on macOS). Search by name, folder, or
activity type, and select a result to open it. For a task, connection, schema,
or property, choose **Find References** to see configured usages. You can
also right-click a task, connection, or schema in Project Explorer. For
property-driven targets, results show the matching environments.

Choose **Commands** in the menu bar or press **Ctrl+Shift+P**
(**Cmd+Shift+P** on macOS) to find actions such as Validate Project, Debug
with Input, or Execution Analytics. Use the arrow keys to select an action,
**Enter** to run it, and **Esc** to close the palette. Use the menu-bar button
if your browser reserves the shortcut. **F5** runs the open Starter Task and
**F6** starts debugging when the task editor is open and execution is idle.

Use **Window → Reopen Closed Task Tab** or run the same command from the
palette to bring back a task tab. With all tabs closed, the designer offers
to reopen the last one. Studio keeps up to 15 recently closed tabs in the
current project for the session.

In the Task Designer toolbar or the **View** menu, choose **Fit Task** to
bring the whole diagram into view, or **Fit Selection** to frame the
selected activities or transition. The zoom controls keep the center of the
current view in place. Click the zoom percentage to return to 100%.

MINA Studio supports interactive debugging for ordinary tasks and continuous event starters.

## Executable groups

Select activities and choose **Group selected**, or pick a type from the
activity picker's **Groups** list. **Setup** shows the options for the chosen
group type. **Activities** lets you search the membership list and review the
entry and next activities before saving. **Advanced** contains nesting, loop
limits, local variables, and fault handlers where applicable. **Cancel** leaves
an unsaved group off the canvas.

**Scope** and **JDBC transaction** accept local
variables and ordered fault handlers. A handler can continue at the group's
unconditional exit with a mapped result, or propagate the fault. Existing
activity error transitions take priority. Retry groups can restore their
entry payload and variables on each attempt. External writes can still repeat.

**For Each** and **Iterate** support batches, output accumulation, and optional
preservation of the incoming payload. **Parallel For Each** runs a bounded
number of isolated iterations and publishes the results in input order.

For **Scatter-Gather** or **First Successful**, connect one preceding activity
to two or more disjoint routes with unconditional transitions. Enclose those
route activities in the group and connect their exits to the same activity
outside it. Scatter-Gather waits for all routes. First Successful tries them
in incoming transition order until one succeeds. Pick First selects the
first eligible branch. Background Scope starts an independent job and passes
the main payload through. At its concurrency limit it waits for a slot first.

Debug steps over routed groups and shows their execution logs. Use the
engine-backed Python archive for routed groups, Pick First, and configured
scope variables or fault handlers. The direct Python archive supports plain
scopes, sequential batching, and isolated retries on qualifying graphs.
Critical sections coordinate within one runtime. JDBC transactions use one
connection. Scope-local event handlers and distributed transactions are
outside this group model.

## Review validation findings

Choose **Validate Task** or **Validate Project** on the ribbon to check the
design. Filter findings by severity or search by location, message, or
suggested fix. **Open** takes you to the affected activity, transition,
connection, schema, or project setting. Mapping findings can open the activity's
**Input** tab directly. Studio expands collapsed parents and focuses the
affected mapping. For a child supplied through a whole-object mapping, Studio
opens the closest visible target.

Use **Find target field** in Input to search the destination tree by label or
schema path. Results include their parent rows so you can tell similarly named
fields apart. Use **Expand all** or **Collapse all** to browse the complete
tree. Clear search to return to that tree.

Validation reports missing required Input fields by path, including named JDBC
parameters and required fields in the selected Mapper or task schema.
Configured values and valid whole-object mappings can supply these fields. An
optional object may be omitted. Once you map part of it, validation checks its
required children. The runtime checks the actual values returned by dynamic
expressions.

After editing, choose **Review Findings** from the ribbon or the **Run** menu
to recheck the same task or project with your search and severity filter still
applied. Use **Revalidate** to rerun the checks while the list is open.

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

Open **Execution Setup** from the ribbon or **Run** menu to choose a task and
environment for one execution. The workspace environment stays selected for
editing. The execution panel and saved-log controls use the launch
environment. **Readiness** reviews the selected task and its statically
referenced subtasks, shared connections, missing or empty environment
properties, and flow and mapping findings. Open a finding to edit it or open
a connection to run its connection test using the selected profile.

To test a Subtask by itself, open it and click **Run**, or choose **Run →
Test Subtask**. The setup shows the Start activity's selected input structure
and offers four input sources. **Start fields** shows editable controls based on
the input structure, including booleans and JSON editors for repeated values.
**Paste or edit JSON** accepts a complete payload. **Load JSON file** previews
a local fixture, with **Edit as JSON** available for changes. **No input**
sends an empty object. Choose **Validate input** to check the selected source
without running the flow. For an XSD-backed Start activity, **Paste or edit XML**
and **Load XML file** accept an XML document. Studio shows the expected root
and validates its namespace, root, and schema before running. The Subtask
receives the validated document as a JSON object keyed by the selected root,
with repeating elements represented as arrays. You can also supply that
structure through the JSON options. **Run Subtask
test** validates again before the first activity. The execution panel stays open
with selectable output and logs. If Start has no input schema, leave the input empty to
execute the task with an empty object. The Subtask uses the selected
environment and its activities run with their configured connections.

In **Run** mode, live receivers take input from their senders and schedules
take input from the timer. For a one-shot entry, paste or load a JSON object.
Quick Run starts with an empty input object. Choose **Run → Debug with Input**
to start a Starter Task or Subtask paused with a sample JSON object. The
paused launch leaves listeners unopened. Use the Activity Test Bench to
preview the starter, supply mock output, or explicitly test the real activity.
**Record thread paths** controls path detail for the session. Metrics are
collected in either setting.

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

### Generated input cases

In the Debug ribbon, open **Input Cases** and choose a task in the Test Bench.
**Generate and check cases** uses a Start JSON Schema or XSD, or the JSON
request contract of an HTTP or REST starter. It checks representative inputs,
supported boundaries, and invalid inputs such as missing required fields or
wrong types. Tasks without an applicable schema show an unchecked fixture.
Timer fixtures include a synthetic schedule event.

Choose a case to inspect its payload and validation result. **Load in Test
Bench** copies it into the activity test input. When paused at a plain Start,
**Use as paused task input** loads a passing case into the task. For a
supported event entry in an activity-testing session, **Mock starter and
step** feeds the fixture into the downstream flow. These actions are
separate from schema checks. Continuing a real Debug flow uses its configured
activities and connections.

**Download cases** saves a JSON suite with expected acceptance or rejection.
Use **Check saved cases** in a later debug session to check the same payloads
against the selected task's current schema and spot changed results.

Environment properties and connector credentials are intentionally excluded from the live-variable editor.

## Continuous starters

An EMS/JMS, Kafka, Pub/Sub, SAP, timer, or file listener displays **ready · waiting for event** until an event arrives. Breakpoints, watches, and pause-on-error remain active for every event. Stopping the session also stops the listener and prevents it from re-arming.
## Monitor Run and Debug logs

Open the execution panel to filter logs by severity or search messages and identifiers. Click a correlation ID to isolate that execution while a listener continues to receive events. Use **Open activity** on an entry with a matching task and activity to jump to its configuration.

The panel initially shows the latest 200 matching entries. **Show older matches** reveals more entries from the available log buffer. Scroll back or turn off **Following latest** to inspect earlier entries. Open **Payload** on a row to view captured data. **Export metadata** downloads timing and identifiers for all matches as NDJSON, omitting log messages and payloads.

Select **Load saved project logs** to inspect saved logs for the current execution environment. Use **Return to execution logs** to switch back to the latest Run or Debug output.
