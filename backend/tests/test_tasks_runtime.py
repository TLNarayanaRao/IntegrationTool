import io, json, tarfile, unittest, zipfile
from fastapi.testclient import TestClient
from app.main import app

class TaskRuntimeTests(unittest.TestCase):
    def setUp(self): self.client = TestClient(app)

    def project(self):
        return {
            'id':'task-runtime-test','name':'Task Runtime Test','description':'',
            'resources':[{'id':'k1','type':'kafka','name':'Local Kafka','config':{'mode':'memory'}}],
            'properties':{'local':[],'dev':[],'qa':[],'pre':[],'production':[]},'active_environment':'local','schemas':[],
            'tasks':[
                {'id':'main','name':'Starter','kind':'starter','activities':[
                    {'id':'s','type':'start','name':'Start','position':{'x':0,'y':0},'config':{}},
                    {'id':'c','type':'call_task','name':'Call child','position':{'x':1,'y':0},'config':{'taskId':'child','inputMappings':{'value':'${input.value}'}}},
                    {'id':'p','type':'kafka','name':'Publish','position':{'x':2,'y':0},'config':{'operation':'publish','resourceId':'k1','topic':'orders','message':'${last}'}},
                    {'id':'r','type':'kafka','name':'Receive','position':{'x':3,'y':0},'config':{'operation':'receive','resourceId':'k1','topic':'orders','maxMessages':1}},
                    {'id':'e','type':'end','name':'End','position':{'x':4,'y':0},'config':{}}],
                 'transitions':[{'id':'1','source':'s','target':'c'},{'id':'2','source':'c','target':'p'},{'id':'3','source':'p','target':'r'},{'id':'4','source':'r','target':'e'}]},
                {'id':'child','name':'Child','kind':'subtask','activities':[
                    {'id':'cs','type':'start','name':'Start','position':{'x':0,'y':0},'config':{'interfaceSchemaText':'{"type":"object","properties":{"value":{"type":"integer"}}}'}},
                    {'id':'ce','type':'end','name':'End','position':{'x':1,'y':0},'config':{'interfaceSchemaText':'{"type":"object","properties":{"answer":{"type":"object","properties":{"value":{"type":"integer"}}}}}', 'inputMappings':{'answer.value':'${input.value}'}}}],
                 'transitions':[{'id':'c1','source':'cs','target':'ce'}]}
            ],'active_task_id':'main'
        }

    def test_subtask_messaging_export_import_and_debug(self):
        payload = self.project()
        payload['properties']['production'] = [{'key':'custom.password','value':'do-not-package','data_type':'password'}]
        self.assertEqual(self.client.post('/api/projects', json=payload).status_code, 200)
        result = self.client.post('/api/projects/task-runtime-test/run', json={'task_id':'main','input':{'value':42},'environment':'local'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'completed')
        self.assertEqual(result.json()['output']['count'], 1)
        self.assertEqual(result.json()['activity_outputs']['c']['output'], {'answer': {'value': 42}})
        self.assertEqual(result.json()['task_outputs']['child']['output'], {'answer': {'value': 42}})
        exported = self.client.get('/api/projects/task-runtime-test/export')
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertIn('tasks/child.json', archive.namelist())
            self.assertIn('resources/kafka/k1.json', archive.namelist())
        imported = self.client.post('/api/projects/import', files={'file':('project.ifproject', exported.content, 'application/zip')})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(len(imported.json()['tasks']), 2)
        debug = self.client.post('/api/projects/task-runtime-test/debug', json={'task_id':'main','input':{'value':42},'breakpoints':['c']})
        self.assertEqual(debug.status_code, 200)
        stepped = self.client.post(f"/api/debug/{debug.json()['sessionId']}/action", json={'action':'step_over'})
        self.assertEqual(stepped.status_code, 200)
        self.assertEqual(stepped.json()['currentActivityId'], 'c')
        entered = self.client.post(f"/api/debug/{debug.json()['sessionId']}/action", json={'action':'step_in'})
        self.assertEqual(entered.json()['currentTaskId'], 'child')
        self.assertEqual(entered.json()['currentActivityId'], 'cs')
        child_step = self.client.post(f"/api/debug/{debug.json()['sessionId']}/action", json={'action':'step_over'})
        self.assertEqual(child_step.json()['currentActivityId'], 'ce')
        returned = self.client.post(f"/api/debug/{debug.json()['sessionId']}/action", json={'action':'step_out'})
        self.assertEqual(returned.json()['currentTaskId'], 'main')
        self.assertEqual(returned.json()['currentActivityId'], 'p')
        self.assertEqual(returned.json()['activityOutputs']['c']['output'], {'answer': {'value': 42}})
        json_file = self.client.get('/api/projects/task-runtime-test/json')
        self.assertEqual(json_file.status_code, 200)
        self.assertEqual(json.loads(json_file.content)['id'], 'task-runtime-test')
        cloud_package = self.client.get('/api/projects/task-runtime-test/package?target=cloud&environment=production&archive=ifpkg')
        self.assertEqual(cloud_package.status_code, 200)
        self.assertNotIn(b'do-not-package', cloud_package.content)
        with zipfile.ZipFile(io.BytesIO(cloud_package.content)) as archive:
            names = archive.namelist()
            self.assertIn('deployment/cloud/Dockerfile', names)
            self.assertIn('deployment/cloud/configmap.yaml', names)
            self.assertIn('deployment/cloud/secret.yaml', names)
            self.assertIn('deployment/cloud/deployment.yaml', names)
            self.assertIn('deployment/cloud/service.yaml', names)
            self.assertIn('deployment/cloud/hpa.yaml', names)
            self.assertIn('deployment/cloud/kustomization.yaml', names)
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['target'], 'cloud')
            self.assertIn('deployment', manifest['selectedArtifacts'])
        selected_cloud = self.client.get('/api/projects/task-runtime-test/package?target=cloud&environment=production&archive=ifpkg&artifacts=deployment,service')
        self.assertEqual(selected_cloud.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(selected_cloud.content)) as archive:
            self.assertIn('deployment/cloud/deployment.yaml', archive.namelist())
            self.assertIn('deployment/cloud/service.yaml', archive.namelist())
            self.assertNotIn('deployment/cloud/Dockerfile', archive.namelist())
            self.assertNotIn('deployment/cloud/secret.yaml', archive.namelist())
        on_prem_package = self.client.get('/api/projects/task-runtime-test/package?target=on-prem&environment=production&archive=tar.gz')
        self.assertEqual(on_prem_package.status_code, 200)
        with tarfile.open(fileobj=io.BytesIO(on_prem_package.content), mode='r:gz') as archive:
            self.assertIsNotNone(archive.getmember('deployment/on-prem/application.json'))
            self.assertIsNotNone(archive.getmember('deployment/on-prem/environment.properties'))
            self.assertIsNotNone(archive.getmember('deployment/on-prem/deploy.sh'))
            self.assertIsNotNone(archive.getmember('deployment/on-prem/install.sh'))
        deleted = self.client.delete('/api/projects/task-runtime-test')
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get('/api/projects/task-runtime-test').status_code, 404)

    def test_dynamic_subtask_override_is_resolved_from_environment_properties(self):
        payload = self.project()
        payload['properties']['local'] = [{'key':'routing.targetTask','value':'Child','data_type':'string'}]
        call = next(item for item in payload['tasks'][0]['activities'] if item['type'] == 'call_task')
        call['config']['taskId'] = 'missing-static-fallback'
        call['config']['dynamicTaskId'] = '${properties.routing.targetTask}'
        self.assertEqual(self.client.post('/api/projects', json=payload).status_code, 200)
        result = self.client.post('/api/projects/task-runtime-test/run', json={'task_id':'main','input':{'value':42},'environment':'local'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['activity_outputs']['c']['output'], {'answer': {'value': 42}})
        self.client.delete('/api/projects/task-runtime-test')

    def test_multi_environment_package_has_common_application_and_profile_specific_descriptors(self):
        payload = self.project()
        payload['properties']['dev'] = [{'key':'service.url','value':'https://dev.example','data_type':'string'}, {'key':'service.password','value':'dev-secret','data_type':'password'}]
        payload['properties']['qa'] = [{'key':'service.url','value':'https://qa.example','data_type':'string'}, {'key':'service.password','value':'qa-secret','data_type':'password'}]
        self.assertEqual(self.client.post('/api/projects', json=payload).status_code, 200)
        response = self.client.get('/api/projects/task-runtime-test/package?target=cloud&environments=dev,qa&archive=ifpkg&artifacts=configmap,secret,deployment,service,package')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(b'dev-secret', response.content); self.assertNotIn(b'qa-secret', response.content)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            self.assertIn('application/project.json', names)
            self.assertIn('environments/dev.json', names); self.assertIn('environments/qa.json', names)
            self.assertIn('deployment/cloud/profiles/dev/configmap.yaml', names)
            self.assertIn('deployment/cloud/profiles/qa/configmap.yaml', names)
            self.assertIn('deployment/cloud/profiles/dev/deployment.yaml', names)
            self.assertIn('deployment/cloud/profiles/qa/secret.yaml', names)
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['environments'], ['dev', 'qa'])
            self.assertEqual(json.loads(archive.read('application/project.json'))['properties'].keys(), {'dev', 'qa'})
            self.assertIn(b'https://dev.example', archive.read('deployment/cloud/profiles/dev/configmap.yaml'))
            self.assertIn(b'https://qa.example', archive.read('deployment/cloud/profiles/qa/configmap.yaml'))
        self.client.delete('/api/projects/task-runtime-test')

    def test_package_includes_selected_starters_and_only_transitive_subtask_dependencies(self):
        payload = self.project()
        payload['tasks'].extend([
            {'id':'secondary','name':'Secondary Starter','kind':'starter','activities':[{'id':'ss','type':'start','name':'Start','position':{'x':0,'y':0},'config':{}},{'id':'se','type':'end','name':'End','position':{'x':1,'y':0},'config':{}}], 'transitions':[{'id':'s1','source':'ss','target':'se'}]},
            {'id':'orphan','name':'Unused Sub Task','kind':'subtask','activities':[{'id':'os','type':'start','name':'Start','position':{'x':0,'y':0},'config':{}},{'id':'oe','type':'end','name':'End','position':{'x':1,'y':0},'config':{}}], 'transitions':[{'id':'o1','source':'os','target':'oe'}]},
        ])
        self.assertEqual(self.client.post('/api/projects', json=payload).status_code, 200)
        response = self.client.get('/api/projects/task-runtime-test/package?target=on-prem&environments=dev&starters=main&archive=ifpkg')
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            self.assertIn('application/tasks/main.json', names)
            self.assertIn('application/tasks/child.json', names)
            self.assertNotIn('application/tasks/secondary.json', names)
            self.assertNotIn('application/tasks/orphan.json', names)
            project = json.loads(archive.read('application/project.json'))
            self.assertEqual([task['id'] for task in project['tasks']], ['main', 'child'])
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['starterTaskIds'], ['main'])
            self.assertEqual(manifest['includedTaskIds'], ['main', 'child'])
        self.client.delete('/api/projects/task-runtime-test')

    def test_project_save_removes_retry_from_non_outbound_activities_only(self):
        payload = self.project()
        retry = {'retryEnabled':True, 'retryCount':3, 'retryIntervalSeconds':5, 'logPayload':False}
        activities = payload['tasks'][0]['activities']
        next(item for item in activities if item['id'] == 'p')['config']['advanced'] = dict(retry)
        next(item for item in activities if item['id'] == 'r')['config']['advanced'] = dict(retry)
        saved = self.client.post('/api/projects', json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        saved_activities = saved.json()['tasks'][0]['activities']
        publish_advanced = next(item for item in saved_activities if item['id'] == 'p')['config']['advanced']
        receive_advanced = next(item for item in saved_activities if item['id'] == 'r')['config']['advanced']
        self.assertIn('retryEnabled', publish_advanced)
        self.assertNotIn('retryEnabled', receive_advanced)
        self.assertEqual(receive_advanced, {'logPayload':False})
        self.client.delete('/api/projects/task-runtime-test')

    def test_dataweave_transform_executes_selectors_defaults_collections_and_xml(self):
        script = '''%dw 2.0
output application/json
var fallback = "Unknown"
---
{ customer: upper(payload.name default fallback), ids: payload.lines map (line) -> line.id }'''
        response = self.client.post('/api/dataweave/test', json={'script':script, 'input':{'name':'ada','lines':[{'id':1},{'id':2}]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['output'], {'customer':'ADA','ids':[1,2]})
        xml = self.client.post('/api/dataweave/test', json={'script':'%dw 2.0\noutput application/xml\n---\n{ order: { id: payload.id } }', 'input':{'id':7}})
        self.assertEqual(xml.status_code, 200, xml.text)
        self.assertEqual(xml.json()['output'], '<order><id>7</id></order>')
        metadata = self.client.post('/api/dataweave/test', json={
            'script':'%dw 2.0\noutput application/json\n---\n{ requestId: attributes.requestId, region: vars.region }',
            'input':{}, 'attributes':{'requestId':'req-7'}, 'variables':{'region':'west'}
        })
        self.assertEqual(metadata.status_code, 200, metadata.text)
        self.assertEqual(metadata.json()['output'], {'requestId':'req-7','region':'west'})
        csv_output = self.client.post('/api/dataweave/test', json={
            'script':'%dw 2.0\noutput text/csv\n---\npayload',
            'input':[{'id':1,'name':'Ada'},{'id':2,'name':'Lin'}]
        })
        self.assertEqual(csv_output.status_code, 200, csv_output.text)
        self.assertEqual(csv_output.json()['output'], 'id,name\n1,Ada\n2,Lin\n')

    def test_dataweave_custom_functions_coercions_and_extended_collections(self):
        script = '''%dw 2.0
output application/json
fun normalize(value: String) = upper(trim(value))
---
{
  name: normalize(payload.name),
  id: payload.id as String,
  numeric: payload.id is Number,
  values: payload.groups flatMap (group) -> group.values,
  wildcard: payload.labels.*,
  entries: payload.labels pluck (value, key) -> { name: key, value: value }
}'''
        response = self.client.post('/api/dataweave/test', json={'script': script, 'input': {
            'name': ' ada ', 'id': 7, 'groups': [{'values': [1, 2]}, {'values': [3]}], 'labels': {'a': 'A', 'b': 'B'},
        }})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['output'], {
            'name': 'ADA', 'id': '7', 'numeric': True, 'values': [1, 2, 3], 'wildcard': ['A', 'B'],
            'entries': [{'name': 'a', 'value': 'A'}, {'name': 'b', 'value': 'B'}],
        })

if __name__ == '__main__': unittest.main()
