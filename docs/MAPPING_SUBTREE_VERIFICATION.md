# Root-level mapping deletion verification

The shared Input editor and Mapper editor enable **Delete mapping** when the
selected target has either its own binding or descendant bindings. Deletion
clears that target subtree in the selected occurrence, including nested
duplicate occurrences. The schema stays available for remapping. Independent
sibling targets and sibling duplicate occurrences retain their bindings.

## Automated checks

- `frontend/tests/mapping-subtree-activities.test.mjs` evaluates every current
  activity-picker definition using the actual editor deletion action and saved
  configuration callback. This includes Call Sub Task, End, HTTP Send Response,
  Parse/Render activities and Mapper. Legacy Mapper aliases are covered too.
- `backend/tests/test_mapping_subtree_e2e.py` invokes Studio's TypeScript deletion
  helper through `frontend/tests/fixtures/clear-mapping-subtree.mjs`. It checks
  input resolution for every backend activity kind using the resulting saved
  mappings, including removal of nested repeating occurrence metadata.
- A parallel flow is saved with mappings, run, saved again after clearing, then
  executed through the Run and Debug API routes. The test checks the child task's
  input, child End output, parent End output and untouched sibling Mapper output.
- Both `python-direct` and `python-engine` archives are downloaded through the
  packaging API, extracted and executed in separate Python processes. Their
  outputs must match Run and Debug, including the untouched parallel branch.

Run from the repository root, with frontend dependencies and the backend test
environment installed:

```powershell
node --test frontend/tests/mapping-subtree-activities.test.mjs frontend/tests/mapper-loop-mappings.test.mjs frontend/tests/mapper-editing-regressions.test.mjs
Push-Location backend
python -m unittest tests.test_mapping_subtree_e2e tests.test_parallel_join tests.test_debug_input_capture tests.test_engine_export -v
Pop-Location
```

## Scope and defaults

These tests verify editor actions, persistence, mapping resolution and execution;
they do not contact every external database, broker or remote provider. Studio
editor checks execute the component actions rather than automate a desktop mouse.
Run and Debug checks use a newly started execution after saving the project.
An already running debugger retains its execution snapshot.

Deleting the last binding does not change an activity's normal defaults. In
particular, unmapped End and Call Sub Task boundaries continue to pass through
the preceding output. A regression test verifies that behavior without resolving
the deleted expression. To return a specific empty object, map that literal
explicitly rather than relying on an unmapped boundary.
