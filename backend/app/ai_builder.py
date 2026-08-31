from __future__ import annotations

import json, os, re, uuid
from typing import Any
import httpx
from .models import Activity, ProcessDefinition, SharedResource, TaskDefinition, Transition

CATALOG = {
    'http listener': ('http_listener', 'listen', 'HTTP Listener'), 'rest receiver': ('rest', 'receiver', 'REST API Receiver'),
    'file poller': ('file', 'poll', 'File Poller'), 'timer': ('timer', 'schedule', 'Timer / Scheduler'),
    'ems receiver': ('ems', 'queue_receiver', 'EMS Queue Receiver'), 'jms receiver': ('ems', 'queue_receiver', 'EMS Queue Receiver'),
    'kafka receiver': ('kafka', 'receive', 'Kafka Receive Message'), 'pubsub subscriber': ('pubsub', 'subscribe', 'GCP Pub/Sub Subscriber'),
    'parse xml': ('xml', 'parse', 'Parse XML'), 'render xml': ('xml', 'render', 'Render XML'),
    'parse json': ('json', 'parse', 'Parse JSON'), 'render json': ('json', 'render', 'Render JSON'),
    'parse data': ('flat', 'parse', 'Parse Data'), 'render data': ('flat', 'render', 'Render Data'),
    'jdbc query': ('jdbc', 'query', 'JDBC Query'), 'jdbc update': ('jdbc', 'update', 'JDBC Update'),
    'http request': ('http', 'request', 'HTTP Send Request'), 'rest invoke': ('rest', 'invoke', 'REST API Invoke'),
    'log': ('log', 'write', 'Log'), 'transform': ('transform', 'map', 'Transform'),
    'send response': ('http_response', 'response', 'HTTP Send Response'), 'catch': ('catch', 'catch', 'Catch Exception'),
    'throw': ('throw', 'throw', 'Throw Exception'), 'rethrow': ('rethrow', 'rethrow', 'Rethrow Exception'),
}
EVENT_TYPES = {'http_listener','rest','timer','file','ems','kafka','pubsub','sap','start'}

def _slug(value: str, fallback='activity') -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-') or fallback

def local_proposal(requirement: str, scope: str, current_task: dict | None = None) -> dict[str, Any]:
    lower = requirement.lower(); selected = []
    if 'rest' in lower and any(word in lower for word in ('receive','receiver','expose','host')): selected.append(CATALOG['rest receiver'])
    elif 'http' in lower and any(word in lower for word in ('receive','receiver','listen','host')): selected.append(CATALOG['http listener'])
    for phrase, definition in CATALOG.items():
        if phrase in lower and definition not in selected: selected.append(definition)
    if ('response' in lower or 'reply' in lower) and any(item[0] in ('rest','http_listener') for item in selected) and CATALOG['send response'] not in selected: selected.append(CATALOG['send response'])
    events = [item for item in selected if item[0] in EVENT_TYPES and (item[0] != 'file' or item[1] == 'poll')]
    if not events: selected.insert(0, ('start', 'start', 'Manual Start'))
    elif len(events) > 1:
        keep = events[0]; selected = [item for item in selected if item not in events or item == keep]
    if not any(item[0] == 'end' for item in selected): selected.append(('end', 'end', 'End'))
    if selected[-1][0] != 'end': selected.append(('end', 'end', 'End'))
    activities, transitions = [], []
    for index, (kind, operation, label) in enumerate(selected):
        activity_id = f'{_slug(label)}-{index + 1}'
        config: dict[str, Any] = {'operation': operation}
        if kind in ('http_listener','rest') and operation == 'receiver': config.update({'path':'/api/resource','methods':'POST'})
        if kind == 'http_listener': config.update({'path':'/api/resource','method':'POST'})
        if kind == 'catch': config['catchAll'] = True
        activities.append({'id':activity_id,'type':kind,'name':label,'position':{'x':80 + index * 190,'y':100 if kind != 'catch' else 260},'config':config})
    main_track = [item for item in activities if item['type'] != 'catch']
    for index in range(len(main_track)-1):
        transitions.append({'id':f'ai-edge-{index + 1}','source':main_track[index]['id'],'target':main_track[index+1]['id'],'type':'success','label':'success','condition':''})
    task_name = (current_task or {}).get('name') if scope == 'task' else 'AI Generated Task'
    task = {'id':(current_task or {}).get('id','ai-main-task'),'name':task_name or 'AI Generated Task','kind':(current_task or {}).get('kind','starter'),'description':requirement,'activities':activities,'transitions':transitions,'input_schema':{},'output_schema':{}}
    resource_types = []
    for activity in activities:
        candidate = {'jdbc':'jdbc','http':'http','http_listener':'http','rest':'http','ems':'ems','kafka':'kafka','pubsub':'pubsub'}.get(activity['type'])
        if candidate:
            activity['config']['resourceId'] = f'ai-{candidate}-connection'
            if candidate not in resource_types: resource_types.append(candidate)
    resources = [{'id':f'ai-{kind}-connection','type':kind,'name':f'{kind.upper()} Connection','config':{}} for kind in resource_types]
    return {'provider':'local-blueprint','summary':f'Generated {len(activities)} activities and {len(resources)} shared connections. Review configuration and mappings before applying.','scope':scope,'project':{'name':'AI Generated Integration','description':requirement,'tasks':[task],'resources':resources,'schemas':[],'packaging':{'artifact_name':'ai-generated-integration','version':'1.0.0','format':'ifpkg','target':'on-prem','environment':'production'}}}

