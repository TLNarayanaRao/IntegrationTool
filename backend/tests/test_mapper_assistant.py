import asyncio
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.mapper_assistant import fields, plan
from app.mapper import execute
from app.models import Project


SOURCE = {'purchases':[{'id':1,'items':[{'sku':'A','qty':2},{'sku':'B','qty':3}]},
                       {'id':2,'items':[{'sku':'C','qty':4}]}], 'first_name':'Ada'}
TARGET = {'orders':[{'id':0,'lines':[{'productCode':'','quantity':0}]}], 'firstName':''}
EXPECTED = {'orders':[{'id':1,'lines':[{'productCode':'A','quantity':2},{'productCode':'B','quantity':3}]},
                      {'id':2,'lines':[{'productCode':'C','quantity':4}]}], 'firstName':'Ada'}
SOURCE['tags']=['fast','safe'];TARGET['tags']=[''];EXPECTED['tags']=['fast','safe']


class MapperAssistantTests(unittest.TestCase):
    def test_nested_repeating_and_business_names_are_executable(self):
        result = plan(SOURCE,TARGET,profile='commerce')
        self.assertEqual(result['summary']['loops'],2)
        self.assertEqual(result['summary']['suggested'],5)
        self.assertEqual(result['summary']['copies'],1)
        self.assertEqual(execute({'last':SOURCE,'input':SOURCE},result['rules']),EXPECTED)
        self.assertEqual(SOURCE['purchases'][0]['items'][0]['qty'],2)

    def test_ambiguous_fields_require_reviewed_choice_and_respect_types(self):
        source={'billing':{'id':1},'shipping':{'id':2}}
        result=plan(source,{'id':0})
        self.assertEqual(result['summary']['ambiguous'],1)
        self.assertEqual(result['rules'],[])
        chosen=plan(source,{'id':0},choices={'id':'shipping.id'})
        self.assertEqual(execute({'last':source},chosen['rules']),{'id':2})
        with self.assertRaises(ValueError): plan({'id':'one'},{'id':0},choices={'id':'id'})
        with self.assertRaises(ValueError): plan(source,{'id':0},choices={'unknown':'billing.id'})

    def test_manual_values_disabled_rules_and_complex_occurrences_are_preserved(self):
        manual=[{'target':'orders.id','constant':99,'enabled':True},
                {'target':'firstName','source':'"manual"','enabled':False}]
        original=copy.deepcopy(manual)
        result=plan(SOURCE,TARGET,manual,profile='commerce')
        self.assertEqual(result['rules'][:2],manual)
        self.assertFalse(any(r['target'].startswith('orders.') for r in result['rules'][2:]))
        self.assertEqual(manual,original)
        copied=[{'target':'orders','source':'last.original','operator':'copy-of','enabled':True,'occurrenceId':'copy'}]
        self.assertEqual(plan(SOURCE,TARGET,copied,profile='commerce')['rules'][0],copied[0])
        self.assertFalse(any(r['target'].startswith('orders.') for r in plan(SOURCE,TARGET,copied,profile='commerce')['rules']))
        loop={'target':'orders','source':'last.purchases','select':'last.purchases','operator':'for-each','enabled':True}
        authored={'target':'orders.id','constant':99,'enabled':True}
        reused=plan(SOURCE,TARGET,[loop,authored],profile='commerce')
        self.assertEqual(reused['summary']['reusedLoops'],1)
        self.assertEqual(sum(r['target']=='orders' for r in reused['rules']),1)
        output=execute({'last':SOURCE},reused['rules'])
        self.assertEqual([r['id'] for r in output['orders']],[99,99])
        self.assertEqual(output['orders'][0]['lines'][0],{'productCode':'A','quantity':2})
        ambiguous_loops=plan(SOURCE,TARGET,[loop,copy.deepcopy(loop)],profile='commerce')
        self.assertEqual(ambiguous_loops['summary']['reusedLoops'],0)
        self.assertFalse(any(r['target'].startswith('orders.') for r in ambiguous_loops['rules']))

    def test_no_repeat_to_scalar_guess_and_required_gaps_are_reported(self):
        target={'type':'object','properties':{'id':{'type':'integer'},'missing':{'type':'string'}},'required':['id','missing']}
        result=plan({'rows':[{'id':1}]},target)
        self.assertEqual(result['summary']['requiredUnmapped'],2)
        self.assertFalse(result['rules'])
        self.assertFalse(plan(SOURCE,TARGET,profile='commerce',auto_repeating=False)['summary']['loops'])

    def test_custom_aliases_learning_and_exact_strategy(self):
        source={'legacy_code':'A'}; target={'customerCode':''}
        self.assertFalse(plan(source,target)['rules'])
        self.assertTrue(plan(source,target,aliases=[['legacy_code','customerCode']])['rules'])
        self.assertTrue(plan(source,target,learned={'customerCode':'legacy_code'})['rules'])
        self.assertFalse(plan(source,target,aliases=[['legacy_code','customerCode']],strategy='exact')['rules'])
        with self.assertRaises(ValueError): plan(source,target,aliases=[['','x']])

    def test_schema_refs_xsd_nested_arrays_and_optional_sample_fields(self):
        schema={'type':'object','properties':{'rows':{'type':'array','items':{'$ref':'#/$defs/row'}}},
                '$defs':{'row':{'type':'object','properties':{'id':{'type':'integer'},'children':{'type':'array','items':{'type':'string'}}}}}}
        self.assertEqual(next(r for r in fields(schema) if r['path']=='rows.children')['repeats'],['rows','rows.children'])
        sample={'rows':[{'id':1},{'id':2,'optional':'x'}]}
        self.assertIn('rows.optional',{r['path'] for r in fields(sample)})
        xsd='<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="root"><xs:complexType><xs:sequence><xs:element name="rows" maxOccurs="unbounded"><xs:complexType><xs:sequence><xs:element name="children" type="xs:string" maxOccurs="unbounded"/></xs:sequence></xs:complexType></xs:element></xs:sequence></xs:complexType></xs:element></xs:schema>'
        self.assertEqual(fields(xsd)[0]['repeats'],['root.rows','root.rows.children'])

    def test_primitive_arrays_copy_in_generated_xslt(self):
        from app.mapper_binding import generate_binding, reopen_binding
        from app.mapper_xml import parse_xml, transform_xml
        xsd='<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="root"><xs:complexType><xs:sequence><xs:element name="tags" type="xs:string" maxOccurs="unbounded"/></xs:sequence></xs:complexType></xs:element></xs:schema>'
        rules=plan(xsd,xsd)['rules']
        stylesheet=generate_binding(rules,xsd,xsd)
        self.assertEqual(reopen_binding(stylesheet)['mappings'],rules)
        root=transform_xml(parse_xml('<root><tags>A</tags><tags>B</tags></root>'),stylesheet)
        self.assertEqual([n.text for n in root.findall('tags')],['A','B'])

    def test_large_schemas_use_indexed_candidates_and_scope(self):
        source={f'field_{i}':i for i in range(2000)}; target={f'field_{i}':0 for i in range(2000)}
        result=plan(source,target)
        self.assertEqual(result['summary']['suggested'],2000)
        self.assertEqual(result['summary']['candidateComparisons'],2000)
        scoped=plan({'a':{'id':1},'b':{'id':2}},{'b':{'id':0}},source_scope='b',target_scope='b')
        self.assertEqual(scoped['recommendations'][0]['selected'],'b.id')

    def test_invalid_analysis_options_are_rejected_and_zero_literals_are_protected(self):
        for options in ({'threshold':10**400},{'threshold':float('nan')},{'profile':[]},{'aliases':{}},{'choices':[]},{'mappings':{}},
                        {'source_level':0},{'aliases':[['!','?']]}):
            with self.subTest(options=str(options)[:100]), self.assertRaises(ValueError): plan({'x':1},{'x':0},**options)
        rule={'target':'x','source':0,'enabled':True}
        self.assertEqual(plan({'x':1},{'x':0},[rule])['rules'],[rule])

    def test_api_preview_run_debug_and_both_python_archives(self):
        from app.main import mapper_plan, mapper_test
        with patch('app.main.shared_paths',return_value={}):
            result=mapper_plan({'sourceSchema':SOURCE,'targetSchema':TARGET,'profile':'commerce'})
        rules=result['rules']
        integer={'type':'integer'}; string={'type':'string'}
        line={'type':'object','properties':{'productCode':string,'quantity':integer},'required':['productCode','quantity']}
        order={'type':'object','properties':{'id':integer,'lines':{'type':'array','items':line}},'required':['id','lines']}
        schema={'type':'object','properties':{'orders':{'type':'array','items':order},'firstName':string,'tags':{'type':'array','items':string}},'required':['orders','firstName','tags']}
        preview=mapper_test({'input':SOURCE,'mappings':rules,'targetSchema':schema})
        self.assertEqual(preview['output'],EXPECTED);self.assertTrue(preview['valid'])
        nodes=[{'id':'s','name':'Start','type':'start'}, {'id':'m','name':'Mapper','type':'mapper','config':{'mappings':rules,'targetSchema':schema}}, {'id':'e','name':'End','type':'end'}]
        project=Project.model_validate({'id':'assistant','name':'Assistant','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
            'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
        reused=project.tasks[0].model_dump();reused['id']='reused';reused['name']='Reused'
        reused['activities'][1]['config']['mappings']=plan(SOURCE,TARGET,[
            {'target':'orders','source':'last.purchases','operator':'for-each','enabled':True},
            {'target':'orders.id','constant':99,'enabled':True}],profile='commerce')['rules']
        reused_preview=mapper_test({'input':SOURCE,'mappings':reused['activities'][1]['config']['mappings'],'targetSchema':schema})
        self.assertTrue(reused_preview['valid'])
        self.assertEqual([row['id'] for row in reused_preview['output']['orders']],[99,99])
        self.assertEqual(reused_preview['output']['orders'][0]['lines'][0],{'productCode':'A','quantity':2})
        project=Project.model_validate({**project.model_dump(),'tasks':[project.tasks[0].model_dump(),reused]})
        spec=importlib.util.spec_from_file_location('assistant_flows',Path(__file__).parents[2]/'scripts/flow-throughput.py')
        flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
        async def run(folder):
            for mode in ('run','debug','python-direct','python-engine'):
                executor=flow.Executor(mode,project,str(Path(folder)/(mode+'.log')))
                try:
                    await executor.start()
                    self.assertEqual(await executor.execute('main',SOURCE),EXPECTED,mode)
                    reused_expected=copy.deepcopy(EXPECTED)
                    for order in reused_expected['orders']:order['id']=99
                    self.assertEqual(await executor.execute('reused',SOURCE),reused_expected,mode)
                    changed=copy.deepcopy(SOURCE);changed['purchases']=[]
                    self.assertEqual((await executor.execute('main',changed))['orders'],[],mode)
                finally: await executor.close()
        with tempfile.TemporaryDirectory() as folder: asyncio.run(run(folder))


if __name__=='__main__': unittest.main()
