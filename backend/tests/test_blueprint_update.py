import copy
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import store
from app.api_blueprint import blueprint_plan
from app.blueprint_update import update_plan, apply_update, revision, UpdateConflict
from app.models import Project, Activity, Transition
from tests.test_raml_contract import RAML, REFERENCES


def project():
    plan=blueprint_plan(RAML,['books','book'],{'type':'http','config':{'host':'127.0.0.1','port':8080,
        'trustedCertificateFolder':'${properties.tls.roots}'}},response_mode='example',reference_documents=REFERENCES,document_path='api.raml',package_path='APIs/Books')
    item=Project.model_validate({'id':'update-test','name':'Update-Test','resources':[plan['resource']],'tasks':plan['tasks']})
    task=item.tasks[0]
    task.activities.insert(1,Activity(id='Business',name='Business',type='log',config={'inputMappings':{'payload':'${input}'}}))
    task.transitions=[Transition(id='business-link',source='Receive',target='Business'),Transition(id='reply-link',source='Business',target='Reply'),Transition(id='end-link',source='Reply',target='End')]
    task.activities[-2].config['inputMappings']={'body':'[{"id":"42","title":"custom"}]'}
    task.input_schema={'type':'object','properties':{'custom':{'type':'boolean'}}}
    return item,item.resources[0].id


class BlueprintUpdateTests(unittest.TestCase):
    def test_in_place_update_preserves_complete_implementation_and_transport(self):
        item,target=project();before=item.model_dump()
        changed=RAML.replace('minimum: 2','minimum: 3')+'\n/health:\n  get:\n    (operationId): health\n    responses: {204: {description: Healthy}}\n'
        candidate,report=update_plan(item,target,changed,['books','book','health'],reference_documents=REFERENCES,document_path='api.raml')
        self.assertEqual(item.model_dump(),before)
        for old in item.tasks:
            current=next(task for task in candidate.tasks if task.id==old.id)
            self.assertEqual(current.model_dump(),old.model_dump())
        self.assertEqual(candidate.resources[0].id,target)
        self.assertEqual(candidate.resources[0].config['trustedCertificateFolder'],'${properties.tls.roots}')
        self.assertEqual(len(report['added']),1)
        self.assertTrue(report['updated']);self.assertTrue(report['requiresReview'])

    def test_operation_id_keeps_flow_when_route_changes_and_removed_operations_block(self):
        item,target=project()
        candidate,report=update_plan(item,target,RAML.replace('/books:','/library:'),['books','book'],reference_documents=REFERENCES,document_path='api.raml')
        self.assertEqual(candidate.tasks[0].id,item.tasks[0].id)
        self.assertFalse(report['removed']);self.assertTrue(report['updated'])
        _,report=update_plan(item,target,RAML,['books'],reference_documents=REFERENCES,document_path='api.raml')
        self.assertEqual(len(report['removed']),1);self.assertTrue(report['conflicts'])

    def test_apply_is_revision_and_contract_bound_and_rolls_back_failed_save(self):
        item,target=project()
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'DATA_DIR',Path(folder)),patch.object(store,'PROJECTS_DIR',Path(folder)/'projects'):
            store.save_project(item)
            before=store.get_project(item.id)
            changed=RAML.replace('minimum: 2','minimum: 3')
            _,report=update_plan(before,target,changed,['books','book'],reference_documents=REFERENCES,document_path='api.raml')
            options={'reference_documents':REFERENCES,'document_path':'api.raml'}
            with self.assertRaises(UpdateConflict):apply_update(item.id,target,changed,['books','book'],'stale',True,report['token'],**options)
            with self.assertRaises(UpdateConflict):apply_update(item.id,target,RAML,['books','book'],report['revision'],True,report['token'],**options)
            with self.assertRaises(UpdateConflict):apply_update(item.id,target,changed,['books','book'],report['revision'],False,report['token'],**options)
            original=store.save_project
            def failing_save(candidate,**kwargs):
                original(candidate,**kwargs)
                raise OSError('Simulated disk failure after write')
            with patch.object(store,'save_project',side_effect=failing_save),self.assertRaises(OSError):
                apply_update(item.id,target,changed,['books','book'],report['revision'],True,report['token'],**options)
            self.assertEqual(revision(store.get_project(item.id)),report['revision'])
            updated,_=apply_update(item.id,target,changed,['books','book'],report['revision'],True,report['token'],**options)
            self.assertNotEqual(revision(updated),report['revision'])
            self.assertEqual(store.get_project(item.id).tasks[0].activities[1].config,item.tasks[0].activities[1].config)

    def test_callback_helpers_keep_ids_and_custom_mappings(self):
        from tests.test_api_blueprint_robustness import contract
        document=contract();document['paths']['/orders/{order-id}']['get']['callbacks']={'notify':{'{$request.query.callbackUrl}':{'post':{'responses':{'200':{'description':'OK'}}}}}}
        plan=blueprint_plan(document,['getOrder'],{'type':'http','config':{}})
        item=Project.model_validate({'id':'callbacks','name':'Callbacks','resources':[plan['resource']],'tasks':plan['tasks']})
        helper=item.tasks[-1];helper.activities[1].config['inputMappings']['RestInputRequest.Config.RequestBody']='${input.custom}'
        changed=copy.deepcopy(document);changed['paths']['/orders/{order-id}']['get']['callbacks']['notify']['{$request.query.callbackUrl}']['post']['responses']['200']['description']='Delivered'
        candidate,report=update_plan(item,item.resources[0].id,changed,['getOrder'])
        actual=next(task for task in candidate.tasks if task.id==helper.id)
        self.assertEqual(actual.activities[1].config['inputMappings'],helper.activities[1].config['inputMappings'])
        self.assertTrue(report['callbackUpdates']);self.assertEqual(len(candidate.tasks),len(item.tasks))


