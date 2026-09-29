import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import java_bridge
from app.main import app


class UpgradeCompatibilityTests(unittest.TestCase):
    def test_legacy_archive_formats_import_in_studio(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.store.PROJECTS_DIR', Path(folder)):
            for format_name, location in [('integration-fabric-project', 'project.json'), ('integration-fabric-deployment', 'application/project.json')]:
                body = io.BytesIO()
                with zipfile.ZipFile(body, 'w') as archive:
                    archive.writestr('manifest.json', json.dumps({'format':format_name}))
                    archive.writestr(location, json.dumps({'id':'compat-test', 'name':'Compatibility', 'tasks':[]}))
                with TestClient(app) as client:
                    response = client.post('/api/projects/import', files={'file':('legacy.ifpkg', body.getvalue(), 'application/zip')})
                self.assertEqual(response.status_code, 200, response.text)

    def test_driver_override_old_and_new_precedence(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FABRIC_DRIVER_HOME':folder, 'MINA_DRIVER_HOME':''}, clear=False):
            self.assertEqual(java_bridge.default_driver_home(), Path(folder).resolve())
            with patch.dict(os.environ, {'MINA_DRIVER_HOME':folder+'/new'}):
                self.assertEqual(java_bridge.default_driver_home(), Path(folder+'/new').resolve())

    def test_legacy_driver_folder_is_retained(self):
        paths = java_bridge.driver_directories({}, 'jms')
        if os.name == 'nt' and os.environ.get('PROGRAMDATA'):
            self.assertIn(Path(os.environ['PROGRAMDATA']) / 'Integration Fabric Studio/drivers/jms', paths)
        elif os.name != 'nt':
            self.assertIn(Path('/opt/integrationfabric/drivers/jms'), paths)