def _schema() -> dict[str, Any]:
    activity = {'type':'object','additionalProperties':False,'required':['id','type','name','position','config'],'properties':{'id':{'type':'string'},'type':{'type':'string'},'name':{'type':'string'},'position':{'type':'object','additionalProperties':False,'required':['x','y'],'properties':{'x':{'type':'number'},'y':{'type':'number'}}},'config':{'type':'object','additionalProperties':True}}}
    transition = {'type':'object','additionalProperties':False,'required':['id','source','target','type','label','condition'],'properties':{'id':{'type':'string'},'source':{'type':'string'},'target':{'type':'string'},'type':{'type':'string','enum':['success','success_condition','success_no_match','error']},'label':{'type':'string'},'condition':{'type':'string'}}}
    task = {'type':'object','additionalProperties':False,'required':['id','name','kind','description','activities','transitions','input_schema','output_schema'],'properties':{'id':{'type':'string'},'name':{'type':'string'},'kind':{'type':'string','enum':['starter','subtask']},'description':{'type':'string'},'activities':{'type':'array','items':activity},'transitions':{'type':'array','items':transition},'input_schema':{'type':'object','additionalProperties':True},'output_schema':{'type':'object','additionalProperties':True}}}
    resource = {'type':'object','additionalProperties':False,'required':['id','type','name','config'],'properties':{'id':{'type':'string'},'type':{'type':'string','enum':['jdbc','ftp','sftp','http','ems','kafka','pubsub','sap','sap_tid']},'name':{'type':'string'},'config':{'type':'object','additionalProperties':True}}}
    return {'type':'object','additionalProperties':False,'required':['summary','project'],'properties':{'summary':{'type':'string'},'project':{'type':'object','additionalProperties':False,'required':['name','description','tasks','resources','schemas','packaging'],'properties':{'name':{'type':'string'},'description':{'type':'string'},'tasks':{'type':'array','items':task},'resources':{'type':'array','items':resource},'schemas':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['id','name','content'],'properties':{'id':{'type':'string'},'name':{'type':'string'},'content':{'type':'string'}}}},'packaging':{'type':'object','additionalProperties':True}}}}}

async def generate(requirement: str, scope='task', current_task: dict | None = None) -> dict[str, Any]:
    key = os.getenv('OPENAI_API_KEY')
    if not key: return local_proposal(requirement, scope, current_task)
    model = os.getenv('INTEGRATION_FABRIC_AI_MODEL', 'gpt-5')
    prompt = f'''Build an Integration Fabric middleware {scope} from this requirement:\n{requirement}\nUse only these activity types and operations: {json.dumps(CATALOG)}. A starter task must have exactly one event activity. Catch activities have no incoming transition. Add explicit HTTP Send Response for request/reply listeners. Return a fully connected, editable design; do not include credentials.'''
    payload = {'model':model,'input':prompt,'text':{'format':{'type':'json_schema','name':'integration_fabric_design','strict':False,'schema':_schema()}}}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post('https://api.openai.com/v1/responses', headers={'authorization':f'Bearer {key}','content-type':'application/json'}, json=payload)
        response.raise_for_status(); body = response.json()
    text = ''.join(item.get('text','') for output in body.get('output',[]) for item in output.get('content',[]) if item.get('type') == 'output_text')
    proposal = json.loads(text); proposal.update({'provider':'openai','scope':scope})
    for task_data in proposal['project']['tasks']: TaskDefinition.model_validate(task_data)
    for resource in proposal['project']['resources']: SharedResource.model_validate(resource)
    return proposal