class UpdatedRamlArchiveTests(unittest.TestCase):
    def test_both_archives_run_updated_contract_and_preserved_mapping(self):
        from app.raw_python import raw_python_files,engine_python_files
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(archive=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                item,target=project()
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                item.resources[0].config.update(port=port,trustedCertificateFolder='')
                changed=RAML.replace('minimum: 2','minimum: 3')+'\n/health:\n  get:\n    (operationId): health\n    responses: {204: {description: Healthy}}\n'
                candidate,_=update_plan(item,target,changed,['books','book','health'],reference_documents=REFERENCES,document_path='api.raml',response_mode='example')
                for name,data in compiler(candidate.model_dump(),{'local':[]}).items():
                    path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                script=f'''import asyncio,httpx
from application.main import run_application
async def main():
    job=asyncio.create_task(run_application('local'))
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for attempt in range(100):
                if job.done():await job
                try:
                    response=await client.get('http://127.0.0.1:{port}/v1/books?page=3',timeout=.3)
                    break
                except (httpx.ConnectError,httpx.ConnectTimeout):await asyncio.sleep(.05)
            else:raise AssertionError('API did not start')
            assert response.status_code==200,response.text
            assert response.json()==[{{'id':'42','title':'custom'}}],response.text
            assert (await client.get('http://127.0.0.1:{port}/v1/books?page=2')).status_code==400
            assert (await client.get('http://127.0.0.1:{port}/v1/health')).status_code==204
            spec=await client.get('http://127.0.0.1:{port}/_mina/openapi.json')
            assert len(spec.json()['paths'])==3,spec.text
            docs=await client.get('http://127.0.0.1:{port}/_mina/docs')
            assert 'SwaggerUIBundle' in docs.text,docs.text
            collection=await client.get('http://127.0.0.1:{port}/_mina/postman.json')
            assert len(collection.json()['item'])==3,collection.text
    finally:
        job.cancel()
        try:await job
        except asyncio.CancelledError:pass
asyncio.run(main())
'''
                driver=Path(folder)/'verify_updated.py';driver.write_text(script,encoding='utf-8')
                result=subprocess.run([sys.executable,str(driver)],cwd=folder,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
