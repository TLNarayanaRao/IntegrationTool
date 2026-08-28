# Integration Fabric

Integration Fabric is a BusinessWorks-inspired integration studio. It combines a React visual designer, a FastAPI/Python execution runtime, and a Java extension worker contract.

## What is included

- BW-style three-pane designer: Project Explorer, orchestration canvas, and activity configuration panel.
- Project and process persistence in SQLite.
- Runnable activities: Start, HTTP/REST, File, Transform, Log, Kafka publish (optional dependency), Java extension, and End.
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

## Windows installer

Run `scripts/build-windows.ps1` on Windows. It builds the React files, packages the Python runtime with PyInstaller, and creates an NSIS installer when NSIS is installed. The application opens in the system browser and is also usable as a local runtime API.

## Kubernetes runtime

```bash
docker build -t integration-fabric:0.1.0 .
kubectl apply -f deploy/kubernetes/
```

Configure connector credentials with Kubernetes Secrets; do not put them in project definitions.

## Architecture

The UI only stores declarative process definitions. The Python runtime validates and executes the graph. Java activities are invoked through a JSON-lines worker process, keeping custom Java logic isolated from the orchestrator.
