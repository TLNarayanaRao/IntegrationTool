import json
import asyncio
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.http_messages import response_message
from app.models import Project
from app.raw_python import raw_python_files, engine_python_files
from app.runtime import WorkflowRuntime


def fixture(port, kind='http_listener'):
    return Project.model_validate({'id':'response-tree','name':'Response-Tree','active_task_id':'main',
        'resources':[{'id':'server','name':'Server','type':'http','config':{'connectorMode':'server',
            'host':'127.0.0.1','port':port,'minimumQtpThreads':1,'maximumQtpThreads':2}}],
        'tasks':[{'id':'main','name':'Main','kind':'starter','activities':[
            {'id':'Receive','name':'Receive','type':kind,'config':{'resourceId':'server','path':'/reply',
                'operation':'receiver' if kind=='rest' else 'listen','methods':'GET',
                'requestParameters':[{'in':'query','name':'status','type':'integer'}]}},
            {'id':'Reply','name':'Reply','type':'http_response','config':{'statusCode':200,
                'headers':{'X-Legacy':'kept','X-Trace':'old'},'inputMappings':{
                    'HTTPHeaders.Content-Type':'${input.headers.x-response-type}',
                    'HTTPHeaders.StatusLine.httpVersion':'${input.headers.x-version}',
                    'HTTPHeaders.StatusLine.statusCode':'${input.query.status}',
                    'HTTPHeaders.StatusLine.reasonPhrase':'${input.headers.x-reason}',
                    'HTTPHeaders.Cookies':'["a=1; Path=/; HttpOnly","b=2; Path=/"]',
                    'DynamicHTTPHeaders.Headers.0':'{}',
                    'DynamicHTTPHeaders.Headers.0.headerName':'"X-Trace"',
                    'DynamicHTTPHeaders.Headers.0.headerValue':'${input.headers.x-trace}',
                    'DynamicHTTPHeaders.Headers.1':'{}',
                    'DynamicHTTPHeaders.Headers.1.headerName':'"x-trace"',
                    'DynamicHTTPHeaders.Headers.1.headerValue':'"second"',
                    'DynamicHTTPHeaders.Headers.2':'{}',
                    'DynamicHTTPHeaders.Headers.2.headerName':'"Set-Cookie"',
                    'DynamicHTTPHeaders.Headers.2.headerValue':'"c=3; Path=/"',
                    'body':'{"ok":true}'}}}],
            'transitions':[{'id':'next','source':'Receive','target':'Reply'}]}]})


def assert_response(test,response):
    test.assertEqual(response.status_code,201,response.text)
    test.assertEqual(response.headers['content-type'],'application/vnd.mina.reply+json')
    test.assertEqual(response.json(),{'ok':True})
    test.assertEqual(response.headers.get_list('x-trace'),['first','second'])
    test.assertEqual(response.headers['x-legacy'],'kept')
    test.assertEqual(response.headers.get_list('set-cookie'),['a=1; Path=/; HttpOnly','b=2; Path=/','c=3; Path=/'])
    test.assertNotIn('statusline',response.headers)
    test.assertNotIn('cookies',response.headers)


