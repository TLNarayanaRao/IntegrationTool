import asyncio
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch

from app.models import Activity, SharedResource
from app.runtime import WorkflowRuntime
from app.sap import SapAdapter

XML = '<ARTMAS05><IDOC><EDI_DC40><DOCNUM>0000000123456789</DOCNUM></EDI_DC40><E1BPE1VARKEY><MATERIAL>123</MATERIAL></E1BPE1VARKEY></IDOC></ARTMAS05>'
CONFIG = {'idocType': 'ARTMAS05', 'idocOutputMode': 'JSON'}

class IdocKafkaPayloadTests(unittest.TestCase):
    def test_parser_serializes_one_document_and_preserves_legacy_lookups(self):
        result = SapAdapter().execute('idoc_parser', CONFIG, XML)
        for value in (result, copy.deepcopy(result)):
            self.assertEqual(json.dumps(value).count('0000000123456789'), 1)
            self.assertEqual(list(value['SAPIDoc']), ['ARTMAS05'])
            self.assertEqual(value['SAPIDoc']['IDOC'], value['SAPIDoc']['ARTMAS05']['IDOC'])
            self.assertEqual(value.get('ARTMAS05')['IDOC'], value['SAPIDoc'].get('IDOC'))
        # The wire representation matches the schema tree after a JSON round trip.
        wire = json.loads(json.dumps(result))
        self.assertEqual(wire['SAPIDoc']['ARTMAS05']['IDOC']['EDI_DC40']['DOCNUM'], '0000000123456789')
        self.assertNotIn('IDOC', wire['SAPIDoc'])
        self.assertNotIn('ARTMAS05', wire)

    def test_mapped_parser_output_is_published_once_without_duplicate_json(self):
        messages = []
        class Producer:
            def __init__(self, config): pass
            def produce(self, topic, value, **kwargs): messages.append((topic, value))
            def poll(self, timeout): pass
            def flush(self, timeout): return 0
        kafka = types.ModuleType('confluent_kafka')
        kafka.Producer = Producer; kafka.Consumer = object; kafka.TopicPartition = object
        async def exercise():
            runtime = WorkflowRuntime()
            resource = SharedResource(id='k', type='kafka', name='Kafka', config={'bootstrapServers': 'localhost:9092'})
            result = SapAdapter().execute('idoc_parser', CONFIG, XML)
            ctx = {'resources': {'k': resource}, 'input': {}, 'last': result, 'properties': {}, 'vars': {}, 'context': {}, 'activities': {}}
            runtime.record_activity_output(Activity(id='Parser', type='sap', name='Parser'), result, ctx)
            try:
                for source in ('${Parser.SAPIDoc}', '${Parser.SAPIDoc.ARTMAS05}', '${Parser.SAPIDoc.IDOC}', '${Parser.ARTMAS05.IDOC}'):
                    before = len(messages)
                    activity = Activity(id='send', name='Kafka Send', type='kafka', config={'operation': 'publish', 'resourceId': 'k', 'topic': 'idocs', 'valueSerializer': 'JSON', 'inputMappings': {'data': source}})
                    await runtime.execute(activity, ctx)
                    self.assertEqual(len(messages), before + 1)
                    topic, payload = messages[-1]
                    self.assertEqual(topic, 'idocs')
                    self.assertEqual(payload.decode().count('0000000123456789'), 1, (source, payload))
                    self.assertIsInstance(json.loads(payload), dict)
            finally:
                runtime.close_publishers()
        with patch.dict(sys.modules, {'confluent_kafka': kafka}): asyncio.run(exercise())

    def test_repeated_documents_are_preserved_not_deduplicated(self):
        xml = XML.replace('</ARTMAS05>', '<IDOC><EDI_DC40><DOCNUM>0000000987654321</DOCNUM></EDI_DC40></IDOC></ARTMAS05>')
        result = SapAdapter().execute('idoc_parser', CONFIG, xml)
        wire = json.dumps(result['SAPIDoc'])
        self.assertEqual(wire.count('0000000123456789'), 1)
        self.assertEqual(wire.count('0000000987654321'), 1)
        self.assertEqual(len(result['SAPIDoc']['ARTMAS05']['IDOC']), 2)
