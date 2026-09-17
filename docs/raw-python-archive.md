# Raw Python archive and data-plane agent

Raw Python (`.pyifpkg`) is a separate deployment type. Existing JSON-based
`.ifpkg`, `.ear`, ZIP, and TAR packages are unchanged.

The archive contains `manifest.json` as Control Plane metadata and Python-only
source under `application/`. `main.py` is the entry point; `project.py` and
`tasks/` assemble typed Python task, group, resource, schema, and environment
models. No project, task, resource, or environment JSON and no Fabric DSL is
packaged. The Python engine modules bundled into the archive are the same
implementation used by Studio, preserving group scheduling, transaction
boundaries, exception handling, mapping, and connector behavior. This is not
a transpilation of every activity into an independent vendor-client function.

Run a task after extracting an archive into a Python environment with the
backend runtime dependencies installed:

```sh
python -m application.main --environment dev --task my-task --input '{"value":42}'
```

Notebook use:

```python
from application.main import run_task
result = await run_task("my-task", {"value": 42}, "dev")
```

## Connector dependencies

The bundled Python engine includes the code paths for SAP JCo, EMS/JMS,
Kafka, Pub/Sub, confirm, mapping, groups, and JDBC transactions. External
connectors still require actual services, Python client packages, and vendor
drivers. SAP/JCo, EMS/JMS, and Java JDBC modes require a Java runtime, bridge
classes, and licensed vendor JARs; SAP also needs its matching native library.
Set `FABRIC_DRIVER_HOME` or mount driver files under the default agent driver
directory. The Python agent image builds the Java bridge but does not
redistribute licensed vendor binaries.

## Agent deployment

For a Windows/Linux host, install `backend/requirements.txt` and
`administrator/requirements-agent.txt`. Set `FABRIC_CONTROL_PLANE_URL`,
`FABRIC_AGENT_KEY`, `FABRIC_DATA_PLANE_ID`, and `FABRIC_AGENT_MODE=local`, then
run `python -m administrator.agent.main` from the project root. A local Control
Plane can instead launch the archive directly; set `FABRIC_PYTHON_EXECUTABLE`
if its own Python lacks the backend runtime dependencies.

For Kubernetes, build `Dockerfile.python-agent`. Create the
`fabric-agent-credentials` Secret containing `control-plane-key`, set the
correct URL, image, data-plane ID, and namespace in
`deploy/kubernetes/python-agent.yaml`, and apply it. The agent reconciles
Raw Python deployments into per-application workloads, keeps its Control
Plane credential separate from application secrets, and reports replica
readiness. If SAP/JCo or EMS/JMS driver files are needed, set
`FABRIC_K8S_DRIVER_PVC` on the agent to mount a read-only driver volume into
the application pods.

The data plane needs a matching namespace and Integration Runtime capability.
The application pods need network access to Control Plane and the integration
systems. Production use of vendor connectors still requires real ECC/EMS/JMS
and database load, failover, and soak qualification; this code cannot certify
external systems or licensed drivers by itself.

## Current limits

The generated tasks use typed Python model constructors and the bundled Python
engine. They are not a one-to-one translation of every activity into a standalone
connector function. The Java bridge is still required for SAP JCo, EMS/JMS, and
Java JDBC modes. The existing EMS/JMS receive bridge is short-lived and closes
its session after each receive; client acknowledgement is therefore not a
durable, post-processing broker acknowledgement. Do not rely on that mode for
exactly-once processing until a persistent JMS session and broker-backed
confirm/rollback protocol are implemented and tested. Kubernetes reconciliation
has unit-level coverage but has not been validated against a live cluster here.
