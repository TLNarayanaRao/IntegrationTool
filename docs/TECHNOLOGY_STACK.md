# Integration Fabric Technology Stack

## 1. Purpose and scope

Integration Fabric is a BusinessWorks-inspired integration design and execution platform. It separates the visual design experience from the runtime that executes integration applications. Projects are declarative `.ifproject` documents containing tasks, activities, mappings, transitions, shared resources, and environment properties.

This document records the technologies currently used in this repository, what each technology does, and the deployment implications for Windows, Linux, containers, and cloud environments.

## 2. Architecture at a glance

```text
Browser or Electron Studio
        |
        | HTTP/JSON REST API
        v
FastAPI application (Python runtime)
        |
        +-- workflow graph execution and fault policies
        +-- project persistence and package import/export
        +-- connector adapters
        +-- observability and Arizona-time logs
        |
        +-- Java JSON-lines bridge --> SAP JCo / JMS / JDBC vendor drivers
        +-- native Python connectors --> Kafka, Pub/Sub, AMQP, databases, files
        +-- HTTP clients/servers --> REST and SOAP integrations
```

The same activity model is used at design time and runtime. The web Studio uses the local FastAPI process, while the Windows product packages the Studio and a Python runtime sidecar together.

## 3. Frontend and visual designer

| Technology | Current use |
|---|---|
| React | Component-based Studio UI, home screen, project explorer, activity editor, mapper, schema editor, and runtime views |
| TypeScript | Static typing for the frontend application and activity/mapping models |
| Vite | Development server, production bundling, hashed JS/CSS assets, and static frontend output |
| React DOM | Browser and Electron renderer integration |
| lucide-react | UI icons |
| CSS | Themes, designer canvas, activity configuration panels, responsive layout, branding, animation, and error states |
| ESLint and TypeScript compiler | Frontend quality and compile checks |

The production frontend is written to `frontend/dist`. The FastAPI runtime serves that directory when running locally or from a packaged application. Vite produces content-hashed JS and CSS filenames. `index.html` is deliberately served with no-cache headers so it does not retain references to obsolete asset hashes.

## 4. Desktop application and packaging

| Technology | Current use |
|---|---|
| Electron | Windows desktop shell for the Studio |
| electron-builder | Windows application packaging |
| NSIS | Installer technology; supports per-machine installation, elevation, install-directory selection, Start Menu shortcut, and desktop shortcut |
| PyInstaller | Packages the Python runtime sidecar and its dependencies |
| PowerShell | Windows build orchestration and validation scripts |
| Java 17+ `javac` and `jlink` | Compiles the Java bridge and creates the bundled Java runtime |

The main desktop flow is:

1. Build the Vite frontend.
2. Validate that `index.html` references existing generated assets.
3. Compile the Java connector bridge.
4. Build the Python runtime sidecar with PyInstaller.
5. Run the packaged-runtime smoke test.
6. Package the Electron application with electron-builder and NSIS.

Relevant scripts are `scripts/build-studio.ps1`, `scripts/build-electron-sidecar.ps1`, `scripts/build-java-bridge.ps1`, and `scripts/build-windows.ps1`.

## 5. Backend runtime

| Technology | Current use |
|---|---|
| Python | Runtime orchestration, adapters, project services, mapping, logging, and packaging support |
| FastAPI 0.115.12 | REST API, listener endpoints, OpenAPI generation, request validation, and application lifecycle |
| Uvicorn 0.34.0 | ASGI server for local, server, and container execution |
| Pydantic 2.x | Project, task, activity, resource, configuration, and API payload validation |
| asyncio and threads | Concurrent listeners, non-blocking runtime work, bounded connector workers, and lifecycle shutdown |
| httpx 0.28.1 | HTTP client functionality and shared HTTP transport behavior |
| aiofiles | Asynchronous file operations where required |
| Python standard library | XML/JSON handling, CSV/flat data, FTP, paths, ZIP/TAR packaging, UUIDs, hashing, and process management |

The runtime executes connected activity graphs, resolves expressions and environment properties, applies transition and error policies, records activity lifecycle events, and exposes runtime/debug state through the API.

## 6. Project model and persistence

Projects are stored as JSON-backed files under the runtime data directory. The model separates:

- project metadata;
- task definitions;
- shared connection/resource definitions;
- environment properties;
- logs and runtime state.

