# MINA documentation site and PDF

Open **Help > MINA Documentation** in Studio, or visit `/help/index.html` on the same host and port as Studio. No separate documentation service is required. Installed desktop Studio uses its existing local runtime address; do not assume a fixed port.

The documentation includes a searchable, expandable index and deep links to individual topics and tabs. Use **Download PDF** for the complete offline manual, or **Print topic** for the selected topic, including all its tabs. Light and dark display modes are supported.

## Coverage and accuracy

Activity Configuration, Input, Output, Advanced and Errors sections are generated from Studio's base contracts and documentation definitions. Tasks, groups, mapping, functions, shared connections, deployment, debugging, administration and security guides are included. Project-selected schemas, provider modes and JDBC parameters can change the fields shown in Studio: the reference does not substitute for those project-specific schemas. Provider prerequisites and production qualification still apply.

Only explicitly selected product source files and guides are read. The generator does not inspect project data, environment credentials or user payloads. Existing implementation limitations are documented, not claimed as implemented.

## Project Explorer and task canvas

New projects start with a Sub Task containing Start and End. Use a Starter Task when an external event, such as HTTP, a timer, or a message, starts the workflow. Use **Call Sub Task** to invoke reusable logic. Starter and Sub Task icons distinguish the two in Project Explorer.

Subtasks and **Call Sub Task** use the same process-network-and-bent-arrow symbol in Project Explorer, task tabs, creation menus, the activity picker, and the canvas. Starter tasks use the process network with a play symbol.

The canvas, activity palette, and activity picker share one activity icon catalog. Shared connections use the same protocol or vendor artwork in Project Explorer and connection creation menus. Imported legacy Mapper activities retain the Mapper symbol; an unrecognized activity uses a neutral process symbol instead of a Start or End icon.

Tasks, shared connections, and schemas belong to packages. Right-click their category or an existing package and choose **New Package** to create a top-level or nested folder. Choose the package when creating an item. **Default** is available for each category. Right-click an existing item and choose **Move to Package** to organize it without changing its references. Studio replaces spaces with hyphens in object names.

To rename a package, right-click the folder under **Tasks**, **Resources → Connections**, or **Schemas** and choose **Rename Package**. Its nested folders and items move with it, keeping task, connection, and schema references intact. Under **Packaging**, right-click the deployment artifact and choose **Rename Package** to update its name for future exports while keeping its version and settings. Save the project to keep these changes.

Task, connection, and schema names must be unique within the same package. Studio ignores case and treats spaces as hyphens when checking a name. You can reuse a name in a different package. For dynamic **Call Sub Task** routing, use the task ID or the qualified name (for example, `Orders/Validate`) if more than one subtask has the same name. **Validate Project** reports conflicts already present in older projects.

Package contents appear below their folder. If a name is shortened in a narrow Project Explorer, hover over it to see the full name or drag the pane divider to widen it.

When you first add a protocol activity or shared connection, Studio adds the relevant missing environment properties. Connection setup also offers those properties for binding. Review the generated defaults in the active environment before running the task.

Use **Magnify orchestrator** on the canvas and hover to see a 2× preview. Press Escape to turn it off. Select a transition to set its **Line color** or choose **Reset color** to restore the default. Close task tabs individually or use **Close All** to clear the canvas.

Use the **Theme** selector to change how Studio looks and feels. **Compact Workbench** uses a shorter ribbon and denser explorer rows. **Blueprint Board** uses a drafting grid and framed canvas activities. **Reading Room** uses larger labels, wider spacing, and a paper-like canvas. Existing themes are still available, and Studio remembers your choice.

The bottom-right **Runtime status** shows startup stages, current Studio operations, and the activities running in the active project. Click it for the designer and runtime details, including parallel activities and the latest detected slow UI operation on supported browsers. Startup progress counts completed stages; an animated bar means the operation has no reliable percentage. The Windows startup screen also shows the current stage before the designer is ready.

The footer and details use the same live runtime health check. If an older runtime does not provide activity-progress details, Studio reports that limitation separately. It does not mark a healthy runtime as unavailable.

The welcome screen shows packets moving along the integration routes. Use **Pause route animation** to stop them or **Play route animation** to start them. Until you choose a setting, the packets follow the Windows or browser reduced-motion preference. Studio remembers your choice.

## JDBC query and writes

Use `:name` parameters for Query, Update, and Insert, and map each value under **Input → parameters**. To execute multiple records together, enable **Batch update** and map **records**. An empty list writes zero rows. For **Insert if record does not exist**, map an INSERT statement to **InsertStatement** and provide the parameters used by both statements. MINA runs the INSERT only when the UPDATE affects zero rows. If you need an atomic upsert across concurrent executions, use your database's native upsert statement.

To page through a query, enable **Process result in subsets** and use a stable `ORDER BY`. Start with **Row offset** zero. Pass the previous result's **nextRowOffset** to the next call and stop when **lastSubset** is true. **Maximum rows** caps the total rows across those pages. Each call re-executes the query.

### PostgreSQL samples

1. Run [postgresql-setup.sql](/samples/postgresql-setup.sql) in a disposable PostgreSQL database. It creates `mina_demo.orders` and the `mina_demo.order_total` procedure.
2. In Studio **Samples**, open **PostgreSQL CRUD** or **PostgreSQL Procedure and Paging**. Set the JDBC URL, username, and password in the local environment. Use **Debug** to run the example Sub Task or run it by task ID in an exported Python archive.
3. CRUD upserts a demo row, updates it with a version guard, queries the JSONB field, and deletes that row. The other sample reads the first page and calls the procedure with an INOUT numeric argument.

PostgreSQL accepts libpq connection strings and JDBC-style PostgreSQL URLs. Configure **PostgreSQL TLS mode** and a trusted root certificate for verified TLS. A configured **Schema** becomes the search path. Use named `:parameter` bindings to avoid ambiguity with PostgreSQL's JSONB question-mark operator. Declare JSON or JSONB, ISO date/time, and decimal types for driver adaptation. To retain exact decimal digits from a mapped value, provide it as a string. Use JDBC Query with `SELECT` for PostgreSQL functions and Call Procedure for `CALL` operations. PostgreSQL statement timeout applies when configured on the activity.

## Updating the guide

From the repository root, install the documentation authoring dependencies into your chosen Python environment:

```powershell
python -m pip install -r scripts/documentation-requirements.txt
cd frontend
npm run docs:build
npm run docs:check
node --test scripts/documentation.test.mjs
```

If Python is not on PATH, set `MINA_DOCS_PYTHON` to its executable path before running `docs:build`. The Python dependencies are build-time only, not required to read the site or PDF.

`npm run build` checks that the generated documentation matches the selected source files. After changing those sources, regenerate the guide. The site and PDF are copied from `frontend/public/help` to `frontend/dist/help` by Vite and included in the normal Studio distribution. Rebuild the frontend and installer to deliver updated documentation to installed machines. Keep the whole help directory together when copying it for offline use; opening `index.html` directly also works without a server.

The guide is local to the Studio host. Making it reachable on a shared enterprise URL requires publishing these static assets through your approved web server and access controls; this change does not create a public internet endpoint.
