import json
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from app.main import mapper_test

class MapperPreviewTests(unittest.TestCase):
    def test_json_output_is_generated_without_changing_runtime_value(self):
        result = mapper_test({'input':{'name':'Ada'},'mappings':[{'source':'${input.name}','target':'person.name'}]})
        self.assertEqual(result['output'], {'person':{'name':'Ada'}})
        self.assertEqual(json.loads(result['outputText']), result['output'])
        self.assertEqual(result['outputFormat'], 'json')

    def test_named_xsd_target_has_xml_preview_and_repeated_elements(self):
        schema = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:orders" elementFormDefault="qualified"><xs:complexType name="OrderType"><xs:sequence><xs:element name="name" type="xs:string" maxOccurs="unbounded"/></xs:sequence></xs:complexType><xs:element name="Order" type="OrderType"/></xs:schema>'
        result = mapper_test({'input':{},'mappings':[{'target':'Order.name','constant':['Ada','Grace']}], 'targetSchema':schema,'options':{'validateOutput':False}})
        self.assertEqual(result['output'], {'Order':{'name':['Ada','Grace']}})
        root = ET.fromstring(result['outputText'])
        self.assertEqual(root.tag, '{urn:orders}Order')
        self.assertEqual([child.text for child in root], ['Ada','Grace'])
        self.assertEqual(result['outputFormat'], 'xml')

    def test_xml_function_output_is_displayed_without_json_quotes(self):
        with patch('app.main.execute_mapping', return_value='<person><name>Ada</name></person>'):
            result = mapper_test({'input':{'name':'Ada'},'mappings':[]})
        self.assertEqual(result['outputText'], result['output'])
        self.assertEqual(result['outputFormat'], 'xml')
