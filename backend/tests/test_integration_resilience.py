import asyncio
import importlib.util
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models import Activity, ProcessDefinition, Project, Transition
from app.retry_policy import (
    ActivityCircuits, CircuitCapacityError, CircuitOpenError, CircuitPlan, RetryConfigurationError, RetryPlan,
    circuit_activity, outbound_activity,
)
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

    def test_circuit_preserves_one_probe_against_stale_attempts_and_cancellation(self):
        now = 0
        events = []
        circuits = ActivityCircuits(clock=lambda: now)
        plan = CircuitPlan('ftp', 'get', dict(circuitEnabled=True, circuitFailureThreshold=1,
                                             circuitCooldownSeconds=2, circuitFaultTypes='TimeoutError'))
        attempt = lambda: circuits.attempt(('activity',), plan, events.append)
        with attempt():  # A slow success starts in the closed generation.
            with self.assertRaises(ValueError), attempt():
                raise ValueError('excluded fault')
            self.assertEqual(events, [])
            with self.assertRaises(TimeoutError), attempt() as ticket:
                raise TimeoutError('connection')
            self.assertTrue(ticket.stops_retry)
        with self.assertRaises(CircuitOpenError), attempt():
            self.fail('a stale success closed the circuit')
        now = 2
        with self.assertRaises(asyncio.CancelledError), attempt():
            with self.assertRaises(CircuitOpenError), attempt():
                self.fail('two recovery probes were admitted')
            raise asyncio.CancelledError()
        with self.assertRaises(TimeoutError), attempt():
            raise TimeoutError('still unavailable')
        with self.assertRaises(CircuitOpenError), attempt():
            self.fail('a failed probe should start a new cooldown')
        now = 4
        with attempt():
            pass
        self.assertEqual(events, ['open', 'blocked', 'blocked', 'open', 'blocked', 'closed'])
        self.assertFalse(circuit_activity('amqp', 'dead_letter'))
        self.assertFalse(circuit_activity('rest', 'invoke'))

    def test_circuit_registry_bounds_state_and_reclaims_inactive_entries(self):
        now = 0
        circuits = ActivityCircuits(capacity=1, clock=lambda: now)
        plan = CircuitPlan('sftp', 'send', dict(circuitEnabled=True))
        with self.assertRaises(TimeoutError), circuits.attempt('one', plan, lambda _: None):
            raise TimeoutError('count this failure')
        with self.assertRaises(CircuitCapacityError), circuits.attempt('two', plan, lambda _: None):
            self.fail('the circuit registry exceeded its capacity')
        now = 3601
        with circuits.attempt('two', plan, lambda _: None):
            pass

    def test_circuit_stops_retries_and_preserves_fault_policy(self):
        async def check():
            runtime = WorkflowRuntime()
            runtime.execute = AsyncMock(side_effect=TimeoutError('unavailable'))
            policy = dict(retryEnabled=True, retryCount=9, retryIntervalSeconds=0,
                          circuitEnabled=True, circuitFailureThreshold=2)
            activity = Activity(id='transfer', name='Transfer', type='ftp', config={
                'operation':'get', 'advanced':policy, 'errorPolicy':{'action':'continue', 'includeInput':False},
            })
            ctx = {'properties':{}, 'vars':{}, 'context':{'taskId':'task','environment':'qa'}}
            result = await runtime.execute_with_policy(activity, ctx)
            self.assertEqual(result['type'], 'TimeoutError')
            self.assertEqual(runtime.execute.await_count, 2)
            result = await runtime.execute_with_policy(activity, ctx)
            self.assertEqual(result['type'], 'CircuitOpen')
            self.assertEqual(runtime.execute.await_count, 2)
            self.assertEqual([line['circuitState'] for line in ctx['logs'] if line.get('kind') == 'circuitBreaker'], ['open', 'blocked'])
        asyncio.run(check())

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

    @unittest.skipUnless(importlib.util.find_spec('pyftpdlib'), 'Install test-only pyftpdlib for a live FTP server')
    def test_live_circuit_with_run_debug_and_both_exports(self):
        from app.debugger import DebugManager
        from tests.test_python_mapper_parity import PythonMapperParityTests
        from tests.test_transfer_network import ftp_server

        with tempfile.TemporaryDirectory() as root, ftp_server(Path(root)) as connection:
            (Path(root) / 'ready.txt').write_text('ready', encoding='utf-8')
            project = PythonMapperParityTests().project(input_mappings={'result.outcome':'${activities.Fetch.output}'})
            project['resources'] = [dict(id='ftp', name='FTP', type='ftp', config=connection)]
            task = project['tasks'][0]
            task['activities'].insert(1, dict(id='Fetch', name='Fetch', type='ftp', config={
                'operation':'get', 'resourceId':'ftp', 'remotePath':'${input.path}',
                'advanced':{'circuitEnabled':True, 'circuitFailureThreshold':1, 'circuitCooldownSeconds':1},
            }))
            task['activities'].extend([
                dict(id='Fallback', name='Fallback', type='catch', config={'catchAll':True}),
                dict(id='FaultEnd', name='FaultEnd', type='end',
                     config={'inputMappings':{'result.outcome':'${activities.Fallback.output}'}}),
            ])
            task['transitions'] = [dict(id='a', source='Start', target='Fetch'),
                                   dict(id='b', source='Fetch', target='End'),
                                   dict(id='c', source='Fallback', target='FaultEnd')]

            async def check_studio():
                now = 0
                model = Project.model_validate(project)
                resources = {resource.id: resource for resource in model.resources}
                runtime = WorkflowRuntime()
                runtime.activity_circuits = ActivityCircuits(clock=lambda: now)
                debugger = DebugManager(runtime)

                async def run(path, environment='local'):
                    result = await runtime.run(model.tasks[0], {'path':path}, resources, project=model,
                                               environment=environment)
                    self.assertEqual(result.status, 'completed', result.logs)
                    return result.output['outcome']

                async def debug(path):
                    task_id = debugger.start(model, 'main', {'path':path}, resources, {}, [], pause_on_error=False)['sessionId']
                    result = await debugger.action(task_id, 'continue')
                    self.assertEqual(result['status'], 'completed', result['logs'])
                    return result['output']['outcome']

                self.assertEqual((await run('missing.txt'))['type'], 'error_perm')
                self.assertIn('contentBase64', await debug('ready.txt'))
                self.assertIn('contentBase64', await run('ready.txt', 'qa'))
                self.assertEqual((await run('ready.txt'))['type'], 'CircuitOpen')
                self.assertEqual((await debug('missing.txt'))['type'], 'error_perm')
                self.assertEqual((await debug('ready.txt'))['type'], 'CircuitOpen')
                now = 2
                self.assertIn('contentBase64', await run('ready.txt'))
                self.assertIn('contentBase64', await debug('ready.txt'))

            asyncio.run(check_studio())
            for compiler in (raw_python_files, engine_python_files):
                with self.subTest(archive=compiler.__name__), tempfile.TemporaryDirectory() as folder:
                    for name, body in compiler(project, {'local':[], 'qa':[]}).items():
                        path = Path(folder) / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(body)
                    registry_import = ('from application.core import _ACTIVITY_CIRCUITS as circuits'
                        if compiler is raw_python_files else
                        'from application.main import RUNTIME\ncircuits = RUNTIME.activity_circuits')
                    script = registry_import + '''
import asyncio
from application.main import run_task

now = 0
circuits._clock = lambda: now

async def run(path, environment='local'):
    return (await run_task('main', {'path':path}, environment))['outcome']

async def check():
    global now
    assert (await run('missing.txt'))['type'] == 'error_perm'
    assert 'contentBase64' in await run('ready.txt', 'qa')
    assert (await run('ready.txt'))['type'] == 'CircuitOpen'
    now = 2
    assert 'contentBase64' in await run('ready.txt')

asyncio.run(check())
'''
                    result = subprocess.run([sys.executable, '-c', script], cwd=folder,
                                            capture_output=True, text=True, timeout=40)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
