import unittest
from app.runtime import WorkflowRuntime
from app.models import Activity


class DebugInputCaptureTests(unittest.TestCase):
    def test_mapped_values_and_overrides_are_captured_not_previous_output(self):
        runtime = WorkflowRuntime()
        activity = Activity(id='log', name='Log', type='log', config={
            'inputMappings': {'payload.order': '${input.order}', 'message': 'mapped'}})
        ctx = {'input': {'order': {'id': 5}}, 'last': {'unrelated': True}, 'vars': {},
               'properties': {}, 'resources': {}, 'context': {'taskId': 'task'},
               '_debugInputOverrides': {'log': {'message': 'override'}}}
        runtime.resolve_activity_config(activity, ctx)
        result = {'sent': {'id': 5}}
        runtime.record_activity_output(activity, result, ctx, ctx['last'])
        record = ctx['tasks']['task']['activities']['log']
        self.assertEqual(record['input'], {'payload': {'order': {'id': 5}}, 'message': 'override'})
        self.assertEqual(record['output'], result)
        result['sent']['id'] = 9
        ctx['input']['order']['id'] = 9
        self.assertEqual(record['input']['payload']['order']['id'], 5)
        self.assertEqual(record['output']['sent']['id'], 5)

    def test_unmapped_activity_keeps_payload_and_task_local_records(self):
        runtime = WorkflowRuntime()
        activity = Activity(id='same', name='Log', type='log')
        ctx = {'context': {'taskId': 'one'}}
        runtime.record_activity_output(activity, 'output-one', ctx, 'input-one')
        ctx['context']['taskId'] = 'two'
        runtime.record_activity_output(activity, 'output-two', ctx, 'input-two')
        self.assertEqual(ctx['tasks']['one']['activities']['same']['input'], 'input-one')
        self.assertEqual(ctx['tasks']['two']['activities']['same']['output'], 'output-two')
