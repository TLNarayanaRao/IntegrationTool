"""Opt-in compatibility tests. Read the installed BW samples without copying them into MINA."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape

from app.debugger import DebugManager
from app.models import Project
from app.project_import import project_payload
from app.raw_python import raw_python_files, engine_python_files
from app.runtime import WorkflowRuntime


@unittest.skipUnless(os.environ.get('MINA_BW613_HOME'), 'set MINA_BW613_HOME to the installed BW 6.13 directory')
class BW613VendorSamples(unittest.TestCase):
    def verify_sample(self, archive_name, task_suffix, payload, expected_type):
        samples = Path(os.environ['MINA_BW613_HOME']) / 'samples' / 'AppSpace'
        archive = next(samples.rglob(archive_name))
        imported = json.loads(project_payload(archive.read_bytes(), archive.name))
        task = next(task for task in imported['tasks'] if task['name'].endswith(task_suffix))
        activity = next(activity for activity in task['activities'] if activity['type'] == expected_type)
        self.assertTrue(activity['config'].get('targetSchemaId') or activity['config'].get('schemaId'))
        project = Project.model_validate({**imported,'tasks':[task],'active_task_id':task['id']})
        runtime = WorkflowRuntime()
        run = asyncio.run(runtime.run(project.tasks[0],payload,project=project))
        self.assertEqual(run.status,'completed',run.logs)
        debug = DebugManager(runtime)
        session = debug.start(project,task['id'],payload,{}, {}, [])
        result = asyncio.run(debug.action(session['sessionId'],'continue'))
        self.assertEqual(result['status'],'completed',result['logs'])
        self.assertEqual(result['output'],run.output)
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                for name, data in compiler(project.model_dump(), {'local':[]}).items():
                    file = Path(folder) / name
                    file.parent.mkdir(parents=True,exist_ok=True)
                    file.write_bytes(data)
                script = ('import asyncio,json; from application.main import run_task; '
                          f'print("RESULT="+json.dumps(asyncio.run(run_task({task["id"]!r},{payload!r}))))')
                run_archive = subprocess.run([sys.executable,'-c',script],cwd=folder,capture_output=True,text=True,timeout=40)
                self.assertEqual(run_archive.returncode,0,run_archive.stdout+run_archive.stderr)
                self.assertEqual(json.loads(next(line[7:] for line in run_archive.stdout.splitlines() if line.startswith('RESULT='))),run.output)
        return run.output

    ORDER = ('<PurchaseOrder xmlns="http://tibco.tnt.org/Invoice"><OrderIdentifier>PO-7</OrderIdentifier>'
             '<CustomerIdentifier>C-1</CustomerIdentifier><LineItem><OrderIdentifier>PO-7</OrderIdentifier>'
             '<LineNumber>1</LineNumber><ItemIdentifier>ITEM</ItemIdentifier><Quantity>2</Quantity>'
             '<UnitPrice>9.50</UnitPrice></LineItem></PurchaseOrder>')

    def test_vendor_parse_xml(self):
        payload = {'ReadPOXMLFile': '<ReadPOXMLFile><fileContent><textContent>'+escape(self.ORDER)+'</textContent></fileContent></ReadPOXMLFile>'}
        output = self.verify_sample('tibco.bw.sample.palette.java.InvokeCode.zip','JavaProcess ParsePOXML',payload,'xml')
        self.assertEqual(output['PurchaseOrder']['OrderIdentifier'],'PO-7')
        self.assertEqual(output['PurchaseOrder']['LineItem'][0]['Quantity'],'2')

    def test_vendor_render_xml(self):
        payload = {'Variable': '<completePO>'+self.ORDER+'<CustomerInfo xmlns="http://tibco.tnt.org/Customer"><CustomerName>MINA</CustomerName></CustomerInfo></completePO>'}
        output = self.verify_sample('tibco.bw.sample.palette.java.InvokeCode.zip','JavaProcess RenderPOXML',payload,'xml')
        self.assertIn('PO-7',output['xmlString'])
        self.assertIn('MINA',output['xmlString'])

    def test_vendor_mapper(self):
        payload = {'Start':'<Start xmlns="http://www.example.com/namespaces/tns/1580279674527"><elements><AuthorID>1</AuthorID></elements></Start>'}
        output = self.verify_sample('tibco.bw.UT.sample.UnitTestDemoProject.zip','SubProcesswithActivityAssertion Mapper',payload,'mapper')
        self.assertEqual(output['Book']['Title'],'My Life and Times')

    def test_vendor_mapper_repeating_element_with_linked_target_schema(self):
        payload = {
            'ParsePOXML': self.ORDER,
            'Variable': '<completePO><CustomerInfo xmlns="http://tibco.tnt.org/Customer"><CustomerName>MINA</CustomerName></CustomerInfo></completePO>',
            'JavaCode': '<JavaCode/>',
            'index': 1,
        }
        output = self.verify_sample('tibco.bw.sample.palette.java.InvokeCode.zip', 'JavaProcess Map-Data', payload, 'mapper')
        self.assertEqual(output['completePO']['PurchaseOrder']['LineItem'][0]['Quantity'], '2')
        self.assertEqual(output['completePO']['CustomerInfo']['CustomerName'], 'MINA')
