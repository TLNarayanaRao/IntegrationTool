import asyncio
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models import Activity, ProcessDefinition, Transition
from app.retry_policy import RetryPlan, RetryConfigurationError, outbound_activity
from app.runtime import WorkflowRuntime, MinaFault
from app.raw_python import raw_python_files, engine_python_files


class IntegrationResilienceTests(unittest.TestCase):
    def test_backoff_bounds_jitter_and_budget(self):
        retry = RetryPlan(True, dict(retryEnabled=True, retryCount=6, retryIntervalSeconds=2,
            retryBackoff='exponential', retryMaxIntervalSeconds=5, retryMaxElapsedSeconds=20), {})
        self.assertEqual([retry.delay(i, ValueError(), 0) for i in range(7)], [2, 4, 5, 5, 5, 5, None])
        self.assertIsNone(retry.delay(0, ValueError(), 18))
        retry.jitter = True
        with patch('app.retry_policy.random.uniform', return_value=3) as random:
            self.assertEqual(retry.delay(2, ValueError(), 0), 3)
            random.assert_called_once_with(2.5, 5)

    def test_fault_filter_accepts_type_and_code(self):
        retry = RetryPlan(True, dict(retryEnabled=True, retryFaultTypes='HTTP_TIMEOUT, TRANSIENT'), {})
        self.assertIsNone(retry.delay(0, ValueError(), 0))
        self.assertIsNotNone(retry.delay(0, MinaFault('timeout', fault_type='HTTP_TIMEOUT'), 0))
        self.assertIsNotNone(retry.delay(0, MinaFault('busy', code='TRANSIENT'), 0))

    def test_invalid_settings_fail_before_side_effects(self):
        for key, values in {
            'retryCount': [-1, 1.5, 101, True, 'nan', 'inf'],
            'retryIntervalSeconds': [-1, 'nan', 'inf', 86401],
            'retryBackoff': ['unexpected'], 'retryMaxElapsedSeconds': [-1, 'nan'],
            'retryFaultTypes': [{'invalid': True}],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(RetryConfigurationError):
                    RetryPlan(True, dict(retryEnabled=True, **{key:value}), {})

    def test_disabled_or_zero_retries_still_execute_once(self):
        for enabled in ('false', 'off', False, '0'):
            self.assertEqual(RetryPlan(True, dict(retryEnabled=enabled, retryCount=3), {}).count, 0)
        self.assertEqual(RetryPlan(True, dict(retryEnabled=True, retryCount=0), {}).count, 0)

    def test_legacy_error_retry_overrides_advanced_consistently(self):
        retry = RetryPlan(True, dict(retryEnabled=True, retryCount=5, retryIntervalSeconds=60),
            dict(action='retry', retryCount=2, retryDelay=250))
        self.assertEqual(retry.count, 2)
        self.assertEqual(retry.delay(0, ValueError(), 0), .25)

    def test_connectors_share_outbound_classification(self):
        for kind, operation in [('http','request'), ('rest','invoke'), ('soap','request_reply'),
                ('kafka','send'), ('jms','send_message'), ('amqp','send'), ('sap','read_table'), ('sftp','put')]:
            self.assertTrue(outbound_activity(kind, operation))
        for kind, operation in [('kafka','receive'), ('jms','receive_message'), ('amqp','receive'), ('rest','receiver')]:
            self.assertFalse(outbound_activity(kind, operation))

    def test_runtime_does_not_retry_cancellation_or_filtered_faults(self):
        async def check():
            runtime = WorkflowRuntime()
            activity = Activity(id='a', name='Call', type='http', config={'advanced':{
                'retryEnabled':True, 'retryIntervalSeconds':0, 'retryFaultTypes':'TimeoutError'}})
            for error in (asyncio.CancelledError(), ValueError('invalid input')):
                runtime.execute = AsyncMock(side_effect=error)
                with self.assertRaises(type(error)):
                    await runtime.execute_with_policy(activity, {'properties':{}, 'vars':{}})
                self.assertEqual(runtime.execute.await_count, 1)
        asyncio.run(check())

    def test_graph_rejects_duplicate_ids_and_dangling_transitions(self):
        a = Activity(id='a', name='A', type='basic')
        with self.assertRaisesRegex(ValueError, 'Activity identifiers'):
            ProcessDefinition(activities=[a, a])
        edge = Transition(id='t', source='a', target='a')
        with self.assertRaisesRegex(ValueError, 'Transition identifiers'):
            ProcessDefinition(activities=[a], transitions=[edge, edge])
        with self.assertRaisesRegex(ValueError, 'missing activity'):
            ProcessDefinition(activities=[a], transitions=[Transition(id='t', source='a', target='missing')])

    def test_both_exported_archives_execute_retry_and_fault_policies(self):
        project = dict(id='retry', name='Retry', resources=[], schemas=[], tasks=[dict(
            id='main', name='Main', kind='starter', groups=[], transitions=[],
            activities=[dict(id='a', name='Call', type='http', config={'operation':'request'})])])
        for builder, engine in ((raw_python_files, False), (engine_python_files, True)):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as folder:
                for name, body in builder(project, {'local':[]}).items():
                    path = Path(folder) / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                script = '''
import asyncio
from unittest.mock import AsyncMock
ENGINE = %r
if ENGINE:
    from application.engine.runtime import WorkflowRuntime
    from application.engine.models import Activity
    runtime = WorkflowRuntime()
else:
    from application import core
async def check():
    for enabled, expected in [('false', 1), ('true', 3)]:
        raw = {'operation':'request', 'advanced':{'retryEnabled':enabled, 'retryCount':2, 'retryIntervalSeconds':0}, 'errorPolicy':{'action':'continue', 'includeInput':'false', 'outputVariable':'fault'}}
        fake = AsyncMock(side_effect=ValueError('failure'))
        if ENGINE:
            runtime.execute = fake
            ctx = {'properties':{}, 'vars':{}, 'last':{'secret':'hidden'}}
            result = await runtime.execute_with_policy(Activity(id='a', name='Call', type='http', config=raw), ctx)
            variables = ctx['vars']
        else:
            core.execute = fake
            ctx = core.Context({'secret':'hidden'}, {}, {})
            result = await core.execute_with_policy('http', raw, ctx, 'a', 'Call')
            variables = ctx.variables
        assert fake.await_count == expected, (fake.await_count, expected)
        assert result == {'type':'ValueError', 'description':'failure', 'activityId':'a'}, result
        assert variables['fault'] == result
asyncio.run(check())
''' % engine
                result = subprocess.run([sys.executable, '-c', script], cwd=folder, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
