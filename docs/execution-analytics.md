# Execution analytics

Open **Run → Execution Analytics**, **View → Execution Analytics**, or the analytics icon in the Execution / Debug panel.

Select the current debug execution or a completed run. The window provides:

- Invocation and failure counts, summed activity duration and completed-run wall time.
- Recent-run duration graph and slowest-activity bar graph.
- Ordered invocation history, including repeated activity executions.
- Per-activity total, mean, minimum, maximum and nearest-rank P95 durations.
- Search by activity, task or type; click an activity name to open its configuration.
- CSV timing summaries, JSON metadata and a standalone HTML graph report. Open the HTML report in a browser to print or save as PDF.

Reports omit activity inputs, outputs, credentials and configuration. Timings include connector waits and retries. Subprocess durations include child execution, so summed activity times can overlap; they are not process wall time. Debug timings exclude time spent paused at breakpoints. Mocked debug steps measure the mock execution rather than a real connector call.

Execution history is held in memory by the running Studio backend and retains up to 100 runs. A backend restart clears this history; export reports to retain them. Older runs captured before this feature do not contain detailed timing records. These reports describe the Studio runtime and debugger; they do not aggregate remote Control Plane agents.
