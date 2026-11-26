# MINA Integration Libraries

Use the **File** menu or the ribbon’s **Project** section to publish reusable subtasks, connections,
and schemas, or to add a released version to an application.

## Create and export a library

1. In the authoring project, build callable **Sub Tasks** and define their input and output contracts. Put environment-specific values in project properties and reference those properties from the assets.
2. Choose **Create Integration Library**. Enter the display name, library ID, version, and an optional description.
3. Select the subtasks, connections, or schemas that other projects should see. MINA includes dependencies reached by fixed task and resource references as internal assets. It also includes selected Data Format assets and schemas reached through local XSD includes or relative JSON Schema references.
4. Select **Publish version**, then **Export .mlib**. Use a new three-part version number for revised content. Repeating publication of the same content is safe.

The archive contains the published asset definitions, declared setting types,
and a checksum. Project environment values are omitted. Use property references
for credentials and URLs that contain credentials.
Bindings used by recognized connector credential fields are created as password properties.
Move project-only custom function calls out of a subtask before publishing. Library publication reports them because those functions need a definition in the consuming project.

## Use one release in multiple projects

1. Choose **Import Integration Library**. Choose a release from the catalog or use **Import .mlib file**.
2. Enter a project alias and select **Add to project**. The alias qualifies the names in the task, connection, and schema selectors.
3. Set the generated `library.<alias>.<setting>` values under **Properties** in each environment you run or package. Each project owns its environment values, secret bindings, and connection instances.
4. Use **Call Sub Task** to map input to an exported task, choose an exported connection from the connector dropdown, or choose an exported schema in a compatible schema picker.
5. Map the task's public input and output schemas in **Call Sub Task**. Installed library tasks appear by name and version. Debug measures the call as one activity and shows the caller's input, result, and any failure at that boundary. Explicit messages published by the library's Log activities can appear in the application log.

Each project pins the exact version and checksum. To change a version, choose
the new release with the same alias, select **Review version change**, and
apply the change after reviewing the exported contracts and binding changes.
Compatible upgrades preserve existing references. To roll back, select the
previous version using the same process. References to a removed or private
export must be remapped before the change can be applied.

Use **Export .mlib** beside an installed release to export the exact pinned
version, including after reopening a workspace on a different Studio installation.

## Samples included in the catalog

| Library | Exports | Example |
| --- | --- | --- |
| Operations | WriteLog, HandleException, Fault.xsd | Pass a message and correlation ID to WriteLog. From a Catch branch, pass the code, message, and correlation ID to HandleException. Map its structured result and decide in the calling flow whether to route, retry, or rethrow. |
| Enterprise Connections | Database, Local-EMS | Bind `library.enterprise-connections.database-path` to a SQLite database path and select Database in a JDBC Query. Local-EMS uses an in-process queue for local examples. |

To try reuse, add both releases to two projects. Point each project's
`database-path` binding at a different SQLite file and call Operations from
both flows. The library versions stay the same while the JDBC results follow
each project's binding.

## Share through Control Plane or deployment packages

Open **Control Plane catalog** under **Use a library**. Enter the Control Plane
URL, credential, and team ID as applicable. Select a local release and choose
**Publish selected release** to share it with the team. Use **Load catalog**
and **Download to Studio** to import an authorized team's release. Add that
release to the project to create its version pin.

Studio workspace exports carry library IDs, versions, aliases, and checksums.
On a different Studio backend, install those exact `.mlib` releases before
opening the workspace. Older workspace exports with embedded releases still open.
Run and Debug resolve the implementation on the backend. Application packaging
includes the implementation for execution on the data plane.

### Protect files shared with application developers

For a managed Studio, set `MINA_LIBRARY_ARCHIVE_KEY` on the publishing and
consuming Studio backends to the same operator-managed, Base64-encoded 32-byte
key. Studio exports authenticated encrypted `.mlib` files in this mode. The
Control Plane library catalog transports them without the key. Keep the key in
the backend's secret configuration and share the archive with developers.
Studio can still import legacy `.mlib` files. Republish an existing Control Plane
version to replace its legacy archive with the encrypted form. Treat earlier
plaintext copies as source-bearing.

In managed mode, deploy projects that use libraries through the approved HTTPS
Control Plane. Set `MINA_LIBRARY_CONTROL_PLANE_URL` on Studio to that base URL.
Studio requires TLS verification and disables downloading the deployment archive
directly for those projects. Limit access to deployment packages and runtime
hosts to operators who can see their contents. Backend administrators and
workloads with unrestricted access to the backend filesystem can read the
installed implementation. On workstations without a managed key, library
files and deployment packages are portable source-bearing archives.

When a **Call Sub Task** target comes from a project property, fill in that
property for each packaged environment or set a fixed fallback. Packaging
includes the referenced subtasks for every selected profile.
