"""Studio subtree deletion -> saved project -> Run/Debug and executable archives."""
import copy
import asyncio
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import get_args

from fastapi.testclient import TestClient
from app.main import app
from app.models import Activity, ActivityKind
from app.models import Project
from app.runtime import WorkflowRuntime

ROOT=Path(__file__).resolve().parents[2]


def studio_clear(requests):
    node=shutil.which('node')
    if not node or not (ROOT/'frontend/node_modules/typescript').is_dir():
        raise unittest.SkipTest('Cross-layer verification requires frontend Node/TypeScript dependencies')
    result=subprocess.run([node,str(ROOT/'frontend/tests/fixtures/clear-mapping-subtree.mjs')],
        input=json.dumps(requests),text=True,capture_output=True,timeout=30,cwd=ROOT)
    if result.returncode:raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def project():
    def activity(id,kind,config=None):return dict(id=id,name=id,type=kind,config=config or {})
    def edges(pairs):return [dict(id=str(i),source=a,target=b) for i,(a,b) in enumerate(pairs)]
    return dict(id='subtree-clear-e2e',name='Subtree-Clear-E2E',resources=[],schemas=[],
        properties={'local':[]},active_task_id='main',tasks=[
        dict(id='main',name='Main',kind='starter',activities=[
            activity('start','start'),
            activity('call','call_task',{'taskId':'child','inputMappings':{
                'payload.removed.secret':'"stale-call"','payload.keep.id':'${input.id}'}}),
            activity('other','mapper',{'mappings':[
                {'target':'removed.secret','constant':'stale-mapper'},
                {'target':'stable.id','source':'${input.id}'},
                {'target':'stable.secret','source':'${input.secret}'}]}),
            activity('end','end',{'inputMappings':{
                'result.removed.secret':'"stale-end"',
                'result.call':'${activities.call.output}',
                'result.other':'${activities.other.output}'}})],
            transitions=edges([('start','call'),('start','other'),('call','end'),('other','end')])),
        dict(id='child',name='Child',kind='subtask',activities=[activity('cs','start'),
            activity('ce','end',{'inputMappings':{
                'result.removed.secret':'"stale-child"','result.kept':'${input.keep}'}})],
            transitions=edges([('cs','ce')]))])


