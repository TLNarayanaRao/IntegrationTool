import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.jdbc import execute
from app.models import Project
from app.raw_python import engine_python_files, raw_python_files
from app.runtime import WorkflowRuntime


SAMPLES = Path(__file__).resolve().parents[2] / 'frontend' / 'public' / 'samples'


class PostgreSQLExamplesTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('MINA_TEST_POSTGRES_DSN'), 'Requires a disposable PostgreSQL database')
    def test_live_postgresql_examples_in_runtime_and_both_archives(self):
        dsn = os.environ['MINA_TEST_POSTGRES_DSN']
        execute({'driver':'postgresql','url':dsn},
                {'operation':'direct','sql':(SAMPLES/'postgresql-setup.sql').read_text(encoding='utf-8-sig')})
        for name in ('postgresql-crud', 'postgresql-procedure-and-paging'):
            project = Project.model_validate_json((SAMPLES/f'{name}.json').read_text(encoding='utf-8'))
            for prop in project.properties['local']:
                if prop.key == 'connections.jdbc.url':
                    prop.value = dsn
                elif prop.key == 'connections.jdbc.username':
                    prop.value = ''
            config = {prop.key:prop.value for prop in project.properties['local']}
            result = asyncio.run(WorkflowRuntime().run(project.tasks[0], {},
                {resource.id:resource for resource in project.resources}, config, project=project))
            self.assertEqual(result.status, 'completed', result.logs)
            expected = ('rowCount', 1) if name == 'postgresql-crud' else ('outParameters', {'total':'32.000000'})
            self.assert_result(result.output, expected)
            profiles = {'local':[prop.model_dump() for prop in project.properties['local']]}
            for compiler in (raw_python_files, engine_python_files):
                with self.subTest(sample=name, archive=compiler.__name__), tempfile.TemporaryDirectory() as folder:
                    for filename, data in compiler(project.model_dump(), profiles).items():
                        path = Path(folder)/filename
                        path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(data)
                    command = ['run.py'] if compiler is raw_python_files else ['-m','application.main']
                    completed = subprocess.run([sys.executable,*command,'--task','main'],cwd=folder,
                                               capture_output=True,text=True,timeout=30)
                    self.assertEqual(completed.returncode,0,completed.stderr)
                    self.assert_result(json.loads(completed.stdout),expected)

    def assert_result(self, result, expected):
        key, value = expected
        if key == 'outParameters':
            from decimal import Decimal
            self.assertEqual(Decimal(str(result[key]['total'])), Decimal(value['total']))
        else:
            self.assertEqual(result[key], value)
