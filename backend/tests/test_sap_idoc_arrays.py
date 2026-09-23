import asyncio
import unittest
from unittest.mock import Mock, AsyncMock, patch
from app.sap import SapAdapter

SCHEMA = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:complexType name="Row"><xs:sequence>
 <xs:element name="VALUE" type="xs:string"/>
 <xs:element name="DETAIL" maxOccurs="10"><xs:complexType><xs:sequence>
 <xs:element name="CODE" type="xs:string"/>
 </xs:sequence></xs:complexType></xs:element>
</xs:sequence></xs:complexType>
<xs:element name="CUSTOM01"><xs:complexType><xs:sequence>
 <xs:element name="IDOC"><xs:complexType><xs:sequence>
 <xs:element name="EDI_DC40"><xs:complexType><xs:sequence><xs:element name="IDOCTYP" type="xs:string"/></xs:sequence></xs:complexType></xs:element>
 <xs:element name="ROW" maxOccurs="unbounded" type="Row"/>
 <xs:element name="SINGLE" type="Row"/>
 </xs:sequence></xs:complexType></xs:element>
</xs:sequence></xs:complexType></xs:element></xs:schema>'''
XML = '<CUSTOM01><IDOC><EDI_DC40><IDOCTYP>CUSTOM01</IDOCTYP></EDI_DC40><ROW><VALUE>1</VALUE><DETAIL><CODE>A</CODE></DETAIL></ROW><SINGLE><VALUE>2</VALUE></SINGLE></IDOC></CUSTOM01>'
CFG = {'idocType': 'CUSTOM01', 'selectedIdoc': {'idocType': 'CUSTOM01', 'schema': SCHEMA}, 'idocOutputMode': 'JSON'}


class IdocArrayTests(unittest.TestCase):
    def test_parser_xml_singleton_and_nested_segments_stay_arrays(self):
        result = SapAdapter().execute('idoc_parser', CFG, XML)['SAPIDoc']
        for data in (result['IDOC'], result['CUSTOM01']['IDOC']):
            self.assertEqual(data['ROW'][0]['DETAIL'], [{'CODE': 'A'}])
            self.assertIsInstance(data['EDI_DC40'], dict)
            self.assertIsInstance(data['SINGLE'], dict)
            self.assertNotIn('DETAIL', data['SINGLE'])

    def test_json_objects_and_existing_arrays_are_normalized_idempotently(self):
        original = {'IDOC': {'ROW': {'VALUE': '1', 'DETAIL': {'CODE': 'A'}}}}
        normalized = SapAdapter._normalize_idoc_arrays(original, CFG)
        self.assertEqual(normalized['IDOC']['ROW'], [{'VALUE': '1', 'DETAIL': [{'CODE': 'A'}]}])
        self.assertIsInstance(original['IDOC']['ROW'], dict)
        self.assertEqual(SapAdapter._normalize_idoc_arrays(normalized, CFG), normalized)
        result = SapAdapter().execute('idoc_parser', CFG, original)['SAPIDoc']
        self.assertEqual(result['IDOC'], normalized['IDOC'])

    def test_multiple_segments_remain_flat_list(self):
        xml = XML.replace('</IDOC>', '<ROW><VALUE>3</VALUE></ROW></IDOC>')
        result = SapAdapter().execute('idoc_parser', CFG, xml)['SAPIDoc']['IDOC']
        self.assertEqual([row['VALUE'] for row in result['ROW']], ['1', '3'])

    def test_no_schema_preserves_legacy_shape(self):
        value = {'IDOC': {'ROW': {'VALUE': '1'}}}
        self.assertEqual(SapAdapter._normalize_idoc_arrays(value, {}), value)

    def test_listener_uses_same_schema_cardinality(self):
        adapter = SapAdapter()
        cfg = {**CFG, 'mode': 'external', 'programId': 'test', 'gatewayHost': 'test', 'gatewayService': 'sapgw00'}
        listener = Mock()
        listener.process.poll.return_value = None
        listener.next_event = AsyncMock(return_value={'payload': {}})
        with patch.object(adapter, '_listener_key', return_value='test'), patch.object(adapter, '_idoc_structured_to_xml', return_value=XML):
            adapter.listeners['test'] = listener
            result = asyncio.run(adapter.receive_idoc(cfg))
        self.assertIsInstance(result['SAPIDoc']['IDOC']['ROW'], list)
        self.assertEqual(result['IDocXML'], XML)
