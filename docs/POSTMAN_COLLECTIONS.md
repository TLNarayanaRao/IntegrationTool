# Integration Fabric Postman collections

These collections target the self-hosted Control Plane at `http://127.0.0.1:9080`. Import the five JSON collection files and `postman-environment.local.json`, then select the environment in Postman. Set `adminKey` to `FABRIC_ADMIN_API_KEY` when that variable is configured.

## Collections

- `postman-platform-management.collection.json`: health, session, overview, inventory, monitoring, observability, and audit.
- `postman-data-planes-management.collection.json`: list, create, status, modify, heartbeat, and delete data planes.
- `postman-capabilities-management.collection.json`: list, create, filter, modify, and delete capabilities.
- `postman-applications-management.collection.json`: package/application inventory, deployment, status, health, configuration, lifecycle, undeploy, delete, and logs. Lifecycle requests include `{}` sample JSON bodies; create and configuration requests include full sample payloads.
- `postman-environments-secrets-management.collection.json`: profile status/export, profile update, deployment secret status/update, and package deletion.

Create requests capture generated data-plane, capability, or deployment IDs into collection variables where applicable. Run the heartbeat request at least every 90 seconds; a production agent should send it every 30–60 seconds. Secret values are examples only and should be replaced with secure Postman variables or Vault-backed values; never commit real credentials.

For package deployment, upload a validated `.ifpkg` first, then set `packageArtifact`, `packageVersion`, `environment`, `dataPlaneId`, `capabilityId`, and `namespace` to matching values. Applications cannot be deleted while running; use **Stop deployment** or **Undeploy application** first, then use **Delete application**. Delete removes the deployment record and its stored secrets; it does not delete the source package.

Deployment/export archives include only environment properties referenced by the selected Starter Tasks, reachable Sub Tasks, shared resources, and property aliases, plus `runtime.logDirectory` when present. The editable Studio project export remains complete; it is not reduced by deployment packaging.
