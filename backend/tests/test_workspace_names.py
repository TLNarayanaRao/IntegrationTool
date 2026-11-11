import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import store
from app.models import Project, SharedResource, find_subtask


class WorkspaceNamesTests(unittest.TestCase):
    def test_save_rejects_new_collisions_and_keeps_legacy_projects_editable(self):
        project = Project(id='names', name='Names', tasks=[
            {'id':'first', 'name':'Read Orders', 'package_path':'Default'},
            {'id':'second', 'name':'read-orders', 'package_path':'Orders'},
        ])
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
                store, PROJECTS_DIR=Path(directory) / 'projects', LEGACY_DB=Path(directory) / 'legacy.db'):
            store.save_project(project, enforce_names=True)
            project.tasks[1].package_path = 'default'
            with self.assertRaisesRegex(ValueError, 'already exists in package'):
                store.save_project(project, enforce_names=True)
            store.save_project(project)  # Legacy import keeps both items available for repair.
            store.save_project(project, enforce_names=True)
            project.tasks[1].name = 'Receive Orders'
            store.save_project(project, enforce_names=True)
            project.resources.append(SharedResource(id='resource',type='http',name='READ-ORDERS',package_path='Default'))
            with self.assertRaisesRegex(ValueError, 'already exists in package'):
                store.save_project(project, enforce_names=True)

    def test_subtasks_can_be_selected_by_id_or_qualified_name(self):
        project = Project(id='names', name='Names', tasks=[
            {'id':'first','kind':'subtask','name':'Validate','package_path':'Default'},
            {'id':'second','kind':'subtask','name':'Validate','package_path':'Orders/Inbound'},
        ])
        self.assertIsNone(find_subtask(project.tasks, 'Validate'))
        self.assertEqual(find_subtask(project.tasks, 'orders/inbound/validate').id, 'second')
        self.assertEqual(find_subtask(project.tasks, 'first').id, 'first')