The `.ifproject` format is portable and supports readable JSON import/export. The store includes compatibility handling for older SQLite-backed projects. Credentials should be supplied through environment-specific secrets or deployment configuration rather than committed into project files.

## 7. SAP integration

SAP support uses SAP's separately licensed Java Connector libraries, not a Python SAP package.

| Technology | Current use |
|---|---|
| SAP JCo (`sapjco3.jar` and native library) | RFC/BAPI calls, connection tests, client destinations, and RFC server listener support |
| SAP Java IDoc Class Library (`sapidoc3.jar`, when supplied) | Optional repository/XML validation and IDoc-related metadata support |
| Java 17 bridge | Isolates SAP JCo from the Python process and communicates using JSON lines |
| RFC server callbacks | Inbound IDoc and RFC/BAPI listener delivery |
| TID handling | Transactional IDoc delivery, confirmation, rollback, durable TID state, and duplicate protection |

The bridge supports separate operations for connection testing, RFC calls, IDoc validation, persistent SAP workers, and inbound listeners. The listener uses `IDOC_INBOUND_ASYNCHRONOUS` by default for IDoc delivery. SAP connection and listener properties include the application server or gateway settings, system number, client, user, password, program ID, repository destination, connection count, pending-event limit, timeout, transaction protocol, and TID store.

IDoc processing is metadata-driven. The runtime prefers SAP metadata, uses the fetched XSD when needed, preserves the control record (`EDI_DC40`), decodes fixed-width segment fields using their offsets and lengths, supports repeated segments according to occurrence metadata, and renders XML/JSON without blindly treating every segment as `SDATA`.

SAP JCo and IDoc libraries must be obtained and licensed by the customer. They are not redistributed by this project.

## 8. Messaging and event connectors

| Technology | Current use |
|---|---|
| Apache Kafka via `confluent-kafka` | Kafka publish/receive operations, security configuration, and transactional producer/consumer behavior |
| `fastavro` | Avro payload encoding/decoding and schema-registry-oriented payload support |
| Google Cloud Pub/Sub client | Publish and subscription operations |
| Apache Qpid Proton | AMQP 1.0 broker operations |
| `azure-servicebus` | Azure Service Bus messaging |
| `azure-identity` | Azure OAuth and managed identity credentials |
| `pika` | RabbitMQ AMQP 0.9.1 operations |
| TIBCO EMS through Java/JMS bridge | EMS send, receive, queue, topic, request/reply, and acknowledgment patterns |
| Generic JMS through Java bridge | JMS-compatible provider operations where a provider JAR is supplied |

Listener implementations use bounded queues and background readers where needed. This prevents large messages or bursts from blocking connector stdout pipes and places backpressure on the upstream transport instead of allowing unlimited in-memory growth.

## 9. HTTP, REST, SOAP, and file connectivity

| Technology | Current use |
|---|---|
| FastAPI/ASGI | HTTP listeners and service endpoints |
| httpx | REST/HTTP client invocation |
| Python XML libraries | SOAP payload handling and XML parsing/rendering |
| `ftplib` / `FTP_TLS` | FTP and FTPS operations using the Python standard library |
| Paramiko 3.5.1 | SFTP operations |
| `aiofiles` | Asynchronous local file activity support |
| ZIP/TAR standard-library modules | Project/package import and export |

Bundled file operations include read, write, list, poll, copy, rename, delete, and related filesystem actions. REST and SOAP activities support listener/service and request/reply patterns through the shared runtime.

## 10. Database and analytics connectivity

The runtime supports SQLite for local/design-time behavior and vendor drivers for external deployments.

| Technology | Current use |
|---|---|
| Python `sqlite3` | Local persistence and design-time database behavior |
| `psycopg` | PostgreSQL |
| PyMySQL | MySQL and MariaDB |
| `oracledb` | Oracle Database |
| `pyodbc` | SQL Server and other ODBC data sources |
| `ibm-db` | IBM Db2 and its bundled CLI driver |
| Snowflake Connector for Python | Snowflake SQL/runtime operations and key-pair authentication support |
| Databricks SQL Connector | Databricks SQL warehouses and all-purpose compute |
| Databricks SDK | Databricks OAuth M2M credential provider |
| `openpyxl` | Excel `.xlsx` workbooks |
| `xlrd` | Legacy `.xls` workbook reads |

The Java bridge also has JDBC-oriented support for vendor JDBC JARs when a deployment uses the Java connector path. External database credentials and driver locations are deployment concerns and should be managed outside project source files.

