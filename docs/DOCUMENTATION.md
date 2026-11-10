# MINA documentation site and PDF

Open **Help > MINA Documentation** in Studio, or visit `/help/index.html` on the same host and port as Studio. No separate documentation service is required. Installed desktop Studio uses its existing local runtime address; do not assume a fixed port.

The documentation includes a searchable, expandable index and deep links to individual topics and tabs. Use **Download PDF** for the complete offline manual, or **Print topic** for the selected topic, including all its tabs. Light and dark display modes are supported.

## Coverage and accuracy

Activity Configuration, Input, Output, Advanced and Errors sections are generated from Studio's base contracts and documentation definitions. Tasks, groups, mapping, functions, shared connections, deployment, debugging, administration and security guides are included. Project-selected schemas, provider modes and JDBC parameters can change the fields shown in Studio: the reference does not substitute for those project-specific schemas. Provider prerequisites and production qualification still apply.

Only explicitly selected product source files and guides are read. The generator does not inspect project data, environment credentials or user payloads. Existing implementation limitations are documented, not claimed as implemented.

## Project Explorer and task canvas

New projects start with a Sub Task containing Start and End. Use a Starter Task when an external event, such as HTTP, a timer, or a message, starts the workflow. Use **Call Sub Task** to invoke reusable logic. Starter and Sub Task icons distinguish the two in Project Explorer.

Tasks, shared connections, and schemas belong to packages. Right-click their category or an existing package and choose **New Package** to create a top-level or nested folder. Choose the package when creating an item. **Default** is available for each category. Right-click an existing item and choose **Move to Package** to organize it without changing its references. Studio replaces spaces with hyphens in object names.

Package contents appear below their folder. If a name is shortened in a narrow Project Explorer, hover over it to see the full name or drag the pane divider to widen it.

When you first add a protocol activity or shared connection, Studio adds the relevant missing environment properties. Connection setup also offers those properties for binding. Review the generated defaults in the active environment before running the task.

Use **Magnify orchestrator** on the canvas and hover to see a 2× preview. Press Escape to turn it off. Select a transition to set its **Line color** or choose **Reset color** to restore the default. Close task tabs individually or use **Close All** to clear the canvas.

Use the **Theme** selector to choose **Plain Classic**, **Plain Studio**, or another Studio appearance. The theme affects the Studio interface.

The welcome screen shows packets moving along the integration routes. Use **Pause route animation** to stop them or **Play route animation** to start them. Until you choose a setting, the packets follow the Windows or browser reduced-motion preference. Studio remembers your choice.

## JDBC query and writes

Use `:name` parameters for Query, Update, and Insert, and map each value under **Input → parameters**. To execute multiple records together, enable **Batch update** and map **records**. An empty list writes zero rows. For **Insert if record does not exist**, map an INSERT statement to **InsertStatement** and provide the parameters used by both statements. MINA runs the INSERT only when the UPDATE affects zero rows. If you need an atomic upsert across concurrent executions, use your database's native upsert statement.

To page through a query, enable **Process result in subsets** and use a stable `ORDER BY`. Start with **Row offset** zero. Pass the previous result's **nextRowOffset** to the next call and stop when **lastSubset** is true. **Maximum rows** caps the total rows across those pages. Each call re-executes the query.

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
