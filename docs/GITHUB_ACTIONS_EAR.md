# Build a MINA EAR with GitHub Actions and deploy it to Linux

A MINA EAR is a deployment archive that contains the integration definition and its selected environment profiles. The MINA runtime installed on the Linux data plane executes it. The pipeline builds one EAR from the Git revision, saves it with a SHA-256 checksum, and can deploy that same file through the Control Plane.

## Set up the pipeline

1. Follow the [Linux setup guide](LINUX_SETUP.md) to install the MINA runtime, register the Linux data plane and capability, and verify the Control Plane. The deployment job runs on a Linux runner that can reach the Control Plane URL. Use the label `mina-deploy` and restrict access to the runner to the trusted release repository. The runner needs Git, Bash, curl, Python 3, and standard Linux command-line utilities.
2. Commit a Studio-exported `.mpackage` or project JSON to Git, for example `integration/orders.mpackage`. Remove credentials and test payloads from the source before committing. Keep environment property names and references so the deployment can supply values. In Studio, validate the project and confirm its Starter Tasks and target profiles. Applications with protected Integration Libraries use the managed Studio deployment path.
3. Copy [the workflow template](../scripts/ci/mina-ear.workflow.yml) to `.github/workflows/mina-ear.yml` in the repository. Configure the `qa` and `production` GitHub environments to match your MINA profile names. Use a protected branch or tag for deployments. Configure environment approvals where your GitHub plan supports them. See [GitHub environment setup](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

| GitHub environment setting | Value |
| --- | --- |
| Variable `MINA_CONTROL_PLANE_URL` | HTTPS base URL reachable from the deployment runner |
| Variable `MINA_DATA_PLANE` | ID of the registered Linux data plane, or `localhost` if Control Plane runs the worker locally |
| Variable `MINA_CAPABILITY_ID` | Runtime capability ID registered for that data plane and namespace |
| Variable `MINA_NAMESPACE` | Target namespace registered in Control Plane |
| Variable `MINA_TEAM_ID` | Team ID when the Control Plane requires an explicit team |
| Secret `MINA_CONTROL_PLANE_KEY` | Credential authorized to upload, deploy, start, and read health for the target team |
| Secret `MINA_DEPLOYMENT_SECRETS_JSON` | JSON object keyed by the packaged secret names required by the app. Leave empty when the app has no deployment secrets. |

## Build and deploy

1. In **Actions → Build and deploy MINA EAR → Run workflow**, select the release ref, enter the project path, and choose the profile. Leave **deploy** off for the first run. Download the `mina-ear` artifact and confirm that the manifest, Starter Tasks, and environment match your intended release. The template versions packages using the workflow run ID and attempt.
2. Run again with **deploy** enabled when the release is authorized. The deployment job verifies the checksum, uploads the EAR, creates one deployment instance through the Control Plane, starts it, and waits for the Control Plane health endpoint. Review the deployment ID and logs.
3. Verify the integration itself with a safe request, message, or test file and confirm the expected result. Control Plane health indicates the worker state and does not prove business delivery.

Deploying a new version creates a separate deployment. For an existing listener on the same port or a consumer that must run as a singleton, schedule the cutover and stop the previous deployment before starting the replacement. Retain the previous EAR and configuration for rollback through the Control Plane.

To promote the same EAR across environments, build it with both profiles, retain the EAR and checksum, and deploy it separately to each registered target.

```bash
# From the MINA checkout, with backend requirements installed in Python 3.12.
python scripts/ci/build-ear.py integration/orders.mpackage \
  --environment qa --environment production --version 1.4.0 --output-dir dist/ear

# On an authorized Linux deployment runner with the environment settings above.
# Set MINA_SECRETS_FILE to a private JSON file if the app requires secrets.
bash scripts/linux/deploy-application.sh dist/ear/orders-1.4.0-on-prem.ear qa
```

Use the EAR path printed by the build command if the project artifact name differs. Repeat `--starter` with the desired task IDs to package a subset, including the Sub Tasks they call.

## Verify with disposable Linux QA

Run the workflow with **temporary_qa** enabled. Keep the project set to `scripts/ci/fixtures/ear-qa.json`, select **qa**, and leave **deploy** off. The QA job downloads the EAR from the build job and verifies its checksum on a fresh Ubuntu runner. It starts a loopback-only Control Plane and worker, deploys with the normal CI deployment script, and verifies the fixture's JSON response and HTTP 401 when credentials are absent. The job stops the worker and Control Plane afterward. It uses generated credentials and does not use your registered data plane or GitHub environment secrets. See [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

To exercise the same build and deployment commands on a temporary Linux host, use Python 3.12 with the backend and Administrator requirements installed. The workflow dependency step excludes the optional Db2 adapter for this fixture. Run from the MINA checkout.

```bash
qa_artifact=$(mktemp -d)
python scripts/ci/build-ear.py scripts/ci/fixtures/ear-qa.json \
  --environment qa --version 1.0.0 --output-dir "$qa_artifact"
(cd "$qa_artifact" && sha256sum -- *.ear > SHA256SUMS)
python scripts/ci/smoke-ear.py "$qa_artifact"
```

A successful smoke test confirms that a real packaged task ran and returned `{"result":"mina-ear-qa-ok"}`. It qualifies the packaging and deployment path with the synthetic flow. Test your actual application against its providers in its own QA environment.
