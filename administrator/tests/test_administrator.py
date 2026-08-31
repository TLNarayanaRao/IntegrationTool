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


if __name__ == "__main__":
    unittest.main()
