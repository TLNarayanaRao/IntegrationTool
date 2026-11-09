import asyncio,json,unittest
import httpx
from app.models import Activity,Project
from app.runtime import WorkflowRuntime
from tests.test_http_activity_e2e import upstream

SPEC={'openapi':'3.0.3','paths':{'/orders':{'post':{'operationId':'create','requestBody':{'required':True,'content':{'application/json':{'schema':{'type':'object','required':['name']}}}},'responses':{'200':{'description':'Created','content':{'application/json':{'schema':{'type':'object','required':['id']}}}}}}}}}

class DynamicHTTPTests(unittest.TestCase):
    def test_xml_xsd_request_and_response_contracts_are_mappable(self):
        from tests.test_format_activities import XSD
        from app.http_messages import request_config
        from app.http_transport import request
        config=request_config({'baseUrl':'http://provider.test','RestInputRequest':{'Config':{'Method':'POST','requestURI':'/orders','RequestBody':'<order id="A"><quantity>2</quantity></order>','validateRequest':True,'requestSchema':XSD,'validateResponse':True,'responseSchema':XSD},'Headers':{'content-type':'application/xml'}}})
        with upstream(lambda req:httpx.Response(200,text=req.content.decode(),headers={'Content-Type':'application/xml'})):
            self.assertIn('<quantity>2</quantity>',request(config)['body'])
            config['RestInputRequest']['Config']['RequestBody']='<order id="A"><quantity>-2</quantity></order>'
            with self.assertRaisesRegex(ValueError,'schema validation'):request(config)

    def test_http_and_rest_accept_contract_and_validation_settings_from_input(self):
        runtime=WorkflowRuntime();payload={'spec':SPEC,'operation':'create','body':{'name':'MINA'},'schema':{'type':'object','required':['name']}}
        for kind in ('http','rest'):
            activity=Activity(id='Call',name='Call',type=kind,config={'operation':'invoke' if kind=='rest' else 'request','baseUrl':'http://provider.test','requestModel':'tree','inputMappings':{'RestInputRequest.Config.openApiDocument':'${input.spec}','RestInputRequest.Config.operationId':'${input.operation}','RestInputRequest.Config.validateRequest':'true','RestInputRequest.Config.requestSchema':'${input.schema}','RestInputRequest.Config.validateResponse':'true','RestInputRequest.Config.responseSchema':'{"type":"object"}','RestInputRequest.Config.RequestBody':'${input.body}'}})
            def reply(request):
                self.assertEqual(request.method,'POST');self.assertEqual(request.url.path,'/orders');self.assertEqual(json.loads(request.content),payload['body'])
                return httpx.Response(200,json={'id':7})
            ctx={'last':payload,'input':payload,'properties':{},'vars':{},'context':{},'activities':{},'tasks':{},'resources':{},'project':None}
            with self.subTest(kind=kind),upstream(reply):
                result=asyncio.run(runtime.execute(activity,ctx));self.assertEqual(result['body'],{'id':7})
            with self.subTest(kind=kind+' invalid'):
                ctx['input']={**payload,'body':{'wrong':'field'}}
                with self.assertRaisesRegex(ValueError,'schema validation'):asyncio.run(runtime.execute(activity,ctx))
