# Activity debugging and testing

During an active debug session, a dedicated Debug ribbon appears underneath the
Studio ribbon. It provides Continue, Pause, Stop, Step In/Over/Out, Jump In/Out,
Run to Selected, Breakpoints, Watches, Variables, Evaluate, Job Data, Edit Payload,
Preview Inputs, Test Activity, and Mock Output. Data/tool buttons open the relevant
editor section; real tests and mocks still require explicit submission there.
Commands are enabled according to session state. The ribbon disappears when the
session completes, fails, or stops; it is not shown during ordinary Run mode.

Choose **Run → Start Activity Testing** to create a paused debug session and open
the test bench. Unlike ordinary Debug, this does not automatically run the flow
or start event listeners. The existing Debug Tools window also contains the bench.

Use the searchable process/activity tree on the left of the test bench. Expand a
process or subprocess and select its activity; enter the input in the right pane.
Each target retains its own input draft while the dialog remains open. Selecting
a Call Sub Task row selects the call activity itself; expanding its arrow reveals
the called subprocess and its activities. Nested calls can be expanded the same
way, and selecting a nested activity targets its owning subprocess. Search includes
nested activities. Circular references stop with a notice. Dynamic calls show a
configured fallback, if any, labelled as potentially different from the runtime
target; unresolved targets are not guessed.

Selecting
a process targets its unique entry activity (or Start); Run once still executes
only that entry activity, not the entire process. If the entry is ambiguous, select
an activity explicitly. Independent tests can target another process in the debug
project without moving the paused flow. Mock stepping is restricted to the current
paused process and activity.

Select an activity and enter a JSON payload (including
arrays, strings, numbers, or null), or choose raw text/XML. The test payload is
available as both `input` and `last` for this independent test. Earlier activity
outputs and environment properties remain available for mappings.

- **Preview inputs** resolves configuration and mappings without executing the activity.
- **Run once (real)** executes the selected activity without advancing the paused
  flow. Inspect resolved inputs, output, logs, duration, and failure details.
- **Use mock output & step** supplies the payload as the current paused activity's
  output, skips its actual connector execution, and follows its normal transitions.
  Use this to simulate a receiver or downstream dependency without contacting it.
- Optional **field overrides** are a JSON object keyed by the activity's configuration
  field names, such as `message` or `topic`. They are applied after mappings as
  literal values. Preview first to verify the inputs.
- Optional **assertions** use runtime conditions, for example `${last.count} > 0`.
  Results distinguish execution failures from assertion failures.

The variable editor accepts whole `input`, `last`, and `vars` replacements, as well
as nested paths such as `input.customer.id`. Replacing `input` does not also replace
`last`; edit each explicitly when needed. `vars` must remain an object.

## Safety and scope

Real tests use the configured connections and can publish, acknowledge, write,
or call external systems. Use test environments and credentials. They are not
an external-side-effect sandbox or an automatic rollback mechanism. Independent
tests do not inherit a paused group's database transaction or lock context; use
normal flow stepping to test those lifecycles.

Single-activity tests default to a ten-second timeout. A timeout cannot guarantee
cancellation of work already submitted to a provider or blocking vendor driver.
Mocks bypass the activity, not the surrounding group's execution semantics.
Input overrides apply to configuration-driven activity fields; special task or
interface mapping behavior still follows the activity's runtime implementation.

The most recent full result and the last 30 result summaries are retained for the
debug session. Test payloads and mock results do not modify or export into the
project. This bench complements breakpoints, watches, expression evaluation,
variable editing, and flow stepping; real-provider integration and load testing
still require the target infrastructure.
