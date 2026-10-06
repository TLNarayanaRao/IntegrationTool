import asyncio,base64,json,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from email.parser import BytesParser
from email import policy
from app.http_messages import request_config,mime_body
from app.http_transport import request,HTTPFault,close_clients
from app.models import Project
from app.runtime import WorkflowRuntime
from app.raw_python import raw_python_files,engine_python_files

class Echo(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    do_GET=lambda self:self.do_POST()
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
        if self.path.startswith('/mime-output'):
            body,kind=mime_body({'mimePart':[{'mimeHeaders':{'content-type':'text/plain'},'textContent':'reply'},{'binaryContent':base64.b64encode(b'\x00\xff').decode()}]},100000)
        else:
            body=json.dumps({'path':self.path,'method':self.command,'headers':{key.lower():self.headers.get_all(key) for key in self.headers},'body':raw.decode()}).encode();kind='application/json'
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Set-Cookie','a=1');self.send_header('Set-Cookie','b=2');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

class RequestTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Echo);cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start();cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):close_clients();cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def test_config_headers_query_and_response_tree(self):
        root={'Config':{'host':'127.0.0.1','port':self.server.server_port,'Method':'POST','requestURI':'/echo?first=one','QueryString':'second=two%20words','RequestBody':False},'Headers':{'accept':'application/json','content-type':'application/json','Accept-Charset':'utf-8','Cookie':'a=1','DynamicHeaders':[{'name':'X-Custom','value':'one'},{'name':'X-Custom','value':'two'},{'name':'Accept','value':'text/plain'}]}}
        result=request({'RestInputRequest':root},{'baseUrl':'http://old.example:1234','headers':{'X-Shared':'default'},'timeout':2})
        value=result['body'];self.assertEqual(value['method'],'POST');self.assertEqual(value['body'],'false');self.assertEqual(value['path'],'/echo?first=one&second=two+words')
        self.assertEqual(value['headers']['x-custom'],['one','two']);self.assertEqual(value['headers']['accept'],['text/plain']);self.assertEqual(value['headers']['x-shared'],['default'])
        self.assertEqual(value['headers']['content-type'],['application/json'])
        output=result['RestOutputResponse'];self.assertEqual(output['statusLine']['statusCode'],200);self.assertEqual(output['statusLine']['reasonPhrase'],'OK');self.assertEqual(output['Headers']['Set-Cookie'],['a=1','b=2']);self.assertEqual(output['body'],value)
    def test_manual_repeated_headers_and_mime_attachments(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'attachment.bin';file.write_bytes(b'file payload')
            envelope={'mimePart':{'0':{'mimeHeaders':{'content-type':'text/plain','content-id':'part-one'},'textContent':'hello'},'1':{'binaryContent':base64.b64encode(b'\x00\xff').decode()},'2':{'fileName':str(file)}}}
            root={'Config':{'requestURI':self.base+'/echo','Method':'POST'},'Headers':{'DynamicHeaders':{'0':{'name':'X-A','value':'one'},'1':{'name':'X-B','value':'two'}}},'mimeEnvelopeElement':envelope}
            result=request({'RestInputRequest':root});body=result['body'];self.assertEqual(body['headers']['x-a'],['one']);self.assertEqual(body['headers']['x-b'],['two'])
            message=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+body['headers']['content-type'][0]+'\r\n\r\n').encode()+body['body'].encode())
            parts=list(message.iter_parts());self.assertEqual(len(parts),3);self.assertEqual(parts[0].get_payload(decode=True),b'hello');self.assertEqual(parts[1].get_payload(decode=True),b'\x00\xff');self.assertEqual(parts[2].get_payload(decode=True),b'file payload')
    def test_multipart_response_decodes_into_output_tree(self):
        result=request({'RestInputRequest':{'Config':{'requestURI':self.base+'/mime-output'}}})
        parts=result['RestOutputResponse']['mimeEnvelopeElement']['mimePart'];self.assertEqual(parts[0]['textContent'],'reply');self.assertEqual(base64.b64decode(parts[1]['binaryContent']),b'\x00\xff')
    def test_invalid_header_pairs_and_mime_choices_fail_before_sending(self):
        for headers in ({'DynamicHeaders':[{'name':'Accept','value':'a'},{'name':'accept','value':'b'}]},{'DynamicHeaders':[{'name':'Bad\r\nName','value':'x'}]},{'DynamicHeaders':[{'name':'X-Name','value':'é'}]},{'DynamicHeaders':[{'name':'X-Name'}]}):
            with self.assertRaises(HTTPFault):request({'RestInputRequest':{'Config':{'requestURI':self.base},'Headers':headers}})
        for part in ({'textContent':'a','binaryContent':'Yg=='},{'binaryContent':'not base64'},{'mimeHeaders':{'content-id':'empty'}}):
            with self.assertRaises(HTTPFault):request({'RestInputRequest':{'Config':{'requestURI':self.base},'mimeEnvelopeElement':{'mimePart':[part]}}})
        cfg=request_config({'RestInputRequest':{'Config':{'timeout':1500}},'timeout':20});self.assertEqual(cfg['socketTimeoutMs'],1500);self.assertNotIn('timeout',cfg)
    def test_studio_and_both_archives_execute_tree_mappings(self):
        for kind in ('http','rest'):
            mappings={'RestInputRequest.Config.host':'${properties.http.host}','RestInputRequest.Config.port':'${properties.http.port}','RestInputRequest.Config.Method':'"POST"','RestInputRequest.Config.requestURI':'"/echo"','RestInputRequest.Config.RequestBody':'${input.body}','RestInputRequest.Headers.DynamicHeaders':{'$rule':'for-each','source':'${input.headers}'}}
            project={'id':'request-tree','name':'Request Tree','properties':{'local':[{'key':'http.host','value':'127.0.0.1','data_type':'string'},{'key':'http.port','value':self.server.server_port,'data_type':'integer'}]},'resources':[{'id':'http','name':'HTTP','type':'http','config':{'connectorMode':'client','scheme':'http'}}],'tasks':[{'id':'main','name':'Main','kind':'starter','groups':[],'activities':[{'id':'Start','name':'Start','type':'start','config':{}},{'id':'Call','name':'Call','type':kind,'config':{'operation':'request' if kind=='http' else 'invoke','resourceId':'http','requestModel':'tree','inputMappings':mappings}},{'id':'End','name':'End','type':'end','config':{}}],'transitions':[{'id':'a','source':'Start','target':'Call'},{'id':'b','source':'Call','target':'End'}]}]}
            payload={'body':{'active':False},'headers':[{'name':'X-A','value':'one'},{'name':'X-B','value':'two'}]};model=Project.model_validate(project)
            result=asyncio.run(WorkflowRuntime().run(model.tasks[0],payload,{value.id:value for value in model.resources},{'http.host':'127.0.0.1','http.port':self.server.server_port},project=model));self.assertEqual(result.status,'completed',result.logs)
            self.assertEqual(result.output['RestOutputResponse']['body']['headers']['x-b'],['two'])
            for compiler in (raw_python_files,engine_python_files):
                with self.subTest(kind=kind,compiler=compiler.__name__),tempfile.TemporaryDirectory() as folder:
                    for name,data in compiler(project,project['properties']).items():
                        path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    command=[sys.executable,'run.py'] if compiler is raw_python_files else [sys.executable,'-m','application.main']
                    run=subprocess.run([*command,'--task','main','--input',json.dumps(payload)],cwd=folder,capture_output=True,text=True,timeout=30)
                    self.assertEqual(run.returncode,0,run.stderr);output=json.loads(run.stdout);self.assertEqual(output['RestOutputResponse']['body']['headers']['x-a'],['one'])
