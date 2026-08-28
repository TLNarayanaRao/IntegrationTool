import io, json, unittest, zipfile
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
                    {'id':'cs','type':'start','name':'Start','position':{'x':0,'y':0},'config':{}},
                    {'id':'ce','type':'end','name':'End','position':{'x':1,'y':0},'config':{}}],
                 'transitions':[{'id':'c1','source':'cs','target':'ce'}]}
            ],'active_task_id':'main'
        }

    def test_subtask_messaging_export_import_and_debug(self):
        payload = self.project()
        self.assertEqual(self.client.post('/api/projects', json=payload).status_code, 200)
        result = self.client.post('/api/projects/task-runtime-test/run', json={'task_id':'main','input':{'value':42},'environment':'local'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'completed')
        self.assertEqual(result.json()['output']['count'], 1)
        exported = self.client.get('/api/projects/task-runtime-test/export')
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertIn('tasks/child.json', archive.namelist())
            self.assertIn('resources/kafka/k1.json', archive.namelist())
        imported = self.client.post('/api/projects/import', files={'file':('project.ifproject', exported.content, 'application/zip')})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(len(imported.json()['tasks']), 2)
        debug = self.client.post('/api/projects/task-runtime-test/debug', json={'task_id':'main','input':{},'breakpoints':['c']})
        self.assertEqual(debug.status_code, 200)
        stepped = self.client.post(f"/api/debug/{debug.json()['sessionId']}/action", json={'action':'step_over'})
        self.assertEqual(stepped.status_code, 200)
        self.assertEqual(stepped.json()['currentActivityId'], 'c')
        json_file = self.client.get('/api/projects/task-runtime-test/json')
        self.assertEqual(json_file.status_code, 200)
        self.assertEqual(json.loads(json_file.content)['id'], 'task-runtime-test')
        deleted = self.client.delete('/api/projects/task-runtime-test')
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get('/api/projects/task-runtime-test').status_code, 404)

if __name__ == '__main__': unittest.main()
