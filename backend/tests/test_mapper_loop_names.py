import asyncio
import unittest
from backend.app.mapper import execute
from backend.app.models import Activity
from backend.app.runtime import WorkflowRuntime

class MapperLoopNameTests(unittest.TestCase):
    def test_display_name_references_keep_child_paths_relative_to_each_record(self):
        document = {'input':{},'activities':{'source-id':{'name':'Read Orders','output':{'rows':[{'name':'A','MARKS':10},{'name':'B','MARKS':20}]}}}}
        rules = [{'target':'Record','operator':'for-each','source':'${Read-Orders.rows}'},
                 {'target':'Record.Name','source':'${Read-Orders.rows.name}'},
                 {'target':'Record.Marks','source':'${Read-Orders.rows.MARKS}'}]
        expected = {'Record':[{'Name':'A','Marks':10},{'Name':'B','Marks':20}]}
        self.assertEqual(execute(document,rules),expected)
        self.assertNotIn('Read-Orders',document)
        ctx = {**document,'last':{},'properties':{},'vars':{},'resources':{}}
        self.assertEqual(asyncio.run(WorkflowRuntime().execute(Activity(id='map',name='Mapper',type='mapper',config={'mappings':rules}),ctx)),expected)