## 11. Transformation, mapping, and data formats

The platform uses native Python implementations for:

- JSON parsing and rendering;
- XML parsing and rendering;
- XSD-informed schema structures;
- flat-file and CSV parsing/rendering;
- field mapping and mapping validation;
- DataWeave-inspired expression execution and script recommendations;
- environment/property expressions such as `${input...}`, `${last...}`, and `${properties...}` where enabled by the activity model.

The visual mapper is implemented in React/TypeScript, while execution and validation occur in the Python runtime. The runtime carries activity outputs, attributes, variables, and prior results through the graph context.

## 12. Observability, logging, and audit

| Technology/component | Current use |
|---|---|
| Structured JSON logs | Startup, lifecycle, connector, listener, activity, error, and audit records |
| `project_logging.py` | Per-project log files and log retrieval |
| Arizona timezone utilities | Default log timestamp behavior for `America/Phoenix` |
| OpenTelemetry API/SDK | Instrumentation registration and status reporting |
| OTLP HTTP exporter | Optional telemetry export when configured |
| Runtime state API | Live status, debug sessions, activity results, and diagnostic logs |

Logs include project/task/activity/session identifiers where available. SAP connector diagnostics include server initialization, provider registration, repository binding, TID mode, function-handler registration, server start, listening state, callback failures, and delivery acknowledgment outcomes. Payload logging is configurable because IDocs and other messages can contain sensitive or very large data.

## 13. Deployment technologies

| Technology | Current use |
|---|---|
| Docker | Linux/container runtime image; frontend is built in a Node stage and served by Python runtime image |
| Node 24 Alpine build stage | Container frontend build |
| Python 3.12 slim container | Container runtime base image |
| Kubernetes YAML | Namespace and runtime deployment manifests under `deploy/kubernetes` |
| Kubernetes Secrets | Recommended storage for connector credentials |
| Control Plane / Administrator package | Deployment-target management, package validation, lifecycle, access, security, and observability workflows |

The packaged runtime can run on-premises or in a cloud data plane. Connector-specific native libraries and vendor JARs must be available in the target environment. For SAP inbound IDocs, the SAP gateway must be able to reach the configured host, gateway service, and registered program ID. For multiple runtime replicas, use a shared durable TID store and coordinate program IDs according to the SAP landscape design.

## 14. Build and verification tools

The repository uses:

- `npm ci` or `npm install` for frontend dependencies;
- `tsc -b` for TypeScript compilation;
- `vite build` for production frontend bundles;
- `eslint` for frontend linting;
- `python -m py_compile` and `compileall` for Python syntax verification;
- `pytest` for backend tests when the test dependency is installed;
- `javac` for Java bridge compilation;
- `jlink` for the bundled Java runtime;
- PyInstaller for the runtime sidecar;
- packaged-runtime smoke tests before installer completion.

The build scripts validate generated frontend asset references before packaging. This prevents a deployment from containing an `index.html` that points to missing hashed JavaScript or CSS files.

## 15. Dependency and licensing notes

1. Pin production dependencies where the repository already specifies a version or range. Avoid upgrading dependencies solely because pip or npm reports a newer release.
2. SAP JCo, SAP IDoc libraries, JMS providers, JDBC drivers, and broker-specific libraries may have separate licenses and distribution restrictions.
3. Do not commit passwords, private keys, client secrets, SAP credentials, or broker credentials into `.ifproject` files or source control.
4. Keep native libraries matched to the target operating system, CPU architecture, Python ABI, Java version, and vendor driver version.
5. Rebuild the frontend, Java bridge, and packaged runtime together for a release so the desktop product does not mix artifacts from different builds.

## 16. Repository reference map

- Frontend: `frontend/src`, `frontend/package.json`, `frontend/vite.config.ts`
- Python runtime: `backend/app`
- Python dependencies: `backend/requirements.txt`, `backend/requirements-sap.txt`
- Java bridge: `java-bridge/src`
- Build scripts: `scripts/`
- Deployment manifests: `deploy/kubernetes/`
- Operational documentation: `docs/ADMINISTRATOR_GUIDE.md`, `docs/BUILDING_AND_DISTRIBUTION.md`, `docs/ENVIRONMENT_VARIABLES.md`, `docs/RUNTIME_LOGGING.md`, `docs/SAP_INTEGRATION.md`, and `docs/VENDOR_DRIVERS.md`