class MappingSubtreeE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=project();cls.cleared=copy.deepcopy(cls.original)
        nodes={n['id']:n for task in cls.cleared['tasks'] for n in task['activities']}
        targets=[('call','inputMappings','payload.removed'),('other','mappings','removed'),
                 ('end','inputMappings','result.removed'),('ce','inputMappings','result.removed')]
        results=studio_clear([dict(mappings=nodes[id]['config'][key],target=target) for id,key,target in targets])
        for (id,key,_),cleared in zip(targets,results):nodes[id]['config'][key]=cleared
        cls.expected={'call':{'kept':{'id':7}},'other':{'stable':{'id':7,'secret':'untouched'}}}
        cls.initial={'id':7,'secret':'untouched'}

    def test_every_activity_kind_resolves_saved_cleared_input_without_reviving_descendants(self):
        mappings={'root.removed.secret':'"stale"','root.keep.value':'${input.id}',
            'rootSibling.value':'${input.secret}', '$occurrences':[
                {'target':'root.removed.rows','source':'${input.rows}','operator':'for-each',
                 'occurrenceId':'nested','duplicateOf':'primary'},
                {'target':'root.removed.rows.value','source':'${input.id}','occurrenceId':'nested'}]}
        cleared=studio_clear([dict(mappings=mappings,target='root.removed')])[0]
        self.assertNotIn('$occurrences',cleared)
        runtime=WorkflowRuntime()
        for kind in get_args(ActivityKind):
            with self.subTest(kind=kind):
                ctx={'input':self.initial,'last':{},'vars':{},'properties':{},'resources':{},'context':{}}
                config=runtime.resolve_activity_config(Activity(id='a',type=kind,name=kind,
                    config={'inputMappings':json.loads(json.dumps(cleared))}),ctx)
                self.assertEqual(config['root'],{'keep':{'value':7}})
                self.assertEqual(config['rootSibling'],{'value':'untouched'})
                self.assertNotIn('removed',config['root'])

    def test_saved_project_run_and_debug_use_latest_clear_and_preserve_parallel_branch(self):
        client=TestClient(app);session=None
        try:
            self.assertEqual(client.post('/api/projects',json=self.original).status_code,200)
            before=client.post('/api/projects/subtree-clear-e2e/run',json={'task_id':'main','input':self.initial})
            self.assertEqual(before.status_code,200,before.text)
            self.assertEqual(before.json()['output']['removed'],{'secret':'stale-end'})
            saved=client.post('/api/projects',json=self.cleared)
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertNotIn('stale-',json.dumps(saved.json()))
            run=client.post('/api/projects/subtree-clear-e2e/run',json={'task_id':'main','input':self.initial})
            self.assertEqual(run.status_code,200,run.text)
            result=run.json();self.assertEqual(result['status'],'completed',result)
            self.assertEqual(result['output'],self.expected)
            self.assertEqual(result['task_outputs']['child']['activities']['cs']['output'],{'keep':{'id':7}})
            self.assertEqual(result['activity_outputs']['other']['output'],self.expected['other'])
            debug=client.post('/api/projects/subtree-clear-e2e/debug',json={
                'task_id':'main','input':self.initial,'test_mode':True})
            self.assertEqual(debug.status_code,200,debug.text);session=debug.json()['sessionId']
            continued=client.post(f'/api/debug/{session}/action',json={'action':'continue'})
            self.assertEqual(continued.status_code,200,continued.text)
            state=continued.json();self.assertEqual(state['status'],'completed',state)
            self.assertEqual(state['activityOutputs']['end']['output'],self.expected)
            self.assertEqual(state['taskOutputs']['child']['input'],{'keep':{'id':7}})
            self.assertEqual(state['activityOutputs']['other']['output'],self.expected['other'])
        finally:
            if session:client.post(f'/api/debug/{session}/action',json={'action':'stop'})
            client.delete('/api/projects/subtree-clear-e2e')

    def test_both_downloaded_python_archives_execute_cleared_parallel_flow(self):
        client=TestClient(app)
        try:
            self.assertEqual(client.post('/api/projects',json=self.cleared).status_code,200)
            for mode in ('python-direct','python-engine'):
                with self.subTest(mode=mode),tempfile.TemporaryDirectory(prefix='subtree-export-') as folder:
                    response=client.get(f'/api/projects/subtree-clear-e2e/package?archive={mode}&environment=local')
                    self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        archive.extractall(folder)
                    completed=subprocess.run([sys.executable,'-m','application.main','--task','main',
                        '--input',json.dumps(self.initial)],cwd=folder,text=True,capture_output=True,timeout=45)
                    self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
                    self.assertEqual(json.loads(completed.stdout),self.expected)
        finally:client.delete('/api/projects/subtree-clear-e2e')

    def test_deleting_the_last_mapping_keeps_documented_boundary_passthrough_defaults(self):
        cleared=studio_clear([dict(mappings={'result.removed':'${input.missing}'},target='result'),
                              dict(mappings={'payload.removed':'${input.missing}'},target='payload')])
        self.assertEqual(cleared,[{},{}])
        project_value=Project.model_validate(dict(id='empty-subtree',name='Empty-Subtree',tasks=[
            dict(id='child',name='Child',kind='subtask',activities=[
                dict(id='s',name='Start',type='start'),dict(id='e',name='End',type='end')],
                transitions=[dict(id='se',source='s',target='e')])]))
        async def execute():
            runtime=WorkflowRuntime()
            for kind,mapping in zip(('end','call_task'),cleared):
                ctx={'input':{},'last':{'kept':'previous output'},'vars':{},'properties':{},
                     'resources':{},'context':{},'project':project_value,'logs':[]}
                activity=Activity(id='a',name='Activity',type=kind,config={'taskId':'child','inputMappings':mapping})
                self.assertEqual(await runtime.execute(activity,ctx),{'kept':'previous output'})
        asyncio.run(execute())
