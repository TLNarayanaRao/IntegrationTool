import unittest

from pydantic import ValidationError
from app.models import Transition
from app.raw_python import engine_python_files


class TransitionColorTests(unittest.TestCase):
    def test_color_round_trip_and_legacy_default(self):
        edge = Transition(id='edge', source='start', target='end', color='#a855f7')
        self.assertEqual(Transition.model_validate_json(edge.model_dump_json()).color, '#a855f7')
        self.assertEqual(Transition(id='old', source='start', target='end').color, '')
        for invalid in ['red', '#fff', 'url(https://example.org)']:
            with self.assertRaises(ValidationError):
                Transition(id='edge', source='start', target='end', color=invalid)

    def test_python_export_preserves_transition_color(self):
        project = {'id':'colors', 'name':'Colors', 'resources':[], 'schemas':[], 'active_task_id':'main', 'tasks':[{
            'id':'main', 'name':'Main', 'kind':'starter', 'activities':[
                {'id':'start', 'type':'start', 'name':'Start', 'config':{}},
                {'id':'end', 'type':'end', 'name':'End', 'config':{}},
            ], 'transitions':[{'id':'edge', 'source':'start', 'target':'end', 'color':'#a855f7'}],
        }]}
        files = engine_python_files(project, {'dev':[]})
        tasks = [value.decode() for path,value in files.items() if path.startswith('application/tasks/')]
        self.assertTrue(any("color='#a855f7'" in source or 'color="#a855f7"' in source for source in tasks))


if __name__ == '__main__':
    unittest.main()
