import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import ProcessDefinition, Project
from app.project_logging import _handlers, append_project_logs, project_log_info, read_project_logs
from app.runtime import WorkflowRuntime


class ProjectLoggingTests(unittest.TestCase):
    def test_project_log_rolls_and_can_be_read_back(self):
        project_id = "rolling-log-test"
        with tempfile.TemporaryDirectory() as folder:
            os.environ["FABRIC_RUNTIME_LOG_DIR"] = folder
            os.environ["FABRIC_PROJECT_LOG_MAX_BYTES"] = "1024"
            os.environ["FABRIC_PROJECT_LOG_BACKUP_COUNT"] = "2"
            try:
                for index in range(30):
                    append_project_logs(project_id, "Rolling Log Test", [{"level": "INFO", "message": f"record-{index}-" + "x" * 120}])
                info = project_log_info(project_id)
                self.assertLessEqual(info["sizeBytes"], 1024)
                self.assertTrue(Path(info["path"] + ".1").exists())
                self.assertTrue(read_project_logs(project_id, 100))
            finally:
                for key in [key for key in _handlers if key[0] == project_id]:
                    _handlers.pop(key).close()
                os.environ.pop("FABRIC_RUNTIME_LOG_DIR", None)
                os.environ.pop("FABRIC_PROJECT_LOG_MAX_BYTES", None)
                os.environ.pop("FABRIC_PROJECT_LOG_BACKUP_COUNT", None)

    def test_environment_properties_seed_a_user_configurable_log_directory(self):
        project = Project.model_validate({"id": "property-log-test", "name": "Property Log Test"})
        for environment in ("local", "dev", "qa", "pre", "production"):
            values = {item.key: item.value for item in project.properties[environment]}
            self.assertIn("runtime.logDirectory", values)

    def test_configured_directory_is_used_per_environment(self):
        project_id = "environment-log-test"
        with tempfile.TemporaryDirectory() as folder:
            dev_root = str(Path(folder) / "dev-logs")
            local_root = str(Path(folder) / "local-logs")
            append_project_logs(project_id, "Environment Log Test", [{"level": "INFO", "message": "dev"}], dev_root)
            append_project_logs(project_id, "Environment Log Test", [{"level": "INFO", "message": "local"}], local_root)
            self.assertEqual(read_project_logs(project_id, configured_directory=dev_root)[-1]["message"], "dev")
            self.assertEqual(read_project_logs(project_id, configured_directory=local_root)[-1]["message"], "local")
            self.assertNotEqual(project_log_info(project_id, dev_root)["path"], project_log_info(project_id, local_root)["path"])
            for key in [key for key in _handlers if key[0] == project_id]:
                _handlers.pop(key).close()

    def test_run_uses_selected_environment_log_directory(self):
        project_id = "environment-runtime-log-test"
        with tempfile.TemporaryDirectory() as folder:
            project = Project.model_validate({
                "id": project_id, "name": "Environment Runtime Log Test", "active_environment": "dev", "active_task_id": "main",
                "properties": {"dev": [{"key": "runtime.logDirectory", "value": folder, "data_type": "string"}]},
                "tasks": [{"id": "main", "name": "Main", "kind": "starter", "activities": [
                    {"id": "start", "type": "start", "name": "Start", "position": {"x": 0, "y": 0}, "config": {}},
                    {"id": "end", "type": "end", "name": "End", "position": {"x": 100, "y": 0}, "config": {}},
                ], "transitions": [{"id": "edge", "source": "start", "target": "end", "type": "success"}]}],
            })
            with patch("app.main.get_project", return_value=project):
                response = TestClient(app).post(f"/api/projects/{project_id}/run", json={"environment": "dev", "task_id": "main", "input": {}})
            self.assertEqual(response.status_code, 200)
            expected = Path(folder) / project_id / "application.log"
            self.assertTrue(expected.exists())
            self.assertIn("Application Environment Runtime Log Test started", expected.read_text(encoding="utf-8"))
            for key in [key for key in _handlers if key[0] == project_id]:
                _handlers.pop(key).close()

    def test_runtime_emits_activity_lifecycle_and_transition_logs(self):
        process = ProcessDefinition.model_validate({
            "id": "task", "name": "Logging Task", "kind": "starter",
            "activities": [
                {"id": "start", "type": "start", "name": "Start", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "end", "type": "end", "name": "End", "position": {"x": 100, "y": 0}, "config": {}},
            ],
            "transitions": [{"id": "edge", "source": "start", "target": "end", "type": "success"}],
        })
        result = asyncio.run(WorkflowRuntime().run(process, {}))
        messages = [entry["message"] for entry in result.logs]
        self.assertTrue(any(message.startswith("Activity started:") for message in messages))
        self.assertTrue(any(message.startswith("Activity completed:") for message in messages))
        self.assertTrue(any(message.startswith("Transition selected:") for message in messages))


if __name__ == "__main__":
    unittest.main()
