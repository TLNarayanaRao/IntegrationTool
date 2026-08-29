# Integration Fabric

Integration Fabric is a BusinessWorks-inspired integration studio. It combines a React visual designer, a FastAPI/Python execution runtime, and a Java extension worker contract.

## What is included

- BW-style three-pane designer: Project Explorer, orchestration canvas, and activity configuration panel.
- Lightweight JSON persistence under `backend/data/projects/<project-id>/`, with separate project, task, and shared-resource files. Existing SQLite projects are migrated automatically.
- Portable `.ifproject` import/export, readable JSON download, project close/open, and backend project deletion.
- Midnight, Aurora, Graphite, and Arctic design themes with glass-style configuration dialogs.
- Expandable environment property files with BW-style primitive data types, application renaming, and a vertically resizable/collapsible activity palette.
- Metadata-driven activity editors: Configuration, Input mapping, Output schema, and Errors/fault policy for every bundled operation.
- Runnable activity packs: File, FTP/FTPS, SFTP, HTTP listener/client/response, REST receiver/invoke, SOAP service/request-reply, JDBC, XML, JSON, flat data, Transform, Log, Kafka publish, Java extension, Start, and End.
- Environment-aware properties and conditional/error transitions.
- Inbound services are exposed at `/api/listeners/{project-id}/{configured-path}` and select properties with the `environment` query parameter.
- REST API with OpenAPI documentation at `/docs`.
- Desktop mode for Windows using PyInstaller and an NSIS installer script.
- Container and Kubernetes manifests for a Python runtime deployment.
- Java 17 extension SDK sample for custom activity implementations.

## Quick start

```bash
cd frontend && npm install && npm run build
cd ../backend && python -m venv .venv
.venv\\Scripts\\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787`. For development, run `npm run dev` in `frontend`; it proxies API calls to the backend.

SFTP uses Paramiko. FTP and FTPS use the Python standard library. Listener, REST, and SOAP HTTP transports share the FastAPI/httpx runtime.

## Windows installer

The preferred Windows desktop build is now the Electron Studio installer:

```powershell
cd frontend
npm ci
npm run desktop:installer
```

The complete Studio, Administrator, Linux, Windows, and deployment-package instructions are in [docs/BUILDING_AND_DISTRIBUTION.md](docs/BUILDING_AND_DISTRIBUTION.md).

## Kubernetes runtime

```bash
docker build -t integration-fabric:0.1.0 .
kubectl apply -f deploy/kubernetes/
```

Configure connector credentials with Kubernetes Secrets; do not put them in project definitions.

## Architecture

The UI stores declarative task definitions. The Python runtime validates and executes the graph. Each project uses a compact `project.json`; tasks and shared connections are stored independently in `tasks/*.json` and `resources/*.json`. Java activities are invoked through a JSON-lines worker process, keeping custom Java logic isolated from the orchestrator.
