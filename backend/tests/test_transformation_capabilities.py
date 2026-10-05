import copy
import asyncio
import threading
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.mapper import execute, execute_async, apply_function, validate_output
from app.message_state import operate
from app.raw_python import raw_python_files, engine_python_files
from app.transformation import differences, execute_batches, read_template, run_cases, schema_impact, template


class TransformationCapabilityTests(unittest.TestCase):
    def test_json_patterns_formats_properties_and_conditional_contracts(self):
        schema = {'type':'object', 'patternProperties':{'^code_':{'type':'string','pattern':'^[A-Z]{2}$'}}, 'additionalProperties':False}
        self.assertEqual(validate_output({'code_country':'US'},schema), [])
        for value in ({'code_country':'usa'}, {'other':'US'}, {'code_country':1}): self.assertTrue(validate_output(value,schema))
        for kind, valid, invalid in [('date','2024-02-29','2025-02-29'),('date-time','2025-10-05T12:20:30Z','2025-10-05'),('time','12:20:30+02:00','30:20:30Z'),('ipv4','127.0.0.1','256.1.1.1'),('ipv6','::1','hello'),('uuid','1de5ab20-2311-4121-9511-35d6bb55fef1','wrong'),('email','a@example.com','wrong'),('hostname','example.com','-bad.test'),('uri','https://example.com','relative/path')]:
            with self.subTest(format=kind):
                self.assertEqual(validate_output(valid,{'type':'string','format':kind}), [])
                self.assertTrue(validate_output(invalid,{'type':'string','format':kind}))
        conditional={'if':{'required':['card']},'then':{'required':['billing']},'dependentRequired':{'card':['billing']}}
        self.assertTrue(validate_output({'card':1},conditional))
        self.assertEqual(validate_output({'card':1,'billing':'here'},conditional),[])
        self.assertTrue(validate_output([1,2],{'type':'array','contains':{'const':3}}))

    def test_pattern_timeout_fails_closed(self):
        with patch('regex.search', side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError,'timed out'): validate_output('payload',{'type':'string','pattern':'a'})
        with patch('app.mapper.clock.monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(ValueError,'Contract validation deadline'): validate_output('value',{'type':'string'})

    def test_xsd_restriction_facets(self):
        schema='''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="Root"><xs:complexType><xs:sequence>
        <xs:element name="code"><xs:simpleType><xs:restriction base="xs:string"><xs:length value="2"/><xs:pattern value="[A-Z]{2}"/><xs:enumeration value="US"/><xs:enumeration value="IN"/></xs:restriction></xs:simpleType></xs:element>
        <xs:element name="amount"><xs:simpleType><xs:restriction base="xs:decimal"><xs:minInclusive value="0"/><xs:maxExclusive value="10"/><xs:fractionDigits value="2"/></xs:restriction></xs:simpleType></xs:element>
        </xs:sequence></xs:complexType></xs:element></xs:schema>'''
        self.assertEqual(validate_output({'Root':{'code':'US','amount':1.25}},schema),[])
        for code,amount in [('usa',1.25),('UK',1),('US',-1),('US',10),('US',1.234)]: self.assertTrue(validate_output({'Root':{'code':code,'amount':amount}},schema))

    def test_saved_cases_show_field_differences_and_runtime_errors(self):
        config={'mappings':[{'target':'name','source':'${input.name}'}], 'testCases':[{'name':'good','input':{'name':'Ada'},'expected':{'name':'Ada'}},{'name':'bad','input':{'name':'Grace'},'expected':{'name':'Ada'}}]}
        result=run_cases(config)
        self.assertFalse(result['passed']); self.assertTrue(result['results'][0]['passed'])
        self.assertEqual(result['results'][1]['differences'][0]['path'],'$/name')
        self.assertEqual(differences({'a':None},{}),[{'path':'$/a','kind':'missing','expected':None,'actual':None}])
        self.assertTrue(differences(True,1))
        bad=run_cases({'mappings':[{'target':'a','source':'unknownFunction(1)'}]},[{'input':{},'expected':{}}])
        self.assertFalse(bad['passed']); self.assertIn('error',bad['results'][0])

    def test_templates_are_independent_versioned_and_checksummed(self):
        config={'mappings':[{'target':'a','constant':1}], 'lookupTables':{'codes':{'A':'Alpha'}},'password':'excluded'}
        asset=template(config,'Example','1.0.0'); loaded=read_template(asset)
        self.assertNotIn('password',loaded)
        loaded['mappings'][0]['constant']=2; self.assertEqual(config['mappings'][0]['constant'],1)
        asset['config']['mappings'][0]['constant']=4
        with self.assertRaisesRegex(ValueError,'checksum'):read_template(asset)

    def test_schema_impact_reports_affected_mappings(self):
        old={'type':'object','properties':{'name':{'type':'string'},'removed':{'type':'integer'}}}
        new={'type':'object','required':['name'],'properties':{'name':{'type':'number'},'added':{'type':'boolean'}}}
        impact=schema_impact(old,new,[{'target':'name'},{'target':'removed'}])
        self.assertEqual(impact['added'],['added']); self.assertEqual(impact['removed'],['removed'])
        self.assertEqual(impact['affectedTargets'],['name','removed'])

    def test_named_lookup_pipeline_and_message_composition_functions(self):
        config={'lookupTables':{'countries':{'US':'United States'}},'validateOutput':False}
        rules=[{'target':'country','source':'lookupTable(${input.code}, "countries", "Unknown")'}, {'target':'viaPipeline','source':'${input.code}','functions':[{'name':'lookupTable','args':['countries','Unknown']}]}]
        self.assertEqual(execute({'input':{'code':'US'}},rules,config),{'country':'United States','viaPipeline':'United States'})
        self.assertEqual(apply_function('chunks',[1,2,3],[2]),[[1,2],[3]])
        self.assertEqual(apply_function('enrich',{'a':1},[{'a':2,'b':3}]),{'a':2,'b':3})
        self.assertEqual(apply_function('joinBy',[{'id':1,'a':'A'},{'id':2}],[ [{'key':1,'b':'B'}], 'id','key']),[{'id':1,'a':'A','key':1,'b':'B'}])

    def test_lazy_batches_iteration_limits_and_cancellation(self):
        seen=[]
        def records():
            for index in range(10): seen.append(index); yield {'number':index}
        batches=execute_batches(records(),{'mappings':[{'target':'value','source':'${input.number}'}]},2)
        self.assertEqual(seen,[]); first=next(batches); self.assertEqual(seen,[0,1]); self.assertEqual(first[1]['output'],{'value':1})
        rules=[{'target':'a','constant':1}]
        with self.assertRaisesRegex(ValueError,'evaluation steps'):execute({},rules,{'maxIterations':1})
        with self.assertRaisesRegex(ValueError,'cancelled'):execute({},rules,{'_cancelled':lambda:True})
        with patch('app.mapper.clock.monotonic',side_effect=[0,1]):
            with self.assertRaisesRegex(ValueError,'deadline'):execute({},rules,{'maxExecutionMs':1})

    def test_durable_claim_concurrency_receipts_failure_and_explicit_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'stateFile':str(Path(directory)/'state.sqlite'),'namespace':'orders','messageKey':'order-1'}
            with ThreadPoolExecutor(max_workers=8) as pool: claims=list(pool.map(lambda _:operate('deduplicate',config,{'order':1}),range(8)))
            accepted=[claim for claim in claims if claim['accepted']]; self.assertEqual(len(accepted),1)
            token=accepted[0]['claimToken']
            operate('message_receipt',{**config,'claimToken':token,'action':'fail','error':'downstream unavailable'},None)
            self.assertFalse(operate('deduplicate',config,{})['accepted'])
            failed=operate('replay_messages',config,None); self.assertEqual(failed['messages'][0]['payload'],{'order':1})
            operate('replay_messages',{**config,'action':'requeue'},None)
            next_claim=operate('deduplicate',config,{'order':1}); self.assertTrue(next_claim['accepted'])
            with self.assertRaisesRegex(ValueError,'stale'):operate('message_receipt',{**config,'claimToken':token},None)
            operate('message_receipt',{**config,'claimToken':next_claim['claimToken']},None)
            self.assertFalse(operate('deduplicate',config,{})['accepted'])
            with self.assertRaisesRegex(ValueError,'Only failed'):operate('replay_messages',{**config,'action':'requeue'},None)

    def test_aggregation_completion_duplicate_delivery_and_timeout_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'stateFile':str(Path(directory)/'state.sqlite'),'namespace':'orders','correlationKey':'group-1','expectedCount':2,'messageId':'a'}
            with self.assertRaisesRegex(ValueError,'No aggregate'):
                operate('aggregate_messages',{**config,'action':'flush'},None)
            self.assertFalse(operate('aggregate_messages',config,{'part':1})['ready'])
            duplicate=operate('aggregate_messages',config,{'part':1}); self.assertTrue(duplicate['duplicate']); self.assertEqual(duplicate['count'],1)
            result=operate('aggregate_messages',{**config,'messageId':'b'},{'part':2}); self.assertTrue(result['ready']); self.assertEqual(result['records'],[{'part':1},{'part':2}])
            self.assertFalse(operate('aggregate_messages',{**config,'messageId':'b'}, {})['ready'])
            config.update(correlationKey='timeout',timeoutSeconds=1)
            with patch('app.message_state.time.time',return_value=10):operate('aggregate_messages',config,{'part':1})
            with patch('app.message_state.time.time',return_value=12):
                pending=operate('aggregate_messages',{**config,'messageId':'b'},{'part':2}); self.assertTrue(pending['timedOut']); self.assertFalse(pending['ready'])
                ready=operate('aggregate_messages',{**config,'action':'flush'},None); self.assertTrue(ready['ready']);self.assertEqual(ready['records'],[{'part':1}])

    def project(self, config, kind='mapper'):
        return {'id':'caps','name':'Capabilities','resources':[], 'tasks':[{'id':'main','name':'Main','kind':'starter','groups':[], 'activities':[{'id':'Start','name':'Start','type':'start','config':{}},{'id':'Map','name':'Map','type':kind,'config':config},{'id':'End','name':'End','type':'end','config':{}}], 'transitions':[{'id':'a','source':'Start','target':'Map'},{'id':'b','source':'Map','target':'End'}]}]}

    def run_archive(self, compiler, project, command, stdin=None):
        with tempfile.TemporaryDirectory() as directory:
            files=compiler(project,{'local':[]})
            for name,body in files.items():
                path=Path(directory)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            run=subprocess.run([sys.executable,*command],cwd=directory,input=stdin,capture_output=True,text=True,timeout=30)
            return run

    def test_saved_suites_and_streaming_cli_execute_in_both_python_archives(self):
        config={'mappings':[{'target':'country','source':'lookupTable(${input.code}, "countries", "Unknown")'}], 'lookupTables':{'countries':{'US':'United States'}},'testCases':[{'name':'USA','input':{'code':'US'},'expected':{'country':'United States'}}]}
        for compiler in (raw_python_files,engine_python_files):
            with self.subTest(compiler=compiler.__name__):
                project=self.project(config)
                run=self.run_archive(compiler,project,['run_tests.py']); self.assertEqual(run.returncode,0,run.stderr); self.assertTrue(json.loads(run.stdout)['main/Map']['passed'])
                stream=self.run_archive(compiler,project,['transform_jsonl.py','--activity','main/Map','--batch-size','1'],'{"code":"US"}\n{"code":"UK"}\n')
                self.assertEqual(stream.returncode,0,stream.stderr);self.assertEqual([json.loads(line) for line in stream.stdout.splitlines()],[{'country':'United States'},{'country':'Unknown'}])
                broken=copy.deepcopy(project);broken['tasks'][0]['activities'][1]['config']['testCases'][0]['expected']={'country':'Wrong'}
                run=self.run_archive(compiler,broken,['run_tests.py']);self.assertEqual(run.returncode,1,run.stderr);self.assertIn('$/country',run.stdout)

    def test_new_mediation_activities_export_and_persist_between_processes(self):
        for compiler in (raw_python_files,engine_python_files):
            with tempfile.TemporaryDirectory() as directory,self.subTest(compiler=compiler.__name__):
                project=self.project({'operation':'deduplicate','stateFile':str(Path(directory)/'state.sqlite'),'namespace':'orders','messageKey':'a'},'basic')
                command=['run.py','--task','main','--input','{"order":1}'] if compiler is raw_python_files else ['-m','application.main','--task','main','--input','{"order":1}']
                first=self.run_archive(compiler,project,command);self.assertEqual(first.returncode,0,first.stderr); self.assertTrue(json.loads(first.stdout)['accepted'])
                second=self.run_archive(compiler,project,command);self.assertEqual(second.returncode,0,second.stderr); self.assertFalse(json.loads(second.stdout)['accepted'])

    def test_async_mapper_cancellation_stops_the_worker(self):
        entered=threading.Event(); stopped=threading.Event()
        def worker(document,mappings,options):
            entered.set()
            while not options['_cancelled'](): stopped.wait(.001)
            stopped.set()
            raise ValueError('Transformation cancelled')
        async def run():
            with patch('app.mapper.execute',side_effect=worker):
                task=asyncio.create_task(execute_async({},[]))
                while not entered.is_set(): await asyncio.sleep(.001)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertTrue(await asyncio.to_thread(stopped.wait,1))
        asyncio.run(run())

    def test_transform_api_suite_templates_and_invalid_assets(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client=TestClient(app)
        config={'mappings':[{'target':'a','constant':1}], 'testCases':[{'input':{},'expected':{'a':1}}]}
        response=client.post('/api/mapper/suite',json={'config':config});self.assertEqual(response.status_code,200);self.assertTrue(response.json()['passed'])
        asset=client.post('/api/mapper/template',json={'config':config,'name':'Example','version':'1'}).json()
        self.assertEqual(client.post('/api/mapper/template',json={'asset':asset}).json()['config'],config)
        self.assertEqual(client.post('/api/mapper/template',json={'asset':['invalid']}).status_code,400)
        self.assertEqual(client.post('/api/mapper/template',json={'config':config}).status_code,400)
        self.assertEqual(client.post('/api/mapper/suite',json={'config':config,'cases':[{}]}).status_code,400)

    def test_receipt_replay_aggregate_and_split_run_in_both_archives(self):
        for compiler in (raw_python_files,engine_python_files):
            with tempfile.TemporaryDirectory() as directory,self.subTest(compiler=compiler.__name__):
                config={'stateFile':str(Path(directory)/'state.sqlite'),'namespace':'orders','messageKey':'key'}
                command=['run.py','--task','main'] if compiler is raw_python_files else ['-m','application.main','--task','main']
                def run(operation,extra=None,payload=None):
                    project=self.project({**config,**(extra or {}),'operation':operation},'basic')
                    result=self.run_archive(compiler,project,[*command,'--input',json.dumps(payload if payload is not None else {})])
                    self.assertEqual(result.returncode,0,result.stderr)
                    return json.loads(result.stdout)
                claim=run('deduplicate',payload={'order':1})
                self.assertEqual(run('message_receipt',{'claimToken':claim['claimToken']})['status'],'completed')
                self.assertEqual(run('replay_messages')['count'],0)
                aggregate={'correlationKey':'batch','expectedCount':2,'messageId':'a'}
                self.assertFalse(run('aggregate_messages',aggregate,{'part':1})['ready'])
                ready=run('aggregate_messages',{**aggregate,'messageId':'b'},{'part':2})
                self.assertTrue(ready['ready']);self.assertEqual(ready['records'],[{'part':1},{'part':2}])
                self.assertEqual(run('split_records',{'batchSize':2},[1,2,3])['batches'],[[1,2],[3]])

    def test_batch_and_state_quotas_and_completed_record_cleanup(self):
        try: operate('split_records', {}, 'invalid')
        except ValueError as error: self.assertEqual(error.fault_type, 'InvalidInputException')
        with self.assertRaisesRegex(ValueError,'Batch input'):
            list(execute_batches([{'text':'X'*2000}],{'mappings':[],'maxBatchSizeKb':1}))
        with tempfile.TemporaryDirectory() as directory:
            config={'stateFile':str(Path(directory)/'state.sqlite'),'namespace':'quota','messageKey':'a','maxStateSizeMb':1}
            claim=operate('deduplicate',config,{'data':'X'*700000})
            with self.assertRaisesRegex(ValueError,'capacity'):
                operate('deduplicate',{**config,'messageKey':'b'},{'data':'X'*700000})
            with patch('app.message_state.time.time',return_value=20):
                operate('message_receipt',{**config,'claimToken':claim['claimToken'],'retentionSeconds':1},None)
            with patch('app.message_state.time.time',return_value=22):
                self.assertEqual(operate('replay_messages',{**config,'action':'purge'},None)['purged'],1)
