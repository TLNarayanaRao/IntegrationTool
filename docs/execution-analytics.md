# Execution analytics

Open **Run → Execution Analytics**, **Window → Execution Analytics**, or the analytics icon in the Execution / Debug panel.

Select the current debug execution or a completed run. The window provides:

- Invocation and failure counts, summed activity duration and completed-run wall time.
- Recent-run duration graph and slowest-activity bar graph.
- Ordered invocation history, including repeated activity executions.
- Per-activity total, mean, minimum, maximum and nearest-rank P95 durations.
- Publisher timings for completed EMS/JMS and Pub/Sub sends, with a mean and sample count for each recorded phase.
- Search by activity, task or type; click an activity name to open its configuration.
- CSV timing summaries, JSON metadata and a standalone HTML graph report. Open the HTML report in a browser to print or save as PDF.

Reports omit activity inputs, outputs, credentials and configuration. Ordinary activity timings include connector waits and retries. When a listener hands an event to a workflow, its timing covers the handoff after the event becomes available. IDoc Listener timing also covers local SAP payload conversion. Idle listener waits are excluded.

**Total ms** adds the duration of every invocation. Use **Mean ms** and **P95 ms** to compare per-call latency. To measure throughput for a batch, divide its completed-record count by the elapsed time from the first submission through the final completion.

The **Publisher timings** section and the HTML and JSON reports show the worker queue and Java bridge time for EMS/JMS. The bridge time includes the wait for the shared JMS session and the provider send when those measurements are available. For Pub/Sub, the report shows worker queue and SDK enqueue time, plus provider confirmation wait when the activity waits for delivery. Compare the phases individually because some timings overlap.

In Run, a synchronous Call Sub Task includes its child execution time, so summed activity timings can overlap. Each spawned subtask appears as a separate entry in the **Execution** selector after it finishes. In Debug, the Call Sub Task row records call setup and the child activities have their own rows. Debug timings exclude time paused at breakpoints. Mocked steps record the time to apply the mock.

Execution history is held in memory by the running Studio backend and retains up to 100 runs. A backend restart clears this history; export reports to retain them. Older runs captured before this feature do not contain detailed timing records. These reports describe the Studio runtime and debugger; they do not aggregate remote Control Plane agents.

For a live or recently finished debug session, **Window → Debug Trace & Metrics** shows exact transition paths by workflow thread and reports both active-time and elapsed-time throughput. Use its JSON download to retain the trace and aggregate metrics together. See [Studio debugging](DEBUGGING.md#thread-paths-and-metrics).
