# Runtime logging

Studio records Run, Debug, listener, job, activity, transition, retry, exception, and application lifecycle events in the **Execution / Debug** panel. The disk button in that panel reloads saved records after a run or after Studio restarts.

Each environment properties file contains the user-configurable property:

`runtime.logDirectory`

Set it independently in `local.properties`, `dev.properties`, `qa.properties`, `pre.properties`, and `production.properties`. Run, Debug, listeners, and Stop use the selected runtime environment and write beneath that environment's configured directory. For example, setting the development value to `D:\IntegrationLogs\dev` produces:

`D:\IntegrationLogs\dev\<project-id>\application.log`

Relative values are resolved beneath the Fabric data directory. Environment variables and `~` are expanded. When the property is blank, each project has an isolated structured log at the default location:

`<Fabric data directory>/logs/<project-id>/application.log`

The active file automatically rolls at 10 MB. Four numbered archives are retained by default (`application.log.1` through `application.log.4`), so an individual file never grows without bound. Each line is UTF-8 JSON and includes the project, timestamp, level, message, and available run, correlation, task, activity, duration, and exception context.

Packaged desktop installations place the Fabric data directory under the Studio user-data location configured through `FABRIC_DATA_DIR`. Administrators may override logging without changing code:

- `FABRIC_RUNTIME_LOG_DIR`: process-wide fallback root when the active environment's `runtime.logDirectory` property is blank.
- `FABRIC_PROJECT_LOG_MAX_BYTES`: maximum bytes per active or archived file; default `10485760` (10 MB).
- `FABRIC_PROJECT_LOG_BACKUP_COUNT`: number of rolling archives; default `4`.

Payload bodies are written only when the activity's **Automatic payload logging** option is enabled. Passwords and secrets should never be deliberately mapped into log messages.
