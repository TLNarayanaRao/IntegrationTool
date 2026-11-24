# Deploy a MINA application in a container

Use a Linux container host with Docker and access to the package registries used by your build. Run the build commands from the MINA source checkout. Use a Kubernetes cluster and an image registry for the Kubernetes steps. The standalone application image runs your exported flow and writes runtime logs to stdout. Studio and Control Plane can run separately.

| What to deploy | Use |
| --- | --- |
| An application in Docker or your own Kubernetes manifests | Export a standard **MINA package (.mpkg)**, **direct Python**, or a **Python compatibility archive** from Studio, then build the application image below. |
| A Control Plane-managed Kubernetes application | Export either Python format with the **Cloud** target and deploy to a registered Kubernetes Python data plane. |
| Browser-based Studio | Build the root `Dockerfile`. This image serves Studio and its API on port 8787. |
| Standard `.mpkg` on a configured Linux host without containers | Follow the [Control Plane and Data Plane setup](LINUX_SETUP.md). |

The standard Cloud package includes templates for self-managed Kubernetes. For Control Plane-managed Kubernetes with the included Python agent, use a Python archive.

## 1. Export the application in Studio

1. Open your project and select **Validate Project**. Fix errors and test with the intended environment.
2. Open **Package** and select the Starter Tasks and environment profiles. Download the standard `.mpkg` to run the saved flow with the MINA engine in the runtime image. The two Python export options produce `.pympkg` files.
3. For HTTP or REST, configure the packaged listener to bind to `0.0.0.0`. Pick one port for the first smoke test and record the method and URI path. For event-driven flows, record the test destination and configure that environment's connector properties.
4. Move passwords into typed environment properties or supported shared-connection secret fields. Check `manifest.json` inside the archive for `secretKeys` or `secretKeysByEnvironment`.

## 2. Build the runtime and application images

Copy only the trusted Studio archive into a separate application build context. The example uses a project called `orders` and the `production` profile.

```bash
docker version
docker build --target runtime -f Dockerfile.python-agent -t mina-runtime:local .

mkdir -p /tmp/mina-orders-build
cp /path/to/orders.mpkg /tmp/mina-orders-build/application.mpkg
docker build -f deploy/Dockerfile.application \
  --build-arg MINA_RUNTIME_IMAGE=mina-runtime:local \
  --build-arg MINA_PACKAGE_FILE=application.mpkg \
  -t mina-orders:1.0.0 /tmp/mina-orders-build
```

For a Python archive, name the file `application.pympkg` and omit `MINA_PACKAGE_FILE`. The image validates the package layout and selects its worker automatically. Rebuild the runtime base before using the updated application Dockerfile.

The runtime stage includes Python, Java and the MINA Java bridge. Enable native Db2 dependencies with `--build-arg MINA_INSTALL_DB2=true` when building the runtime if the application needs them. Licensed jars and native libraries, database drivers installed at the OS level, custom CAs, and client certificates must be provisioned for the target Linux architecture. Mount vendor jars under `/opt/mina/drivers` and verify the actual connector before production.

For a direct Python image, verify the installed connector dependencies before starting it.

```bash
docker run --rm mina-orders:1.0.0 --environment production --check
```

Both Python archive formats can run a callable task once. For a standard `.mpkg`, start the packaged Starter Tasks as shown in step 3. Substitute the actual task ID and a safe fixture payload. Use a test profile for tasks with external side effects.

```bash
docker run --rm mina-orders:1.0.0 --environment qa \
  --task check-order --input '{"id":42}'
```

## 3. Start and verify a Docker deployment

For HTTP, the example maps port 8787 and forwards it on the host loopback interface. All three package formats can use `MINA_HTTP_HOST` and `MINA_HTTP_PORT` if a container needs to override its configured listener bind. Leave the port override unset when the application uses distinct listener ports. Published paths are the actual paths configured in the app.

```bash
docker run -d --init --name mina-orders \
  --mount type=volume,source=mina-orders-state,target=/var/lib/mina \
  -e MINA_HTTP_HOST=0.0.0.0 -e MINA_HTTP_PORT=8787 \
  -p 127.0.0.1:8787:8787 mina-orders:1.0.0 --environment production
docker logs --tail 100 mina-orders
curl -fsS http://127.0.0.1:8787/orders/health
docker stop mina-orders
```

