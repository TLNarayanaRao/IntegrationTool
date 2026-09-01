import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.google_pubsub import client_configuration, credential_summary
from app.main import deployment_package_files
from app.models import Project, SharedResource


SERVICE_ACCOUNT = {
    "type": "service_account",
    "project_id": "orders-project",
    "private_key_id": "key-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
    "client_email": "fabric@orders-project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/fabric",
}


class GooglePubSubConnectionTests(unittest.TestCase):
    @patch("app.google_pubsub._credentials_from_info")
    def test_inline_service_account_json_builds_credentials_and_derives_project(self, create_credentials):
        credentials = object()
        create_credentials.return_value = credentials
        kwargs, project_id = client_configuration({
            "authenticationType": "Service Account JSON",
            "serviceAccountJson": json.dumps(SERVICE_ACCOUNT),
            "endpoint": "pubsub.googleapis.com:443",
        })
        self.assertEqual(project_id, "orders-project")
        self.assertIs(kwargs["credentials"], credentials)
        self.assertEqual(kwargs["client_options"]["api_endpoint"], "pubsub.googleapis.com:443")
        create_credentials.assert_called_once_with(SERVICE_ACCOUNT)
        self.assertEqual(credential_summary({"serviceAccountJson": SERVICE_ACCOUNT})["clientEmail"], SERVICE_ACCOUNT["client_email"])

    def test_service_account_json_validation_is_actionable(self):
        with self.assertRaisesRegex(ValueError, "Service account JSON is invalid"):
            client_configuration({"authenticationType": "Service Account JSON", "serviceAccountJson": "{bad"})
        incomplete = {"type": "service_account", "project_id": "orders-project"}
        with self.assertRaisesRegex(ValueError, "client_email, private_key, token_uri"):
            client_configuration({"authenticationType": "Service Account JSON", "serviceAccountJson": incomplete})

    @patch("app.google_pubsub._credentials_from_info")
    def test_legacy_credentials_file_remains_compatible(self, create_credentials):
        create_credentials.return_value = object()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "service-account.json"
            path.write_text(json.dumps(SERVICE_ACCOUNT), encoding="utf-8")
            _, project_id = client_configuration({"credentialsFile": str(path)})
        self.assertEqual(project_id, "orders-project")

    def test_service_account_json_is_removed_from_deployment_packages(self):
        project = Project(
            id="pubsub-package",
            name="Pub/Sub package",
            resources=[SharedResource(
                id="gcp",
                type="pubsub",
                name="Google Pub/Sub",
                config={"authenticationType": "Service Account JSON", "serviceAccountJson": json.dumps(SERVICE_ACCOUNT)},
            )],
        )
        files = deployment_package_files(project, "on-prem", "local", set())
        packaged = json.loads(files["application/resources/pubsub/gcp.json"])
        self.assertEqual(packaged["config"]["serviceAccountJson"], "")
        manifest = json.loads(files["manifest.json"])
        self.assertIn("resources.gcp.config.serviceAccountJson", manifest["secretKeys"])


if __name__ == "__main__":
    unittest.main()
