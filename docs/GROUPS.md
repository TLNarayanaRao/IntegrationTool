# Executable activity groups

Integration Fabric groups are persisted execution boundaries, not drawing-only containers. A group owns a connected set of activities and can be nested through `parent_group_id`. Activities have one direct group owner; a parent group includes the activities of its child groups at runtime.

## Supported runtime semantics

| Group type | Runtime behavior |
|---|---|
| Scope / None | Runs the enclosed single-entry, single-exit graph once. |
| If | Evaluates `condition` before entry and skips the complete group when false. |
| While | Evaluates `condition` before the first and every following iteration. `maxIterations` prevents runaway execution. |
| Iterate / For Each | Resolves `source` or `collection`, exposes `itemVariable` and `indexVariable`, and runs once per item. |
| Repeat Until True | Runs once, evaluates `condition` at the end, and repeats until true. Legacy count-based definitions remain readable. |
| Repeat on Error Until True | Retries the complete group after an unhandled member fault while `stopCondition` is false. A true condition propagates the current fault without another attempt. `retryCount` is the mandatory runaway-safety boundary. |
| Critical Section | Acquires a runtime-wide named lock before entry and releases it on success, fault, or debugger stop. Concurrent jobs using the same lock wait. |
| JDBC Transaction | Opens one connection for the group, supplies it to every matching JDBC activity, commits only after successful exit, and rolls back on an escaping fault or stopped debugger. |

Group exceptions first follow an explicit member error transition. Otherwise Repeat on Error gets the nearest retry opportunity. An exhausted/unhandled error unwinds group resources and propagates to the Task Catch handler or caller.

## Editing and nesting

Select connected activities on the Task canvas and choose **Group selected**. The group frame is rendered behind its activities. Select its header to edit its name, type, membership, parent, condition/collection, retry settings, or JDBC resource. Moving selected activities updates the group frame automatically. Group definitions, membership, nesting, and configuration are saved in Task JSON and included in project/deployment archives.

## Data-driven group configuration

The group editor uses the same Data, Functions, Constants, and project-property browser as an activity Input tab. Conditions and collections can be dragged from initial Task input, any earlier activity output, a prior-iteration output from inside the group, environment properties, typed constants, built-in functions, or project functions.

- **If** evaluates its mapped boolean before entering the group.
- **While True** evaluates before the first iteration and again after each completed iteration.
- **Iterate / For Each** resolves the mapped collection once at group entry and runs exactly `count(collection)` times. The current member and one-based index are published through the configured item and index variables.
- **Repeat Until True** always runs once and evaluates the mapped boolean after the group body.
- **Repeat on Error Until True** publishes the current fault as `${context.error}` and `${vars.error}` before evaluating the stop condition. False restarts the entire group; true stops retrying and propagates the fault.
- **Critical Section** acquires its named lock before the first enclosed activity and retains ownership until that group execution completes, fails, or is stopped. Other jobs using the same named lock wait.

`maxIterations` and `retryCount` are safety boundaries, not substitutes for data conditions.

## Validation rules

- A group must resolve to exactly one graph entry and one graph exit.
- Direct membership is exclusive. Nest groups with `parent_group_id` instead of assigning an activity twice.
- Empty groups, missing members/parents, parent cycles, and missing group configuration fail validation.
- Starter/event, End, and Catch activities cannot be direct group members.
- A JDBC transaction group uses one JDBC resource. Python-native adapters retain one DB-API connection. SQL Server and Oracle Java-driver configurations retain one dedicated bridge worker and one physical JDBC connection for the complete group.
- Parallel success fan-out inside a group is rejected until deterministic join/cancellation semantics are qualified.

## Debugging

Step In, Step Over, Continue, and Stop use the same group boundary scheduler as Run. Debug responses include `currentGroupIds`, per-group `groupIterations`, and group IDs in each call-stack frame. Stopping or failing a debug session rolls back active JDBC transactions.

## Deployment schema

Project and deployment manifests now use format version 2 and advertise `features.groups = runtime-v1`. Each packaged Task JSON carries its `groups` array with membership, nesting, layout, and runtime configuration.

## Deliberately staged

`Pick First` remains visible only for backward compatibility and is disabled in the editor. Runtime validation rejects it with `GROUP_UNSUPPORTED`; it will not be represented as production-ready until concurrent branch cancellation, resource cleanup, and debugger behavior are qualified. Grouped parallel fan-out is likewise rejected explicitly rather than executed with misleading partial semantics.
