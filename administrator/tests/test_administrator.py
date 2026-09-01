import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from administrator.app import main


def package_bytes(*, unsafe=False, target="on-prem"):
    manifest = {
        "format": "integration-fabric-deployment", "formatVersion": 1,
        "artifact": "orders", "version": "1.2.3", "applicationName": "Orders",
        "target": target, "environments": ["dev", "production"],
        "secretKeysByEnvironment": {"dev": ["DB_PASSWORD"], "production": ["DB_PASSWORD", "API_KEY"]},
        "starterTaskIds": ["main"], "includedTaskIds": ["main", "shared"],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("application/project.json", json.dumps({"id": "orders"}))
        archive.writestr("application/tasks/main.json", json.dumps({"id": "main"}))
        archive.writestr("application/tasks/shared.json", json.dumps({"id": "shared"}))
        if unsafe:
            archive.writestr("../outside.txt", "unsafe")
    return output.getvalue()


class AdministratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        main.DATA_DIR = root
        main.PACKAGES_DIR, main.STAGING_DIR, main.LOGS_DIR = root / "packages", root / "staging", root / "logs"
        main.DEPLOYMENTS_FILE, main.PACKAGES_FILE = root / "deployments.json", root / "packages.json"
        main.MACHINES_FILE, main.SECRETS_FILE = root / "machines.json", root / "secrets.json"
        main.AUDIT_FILE, main.KEY_FILE = root / "audit.json", root / ".secret.key"
        main.CAPABILITIES_FILE, main.RESOURCES_FILE, main.PRINCIPALS_FILE = root / "capabilities.json", root / "resources.json", root / "principals.json"
        main.TEAMS_FILE, main.TOKENS_FILE = root / "teams.json", root / "access-tokens.json"
        main.API_KEY = ""
        main.RUNTIME_COMMAND = f'"{sys.executable}" -c "import time; time.sleep(60)"'
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        for deployment in main.read_json(main.DEPLOYMENTS_FILE, []):
            main.terminate_instances(deployment, force=True)
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def upload(self, body=None):
        return self.client.post("/api/packages", files={"file": ("orders.ifpkg", body or package_bytes(), "application/zip")})

    def test_package_deployment_secrets_lifecycle_and_audit(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        package = uploaded.json()
        self.assertEqual(package["packageId"], "orders:1.2.3")
        self.assertEqual(package["status"], "VALIDATED")
        self.assertEqual(len(package["sha256"]), 64)
        self.assertEqual(package["starterTaskIds"], ["main"])

        missing = self.client.post("/api/deployments", json={"packageId": "orders:1.2.3", "environment": "dev", "machine": "localhost", "instances": 1})
        self.assertEqual(missing.status_code, 422)
        created = self.client.post("/api/deployments", json={"packageId": "orders:1.2.3", "environment": "dev", "machine": "localhost", "instances": 1, "secrets": {"DB_PASSWORD": "do-not-return"}})
        self.assertEqual(created.status_code, 200, created.text)
        deployment_id = created.json()["id"]
        detail = self.client.get(f"/api/deployments/{deployment_id}").json()
        self.assertNotIn("do-not-return", json.dumps(detail))
        self.assertTrue(detail["secrets"][0]["configured"])

        started = self.client.post(f"/api/deployments/{deployment_id}/start")
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["state"], "RUNNING")
        self.assertGreater(started.json()["instances"][0]["pid"], 0)
        invalid = self.client.post(f"/api/deployments/{deployment_id}/start")
        self.assertEqual(invalid.status_code, 409)
        stopped = self.client.post(f"/api/deployments/{deployment_id}/stop")
        self.assertEqual(stopped.json()["state"], "STOPPED")
        undeployed = self.client.post(f"/api/deployments/{deployment_id}/undeploy")
        self.assertEqual(undeployed.json()["state"], "UNDEPLOYED")
        self.assertGreaterEqual(len(self.client.get("/api/audit").json()), 5)

    def test_rejects_unsafe_and_incomplete_packages(self):
        unsafe = self.upload(package_bytes(unsafe=True))
        self.assertEqual(unsafe.status_code, 400)
        self.assertIn("Unsafe package path", unsafe.json()["detail"])
        broken = io.BytesIO()
        with zipfile.ZipFile(broken, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"format": "integration-fabric-deployment", "formatVersion": 1}))
        response = self.upload(broken.getvalue())
        self.assertEqual(response.status_code, 400)

    def test_cloud_package_is_inventory_only(self):
        self.assertEqual(self.upload(package_bytes(target="cloud")).status_code, 200)
        response = self.client.post("/api/deployments", json={"packageId": "orders:1.2.3", "environment": "dev", "machine": "localhost", "instances": 1, "secrets": {"DB_PASSWORD": "x"}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Kubernetes", response.json()["detail"])

    def test_control_plane_data_planes_capabilities_resources_access_and_observability(self):
        overview = self.client.get("/api/control-plane/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(overview.json()["dataPlanes"]["running"], 1)
        self.assertEqual(self.client.get("/api/capabilities").json()[0]["type"], "integration-runtime")

        registered = self.client.post("/api/data-planes", json={"name":"Production Kubernetes", "type":"kubernetes", "host":"cluster.example", "region":"us-west", "namespaces":["integration"], "tags":["production"]})
        self.assertEqual(registered.status_code, 200, registered.text)
        plane_id = registered.json()["id"]
        heartbeat = self.client.post(f"/api/data-planes/{plane_id}/heartbeat", json={"cpuPercent":21, "memoryPercent":38, "agentVersion":"1.0.0"})
        self.assertEqual(heartbeat.json()["status"], "ONLINE")
        capability = self.client.post("/api/capabilities", json={"name":"Production Runtime", "type":"integration-runtime", "version":"1.0.0", "dataPlaneId":plane_id, "namespace":"integration"})
        self.assertEqual(capability.status_code, 200, capability.text)
        resource = self.client.post("/api/resources", json={"name":"Global telemetry", "type":"observability", "dataPlaneId":"*", "scope":"global", "configuration":{"metrics":"http://metrics"}})
        self.assertEqual(resource.status_code, 200, resource.text)
        principal = self.client.post("/api/access/principals", json={"name":"Integration Team", "type":"team", "permissions":[{"role":"Application Manager", "scope":"data-plane", "resourceId":plane_id}]})
        self.assertEqual(principal.status_code, 200, principal.text)
        observed = self.client.get(f"/api/observability?dataPlaneId={plane_id}").json()
        self.assertEqual(observed["dataPlanes"][0]["cpuPercent"], 21)
        self.assertEqual(self.client.get("/api/health").json()["component"], "integration-fabric-control-plane")

    def test_delivery_team_assets_are_namespace_and_api_isolated(self):
        plane = self.client.post("/api/data-planes", json={"id":"shared-cluster", "name":"Shared Cluster", "type":"kubernetes", "host":"cluster.example", "namespaces":["team-a", "team-b"]}).json()
        for namespace in ("team-a", "team-b"):
            capability = self.client.post("/api/capabilities", json={"name":f"Runtime {namespace}", "type":"integration-runtime", "dataPlaneId":plane["id"], "namespace":namespace})
            self.assertEqual(capability.status_code, 200, capability.text)
        team_a = self.client.post("/api/teams", json={"id":"delivery-a", "name":"Delivery A", "namespaceScopes":[{"dataPlaneId":plane["id"], "namespace":"team-a"}]}).json()
        team_b = self.client.post("/api/teams", json={"id":"delivery-b", "name":"Delivery B", "namespaceScopes":[{"dataPlaneId":plane["id"], "namespace":"team-b"}]}).json()
        duplicate = self.client.post("/api/teams", json={"id":"delivery-c", "name":"Delivery C", "namespaceScopes":[{"dataPlaneId":plane["id"], "namespace":"team-a"}]})
        self.assertEqual(duplicate.status_code, 409)
        token_a = self.client.post(f"/api/teams/{team_a['id']}/tokens", json={"name":"Team A pipeline"}).json()["token"]
        token_b = self.client.post(f"/api/teams/{team_b['id']}/tokens", json={"name":"Team B pipeline"}).json()["token"]
        viewer = self.client.post(f"/api/teams/{team_a['id']}/tokens", json={"name":"Team A viewer", "roles":["Application Viewer"]}).json()["token"]
        headers_a, headers_b = {"x-control-plane-key":token_a}, {"x-control-plane-key":token_b}

        uploaded_a = self.client.post("/api/packages", headers=headers_a, files={"file":("orders.ifpkg", package_bytes(), "application/zip")})
        uploaded_b = self.client.post("/api/packages", headers=headers_b, files={"file":("orders.ifpkg", package_bytes(), "application/zip")})
        self.assertEqual(uploaded_a.json()["teamId"], team_a["id"])
        self.assertEqual(uploaded_b.json()["teamId"], team_b["id"])
        self.assertEqual(len(self.client.get("/api/packages", headers=headers_a).json()), 1)
        self.assertEqual(len(self.client.get("/api/packages", headers=headers_b).json()), 1)
        self.assertEqual(len(self.client.get("/api/packages").json()), 2)

        wrong_namespace = self.client.post("/api/deployments", headers=headers_a, json={"packageId":"orders:1.2.3", "environment":"dev", "dataPlaneId":plane["id"], "namespace":"team-b", "secrets":{"DB_PASSWORD":"x"}})
        self.assertEqual(wrong_namespace.status_code, 403)
        deployed = self.client.post("/api/deployments", headers=headers_a, json={"packageId":"orders:1.2.3", "environment":"dev", "dataPlaneId":plane["id"], "namespace":"team-a", "secrets":{"DB_PASSWORD":"x"}})
        self.assertEqual(deployed.status_code, 200, deployed.text)
        deployment_id = deployed.json()["id"]
        self.assertEqual(self.client.get(f"/api/deployments/{deployment_id}", headers=headers_b).status_code, 404)
        self.assertEqual(self.client.get("/api/data-planes", headers=headers_a).status_code, 403)
        self.assertEqual(self.client.get("/api/control-plane/overview", headers=headers_a).status_code, 403)
        self.assertEqual(self.client.get("/api/observability", headers=headers_b).json()["summary"]["applications"], 0)
        viewer_upload = self.client.post("/api/packages", headers={"x-control-plane-key":viewer}, files={"file":("orders.ifpkg", package_bytes(), "application/zip")})
        self.assertEqual(viewer_upload.status_code, 403)

    def test_technology_api_key_is_required_when_configured(self):
        main.API_KEY = "technology-secret"
        self.assertEqual(self.client.get("/api/teams").status_code, 401)
        authorized = self.client.get("/api/teams", headers={"x-admin-key":"technology-secret"})
        self.assertEqual(authorized.status_code, 200, authorized.text)
        self.assertEqual(authorized.json()[0]["id"], main.TECHNOLOGY_TEAM_ID)


if __name__ == "__main__":
    unittest.main()