Replace `/orders/health` with your actual test route. For a broker, SAP, file or timer starter, omit `-p` and the HTTP overrides. Submit a known test event through the real test connector and verify its expected output or acknowledgement. Keep one replica until routing, consumer groups, scheduler behaviour and duplicate handling are qualified for scaling. For finite workloads, use a one-shot container or a Kubernetes Job.

For secrets, create a JSON object outside the build context keyed by the exported secret names. Give container UID 10001 read access and mount it read-only at runtime. Restart the workload after rotating mounted secrets.

```bash
# Add these options to docker run, before the image name.
--mount type=bind,source=/secure/orders-secrets.json,target=/run/mina/secrets.json,readonly \
-e MINA_SECRET_FILE=/run/mina/secrets.json
```

The named volume preserves runtime state under `/var/lib/mina`. Give application file paths, state stores, and certificate paths explicit Linux mount points where needed. Retain the build, readiness and end-to-end test output for the target host. See [Docker container mounts](https://docs.docker.com/engine/containers/run/).

## 4. Deploy to Kubernetes

### Standalone application image

Tag and push the tested application image to your registry. Use that registry image in a one-replica Deployment with container arguments `["--environment", "production"]`. For HTTP, set the port in the Deployment and Service to the actual listener port. Use a startup and readiness probe against a route you verified in the running application. An event-only flow does not need an HTTP Service. Mount the JSON secret as a file and set `MINA_SECRET_FILE` to its container path. Use `kubectl rollout status deployment/mina-orders -n mina`, `kubectl logs deployment/mina-orders -n mina`, and a request or test event to verify it. See [Kubernetes startup and readiness probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/).

For a newly exported **Cloud** `.mpkg`, you can also build from the Dockerfile included with the package. Extract the archive to a clean directory and run the command from the extracted root.

```bash
docker build -f deployment/cloud/Dockerfile -t REGISTRY/mina-orders:1.0.0 .
docker push REGISTRY/mina-orders:1.0.0
```

Set that image in the generated `deployment.yaml` and use the generated `configmap.yaml`, `secret.yaml`, and `service.yaml` as applicable. For a multi-environment package use the manifests under `deployment/cloud/profiles/<environment>/`. Fill the `secrets.json` object in the Secret through your secret management process and apply the selected profile to your target namespace. For HTTP, match the generated Service port to the listener configured in the app. Start with one replica and apply the HPA only after qualifying scaling with the actual connector.

### Control Plane-managed application

1. Build the agent image with `docker build -f Dockerfile.python-agent -t REGISTRY/mina-python-agent:VERSION .` and push it to the registry. This uses the final `agent` stage.
2. Register the Kubernetes data plane with its namespaces in Control Plane. Set the matching data-plane ID, Control Plane URL and registry image in [the agent manifest](../deploy/kubernetes/python-agent.yaml). Set both the pod image and `MINA_PYTHON_RUNTIME_IMAGE`. Create the namespace and the `mina-agent-credentials` Secret containing the `control-plane-key` entry before applying the agent manifest.
3. Package with the **Cloud** target and a Python format. Upload it in Control Plane. Select the Kubernetes data plane, namespace, environment and capability, provide required secret values, then start the deployment.
4. The agent downloads the archive into the pod and creates the Deployment, Service and Secrets. For an HTTP application using the included agent, configure the listener for `0.0.0.0:8787`, which matches the agent's Service. Check pod rollout, logs and the actual app endpoint or its test event.

## Browser Studio image

```bash
docker build -t mina-studio:local .
docker run -d --name mina-studio \
  --mount type=volume,source=mina-studio-data,target=/app/backend/data \
  -p 127.0.0.1:8787:8787 mina-studio:local
curl -fsS http://127.0.0.1:8787/api/health
```

Open the published local port in a browser. Keep Studio bound to a trusted interface. Its `/api/health` endpoint checks the Studio service. Use the packaged application's own route or test event to validate a deployed integration.