class ResponseTreeTests(unittest.TestCase):
    def test_optional_defaults_and_legacy_fields(self):
        self.assertEqual(response_message({},'last'),{'statusCode':200,'headers':{},'body':'last'})
        result=response_message({'statusCode':202,'contentType':'text/plain','headers':{'X-Old':'ok'},
                                 'body':'reply','HTTPHeaders':{},'DynamicHTTPHeaders':{'Headers':[{}]}})
        self.assertEqual(result,{'statusCode':202,'headers':{'x-old':'ok','content-type':'text/plain'},'body':'reply'})

    def test_singleton_indexed_headers_and_statusline(self):
        self.assertEqual(response_message({'headers':{'Content-Type':['text/plain']}})['headers']['content-type'],'text/plain')
        for entries in ({'headerName':'X-Test','headerValue':''},{'0':{'headerName':'X-Test','headerValue':''}}):
            result=response_message({'HTTPHeaders':{'StatusLine':'204 No Content','Cookies':'a=1'},
                'DynamicHTTPHeaders':{'Headers':entries}})
            self.assertEqual(result['statusCode'],204)
            self.assertEqual(result['headers'],{'set-cookie':'a=1','x-test':''})

    def test_structured_statusline_partial_defaults_and_validation(self):
        for line in ({},{'httpVersion':'2'},{'reasonPhrase':'Custom description'}, {'statusCode':None}):
            result=response_message({'statusCode':202,'HTTPHeaders':{'StatusLine':line}})
            self.assertEqual(result['statusCode'],202)
            self.assertEqual(result['statusLine']['statusCode'],202)
        for version in ('1.0','1.1','2','2.0','3','3.0','HTTP/1.1','HTTP/2','HTTP/3'):
            result=response_message({'HTTPHeaders':{'StatusLine':{'httpVersion':version,'statusCode':201,'reasonPhrase':'Created'}}})
            self.assertEqual(result['statusCode'],201)
            self.assertEqual(result['statusLine'],{'httpVersion':version if version.startswith('HTTP/') else 'HTTP/'+version,'statusCode':201,'reasonPhrase':'Created'})
        for line in ({'httpVersion':'HTTP/4'}, {'httpVersion':2}, {'httpVersion':'HTTP/1.1\r\nInjected'},
                     {'statusCode':False}, {'statusCode':201.5}, {'statusCode':999},
                     {'reasonPhrase':'Bad\r\nHeader: value'}, {'reasonPhrase':'Bad\x00'}, {'reasonPhrase':12}, {'reasonPhrase':'\u2603'}):
            with self.subTest(line=line),self.assertRaises(ValueError):response_message({'HTTPHeaders':{'StatusLine':line}})

    def test_runtime_retains_all_independently_mapped_status_fields(self):
        project=fixture(8080)
        payload={'query':{'status':202},'headers':{'x-version':'2','x-reason':'Queued by integration',
                  'x-response-type':'application/json','x-trace':'test'}}
        result=asyncio.run(WorkflowRuntime().run(project.tasks[0],payload,{item.id:item for item in project.resources},{},project=project))
        self.assertEqual(result.status,'completed',result.logs)
        self.assertEqual(result.output['statusCode'],202)
        self.assertEqual(result.output['statusLine'],{'httpVersion':'HTTP/2','statusCode':202,'reasonPhrase':'Queued by integration'})

    def test_invalid_mapped_response_headers_and_status_fail(self):
        cases=[{'HTTPHeaders':{'StatusLine':'HTTP/1.1 200 OK\r\nX: injected'}},
            {'headers':{'Content-Type':['text/plain','application/json']}},
            {'HTTPHeaders':{'StatusLine':'999 Invalid'}}, {'statusCode':True},
            {'HTTPHeaders':{'Cookies':['good=1','bad=2\nInjected: yes']}},
            {'DynamicHTTPHeaders':{'Headers':[{'headerName':'X Bad','headerValue':'a'}]}},
            {'DynamicHTTPHeaders':{'Headers':[{'headerName':'X-Test'}]}},
            {'DynamicHTTPHeaders':{'Headers':[{'headerValue':'missing-name'}]}},
            {'DynamicHTTPHeaders':{'Headers':[{'headerName':'X-Test','headerValue':'\r\ninjected'}]}},
            {'DynamicHTTPHeaders':{'Headers':'invalid'}},
            {'DynamicHTTPHeaders':{'Headers':[{'headerName':'Content-Type','headerValue':'text/plain'},
                                             {'headerName':'content-type','headerValue':'application/json'}]}}]
        for config in cases:
            with self.subTest(config=config),self.assertRaises(ValueError):response_message(config)

    def test_studio_run_debug_and_http_rest_listeners_send_structured_fields(self):
        from app import main
        headers={'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json','X-Version':'1.1','X-Reason':'Stored by integration'}
        for kind in ('http_listener','rest'):
            for mode in ('run','debug'):
                with self.subTest(kind=kind,mode=mode),socket.socket() as probe:
                    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                project=fixture(port,kind)
                with patch.object(main,'get_project',return_value=project),patch.object(main,'append_project_logs'),TestClient(main.app) as client:
                    started=client.post(f'/api/projects/{project.id}/{mode}',json={'task_id':'main'})
                    self.assertEqual(started.status_code,200,started.text)
                    try:
                        with httpx.Client(trust_env=False,timeout=5) as live:
                            response=live.get(f'http://127.0.0.1:{port}/reply?status=201',headers=headers)
                            assert_response(self,response)
                            self.assertEqual(response.reason_phrase,'Stored by integration')
                            self.assertEqual(live.get(f'http://127.0.0.1:{port}/reply?status=202',headers=headers).status_code,202)
                            downgraded=live.get(f'http://127.0.0.1:{port}/reply?status=201',headers={**headers,'X-Version':'1.0','X-Reason':'HTTP ten reply'})
                            self.assertEqual(downgraded.http_version,'HTTP/1.0')
                            self.assertEqual(downgraded.reason_phrase,'HTTP ten reply')
                            self.assertEqual(downgraded.headers['connection'],'close')
                            assert_response(self,downgraded)
                            normal=live.get(f'http://127.0.0.1:{port}/reply?status=201',headers=headers)
                            self.assertEqual(normal.http_version,'HTTP/1.1')
                            self.assertEqual(normal.reason_phrase,'Stored by integration')
                            rejected=live.get(f'http://127.0.0.1:{port}/reply?status=201',headers={**headers,'X-Version':'2'})
                            self.assertEqual(rejected.status_code,500)
                            self.assertIn('unsupported',rejected.json()['error'])
                            empty_reason=live.get(f'http://127.0.0.1:{port}/reply?status=201',headers={**headers,'X-Reason':''})
                            self.assertEqual(empty_reason.reason_phrase,'')
                            for status in (204,304):
                                bodyless=live.get(f'http://127.0.0.1:{port}/reply?status={status}',headers={**headers,'X-Version':'1.0'})
                                self.assertEqual((bodyless.http_version,bodyless.status_code,bodyless.content),('HTTP/1.0',status,b''))
                            head=live.head(f'http://127.0.0.1:{port}/reply?status=201',headers={**headers,'X-Version':'1.0'})
                            self.assertEqual((head.http_version,head.status_code,head.content),('HTTP/1.0',201,b''))
                        if kind=='http_listener' and mode=='run':
                            with socket.create_connection(('127.0.0.1',port),timeout=3) as raw:
                                raw.sendall(b'GET /reply?status=201 HTTP/1.1\r\nHost: localhost\r\nX-Version: 1.0\r\nX-Reason: Raw mapped reply\r\nX-Trace: first\r\nX-Response-Type: application/vnd.mina.reply+json\r\n\r\n')
                                chunks=[]
                                while True:
                                    chunk=raw.recv(65536)
                                    if not chunk:break
                                    chunks.append(chunk)
                            wire=b''.join(chunks);headers_bytes,body=wire.split(b'\r\n\r\n',1)
                            self.assertTrue(wire.startswith(b'HTTP/1.0 201 Raw mapped reply\r\n'))
                            self.assertEqual(json.loads(body),{'ok':True})
                            content_length=next(line.split(b':',1)[1].strip() for line in headers_bytes.split(b'\r\n')[1:] if line.lower().startswith(b'content-length:'))
                            self.assertEqual(int(content_length),len(body))
                    finally:
                        if mode=='debug':client.post(f"/api/debug/{started.json()['sessionId']}/action",json={'action':'stop'})
                        else:client.post(f'/api/projects/{project.id}/stop')
                main.runtime_states.pop(project.id,None)

    def test_both_python_archives_send_structured_headers_on_wire(self):
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(archive=compiler.__name__),socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            project=fixture(port)
            with tempfile.TemporaryDirectory() as folder:
                for name,data in compiler(project.model_dump(),{'local':[]}).items():
                    target=Path(folder)/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                script=f'''import asyncio,httpx
from application.main import run_application
async def main():
    job=asyncio.create_task(run_application('local'))
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for attempt in range(100):
                if job.done():await job
                try:
                    response=await client.get('http://127.0.0.1:{port}/reply?status=201',headers={{'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json','X-Version':'1.1','X-Reason':'Stored by integration'}},timeout=.3)
                    break
                except (httpx.ConnectError,httpx.ConnectTimeout):await asyncio.sleep(.05)
            else:raise AssertionError('Listener did not start')
            assert response.status_code==201,response.text
            assert response.reason_phrase=='Stored by integration',response.reason_phrase
            assert response.json()=={{'ok':True}},response.text
            assert response.headers['content-type']=='application/vnd.mina.reply+json',response.headers
            assert response.headers.get_list('x-trace')==['first','second'],response.headers
            assert response.headers['x-legacy']=='kept'
            assert response.headers.get_list('set-cookie')==['a=1; Path=/; HttpOnly','b=2; Path=/','c=3; Path=/'],response.headers
            second=await client.get('http://127.0.0.1:{port}/reply?status=202',headers={{'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json','X-Version':'1.1','X-Reason':'Stored by integration'}})
            assert second.status_code==202,second.text
            downgraded=await client.get('http://127.0.0.1:{port}/reply?status=201',headers={{'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json','X-Version':'1.0','X-Reason':'Archived HTTP ten'}})
            assert downgraded.http_version=='HTTP/1.0',downgraded.http_version
            assert downgraded.reason_phrase=='Archived HTTP ten',downgraded.reason_phrase
            assert downgraded.headers['connection']=='close'
            assert downgraded.json()=={{'ok':True}},downgraded.text
            rejected=await client.get('http://127.0.0.1:{port}/reply?status=201',headers={{'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json','X-Version':'2','X-Reason':'Invalid upgrade'}})
            assert rejected.status_code==500 and 'unsupported' in rejected.json()['error'],rejected.text
    finally:
        job.cancel()
        try:await job
        except asyncio.CancelledError:pass
asyncio.run(main())
'''
                driver=Path(folder)/'check_response.py';driver.write_text(script,encoding='utf-8')
                result=subprocess.run([sys.executable,str(driver)],cwd=folder,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
