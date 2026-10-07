import asyncio
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch

from app.models import Activity, ProcessDefinition, SharedResource
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
                for source, serializer in ((source, serializer) for source in ('${Parser.SAPIDoc}', '${Parser.SAPIDoc.ARTMAS05}', '${Parser.SAPIDoc.IDOC}', '${Parser.ARTMAS05.IDOC}') for serializer in ('JSON', 'String')):
                    before = len(messages)
                    # Like the supplied project: message defaults to the previous
                    # branch output, while Input explicitly maps the parser object.
                    ctx['last'] = {'data': {'destination': 'EMS_QUEUE', 'published': True}, 'schema': {'fields': []}}
                    activity = Activity(id='send', name='Kafka Send', type='kafka', config={'operation': 'send', 'resourceId': 'k', 'topic': 'idocs', 'message': '${last}', 'valueSerializer': serializer, 'inputMappings': {'message': source}})
                    await runtime.execute(activity, ctx)
                    self.assertEqual(len(messages), before + 1)
                    topic, payload = messages[-1]
                    self.assertEqual(topic, 'idocs')
                    self.assertEqual(payload.decode().count('0000000123456789'), 1, (source, payload))
                    self.assertIsInstance(json.loads(payload), dict)
                    self.assertNotIn('EMS_QUEUE', payload.decode())
                    self.assertNotIn('schema', json.loads(payload))
            finally:
                runtime.close_publishers()
        with patch.dict(sys.modules, {'confluent_kafka': kafka}): asyncio.run(exercise())

    def test_pubsub_object_mapping_replaces_previous_branch_result(self):
        runtime = WorkflowRuntime()
        result = SapAdapter().execute('idoc_parser', CONFIG, XML)
        previous = {'messageId': 'ems-message', 'destination': 'EMS_QUEUE', 'published': True}
        ctx = {'resources': {}, 'input': {}, 'last': previous, 'properties': {}, 'vars': {}, 'context': {}}
        runtime.record_activity_output(Activity(id='Parser', type='sap', name='Parser'), result, ctx)
        activity = Activity(id='pubsub', type='pubsub', name='Pubsub', config={
            'message': '${last}', 'data': '${last}', 'inputMappings': {'data': '${Parser.SAPIDoc.ARTMAS05}'}})
        resolved = runtime.resolve_activity_config(activity, ctx)
        self.assertEqual(resolved['data'], result['SAPIDoc']['ARTMAS05'])
        self.assertEqual(previous, {'messageId': 'ems-message', 'destination': 'EMS_QUEUE', 'published': True})

    def test_three_destination_fanout_keeps_each_mapped_document_separate(self):
        runtime = WorkflowRuntime()
        resources = {kind: SharedResource(id=kind, name=kind, type=kind, config={'mode': 'memory'})
                     for kind in ('ems', 'pubsub', 'kafka')}
        activities = [Activity(id='Start', name='Start', type='start'),
                      Activity(id='Parser', name='Parser', type='sap', config={**CONFIG, 'operation': 'idoc_parser', 'resourceId': 'sap', 'payload': XML}),
                      Activity(id='End', name='End', type='end')]
        edges = [{'id': 'parse', 'source': 'Start', 'target': 'Parser'}]
        for kind in resources:
            field = 'data' if kind == 'pubsub' else 'message'
            activities.append(Activity(id=kind, name=kind, type=kind, config={
                'operation': 'send' if kind != 'pubsub' else 'publish', 'resourceId': kind,
                'topic': 'idocs', 'destination': 'idocs', 'message': '${last}',
                **({'data': '${last}'} if kind == 'pubsub' else {}),
                'inputMappings': {field: '${Parser.SAPIDoc.ARTMAS05}'}}))
            edges.extend([{'id': f'to-{kind}', 'source': 'Parser', 'target': kind},
                          {'id': f'end-{kind}', 'source': kind, 'target': 'End'}])
        resources['sap'] = SharedResource(id='sap', name='SAP', type='sap', config={'mode': 'mock'})
        process = ProcessDefinition(id='fanout', name='Fanout', activities=activities, transitions=edges)
        result = asyncio.run(runtime.run(process, {}, resources=resources))
        self.assertEqual(result.status, 'completed', result.logs)
        expected = SapAdapter().execute('idoc_parser', CONFIG, XML)['SAPIDoc']['ARTMAS05']
        self.assertEqual(len(runtime.messages), 3)
        for messages in runtime.messages.values():
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]['data'], expected)

    def test_nested_mapping_preserves_defaults_but_replaces_selected_object(self):
        runtime = WorkflowRuntime()
        ctx = {'input': {'headers': {'Accept': 'application/json'}}, 'last': {}, 'properties': {}, 'vars': {}, 'context': {}}
        activity = Activity(id='http', type='http', name='HTTP', config={
            'RestInputRequest': {'Config': {'host': 'default', 'port': 443}, 'Headers': {'Cookie': 'old'}},
            'inputMappings': {'RestInputRequest.Config.host': '"mapped"', 'RestInputRequest.Headers': '${input.headers}'}})
        resolved = runtime.resolve_activity_config(activity, ctx)['RestInputRequest']
        self.assertEqual(resolved['Config'], {'host': 'mapped', 'port': 443})
        self.assertEqual(resolved['Headers'], {'Accept': 'application/json'})

    def test_child_mapping_does_not_mutate_source_object(self):
        runtime = WorkflowRuntime()
        ctx = {'input': {'object': {'name': 'original'}}, 'last': {}, 'properties': {}, 'vars': {}, 'context': {}}
        values = runtime.map_input_values({'message': '${input.object}', 'message.name': '"mapped"'}, ctx)
        self.assertEqual(values['message']['name'], 'mapped')
        self.assertEqual(ctx['input']['object']['name'], 'original')
        activity = Activity(id='send', type='kafka', name='Send', config={
            'message': '${input.object}', 'inputMappings': {'message.name': '"mapped"'}})
        self.assertEqual(runtime.resolve_activity_config(activity, ctx)['message']['name'], 'mapped')
        self.assertEqual(ctx['input']['object']['name'], 'original')

    def test_repeated_documents_are_preserved_not_deduplicated(self):
        xml = XML.replace('</ARTMAS05>', '<IDOC><EDI_DC40><DOCNUM>0000000987654321</DOCNUM></EDI_DC40></IDOC></ARTMAS05>')
        result = SapAdapter().execute('idoc_parser', CONFIG, xml)
        wire = json.dumps(result['SAPIDoc'])
        self.assertEqual(wire.count('0000000123456789'), 1)
        self.assertEqual(wire.count('0000000987654321'), 1)
        self.assertEqual(len(result['SAPIDoc']['ARTMAS05']['IDOC']), 2)
