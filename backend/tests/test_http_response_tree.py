import json
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


def fixture(port, kind='http_listener'):
    return Project.model_validate({'id':'response-tree','name':'Response-Tree','active_task_id':'main',
        'resources':[{'id':'server','name':'Server','type':'http','config':{'connectorMode':'server',
            'host':'127.0.0.1','port':port,'minimumQtpThreads':1,'maximumQtpThreads':2}}],
        'tasks':[{'id':'main','name':'Main','kind':'starter','activities':[
            {'id':'Receive','name':'Receive','type':kind,'config':{'resourceId':'server','path':'/reply',
                'operation':'receiver' if kind=='rest' else 'listen','methods':'GET'}},
            {'id':'Reply','name':'Reply','type':'http_response','config':{'statusCode':200,
                'headers':{'X-Legacy':'kept','X-Trace':'old'},'inputMappings':{
                    'HTTPHeaders.Content-Type':'${input.headers.x-response-type}',
                    'HTTPHeaders.StatusLine':'"HTTP/1.1 201 Created"',
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
        headers={'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json'}
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
                            assert_response(self,live.get(f'http://127.0.0.1:{port}/reply',headers=headers))
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
                    response=await client.get('http://127.0.0.1:{port}/reply',headers={{'X-Trace':'first','X-Response-Type':'application/vnd.mina.reply+json'}},timeout=.3)
                    break
                except (httpx.ConnectError,httpx.ConnectTimeout):await asyncio.sleep(.05)
            else:raise AssertionError('Listener did not start')
            assert response.status_code==201,response.text
            assert response.json()=={{'ok':True}},response.text
            assert response.headers['content-type']=='application/vnd.mina.reply+json',response.headers
            assert response.headers.get_list('x-trace')==['first','second'],response.headers
            assert response.headers['x-legacy']=='kept'
            assert response.headers.get_list('set-cookie')==['a=1; Path=/; HttpOnly','b=2; Path=/','c=3; Path=/'],response.headers
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
