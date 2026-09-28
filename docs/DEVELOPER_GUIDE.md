# MINA developer guide and source map

Open Studio's installed documentation and select **Developer guide** in the tree,
or open `/help/index.html#developer-overview` on the Studio host. The **Developer
PDF** button downloads the separate source-maintenance manual. The product manual
remains separate.

The source map covers every palette activity, every group type and the built-in
function catalog, plus tasks, Run/Stop, continuous listeners, Debug/test bench,
Job Data, mapping, suggestions, drag-and-drop, persistence, logs and both Python
archive modes. Source paths are relative to the repository. Line numbers are
computed at documentation build time; use the accompanying symbol/search anchor
if you have a different checkout. No source file contents are served by the site.

## Read File: where to start

1. `frontend/src/main.tsx`: `packs` defines the File palette entry (`type=file`,
   `operation=read`). `addActivity` creates the saved canvas node.
2. `frontend/src/ActivityEditor.tsx`: `activityContract` defines the File tab
   fields; `FieldEditor` renders configuration and `InputEditor` stores mappings.
3. `backend/app/models.py`: `Activity.config` stores those values. Project saves
   go through `backend/app/main.py` to `backend/app/store.py`.
4. `backend/app/main.py`: the Run API selects the task and invokes the engine.
   `backend/app/debugger.py` invokes the same execution layer for stepping.
5. `backend/app/runtime.py`: `WorkflowRuntime.resolve_activity_config` resolves
   mappings; `WorkflowRuntime.execute` enters the `activity.type == 'file'`
   branch. After the explicit write/list/delete/rename/copy/poll branches, Read
   File uses `Path.read_text` or `Path.read_bytes`, or returns metadata only.
6. `backend/app/raw_python_support/activities.py`: `file_activity` is the separate
   direct-export implementation. `backend/app/raw_python.py` generates and selects
   the exported code. A change only to `runtime.py` can leave direct export behind.
7. Add a regression in `backend/tests/test_activity_packs.py` and exported-code
   tests in `test_raw_python.py` / `test_engine_export.py`. Check encoding, missing
   file, binary content, metadata-only reads and mapping/output compatibility.

## Maintenance workflow

Edit source, not `frontend/dist`, installed executable resources or generated
archive copies. For a new setting, update UI/defaults, persisted compatibility,
resolved inputs, engine behavior, direct-export behavior and tests together.
Use isolated infrastructure for connector tests; tests may write to external
systems. Changing labels must not break saved activity IDs or mapping references.

From an environment with project and documentation dependencies installed:

```text
cd backend
python -m unittest discover -s tests
cd ../frontend
npm run docs:build
node --test scripts/documentation.test.mjs
npm run build
```

The developer-map definitions are in
`frontend/scripts/developer-documentation.mjs`. Its references are checked during
generation, and covered source changes invalidate `docs:check`. Add a map for any
new activity family, update its tests, regenerate both manuals, then rebuild the
installer/deployment artifacts needed by your users. A source map is navigation
guidance, not proof that every exposed option is implemented or provider-tested.
