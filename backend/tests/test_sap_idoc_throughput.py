"""Replay the SAP bridge protocol through Studio Run and both generated Python entry points."""
import asyncio
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app import main
from app.execution_analytics import activity_timings
from app.models import Project
from app.project_logging import close_project_log_handlers
from app.raw_python import engine_python_files, raw_python_files
from app.runtime import WorkflowRuntime
from app.sap import SapAdapter


def project_for_replay():
    return Project.model_validate({
        'id': 'idoc-replay', 'name': 'IDoc-Replay',
        'properties': {'local': []},
        'resources': [{'id': 'sap', 'name': 'SAP', 'type': 'sap', 'config': {
            'mode': 'external', 'programId': 'REPLAY', 'gatewayHost': 'replay.invalid',
            'gatewayService': 'sapgw00', 'maximumConnections': 8,
        }}],
        'tasks': [{'id': 'starter', 'name': 'Starter', 'kind': 'starter', 'activities': [
            {'id': 'listener', 'name': 'Listener', 'type': 'sap', 'config': {
                'resourceId': 'sap', 'operation': 'idoc_listener', 'idocType': 'ARTMAS05',
            }},
            {'id': 'parser', 'name': 'Parser', 'type': 'sap', 'config': {
                'resourceId': 'sap', 'operation': 'idoc_parser', 'idocType': 'ARTMAS05', 'idocOutputMode': 'JSON',
            }},
            {'id': 'end', 'name': 'End', 'type': 'end'},
        ], 'transitions': [{'id': 'parse', 'source': 'listener', 'target': 'parser'},
                           {'id': 'return', 'source': 'parser', 'target': 'end'}]}],
    })


class ReplayBridge:
    def __init__(self, count):
        self.count = count
        self.position = 0
        self.finish = None
        self.committed = set()
        self.checked = set()
        self.inflight = 0
        self.maximum_inflight = 0
        self.errors = []
        self.process = Mock()
        self.process.poll.return_value = None

    def close(self):
        self.process.poll.return_value = 0

    async def next_event(self, timeout=None):
        if self.position >= self.count:
            await asyncio.Event().wait()
        number = str(self.position)
        self.position += 1
        self.inflight += 1
        self.maximum_inflight = max(self.maximum_inflight, self.inflight)
        return {'event': 'sap_request', 'deliveryId': number, 'TID': f'package-{int(number) // 250}',
                'payload': {'tables': {'IDOC_CONTROL_REC_40': [{'DOCNUM': number}], 'IDOC_DATA_REC_40': [
                    {'DOCNUM': number, 'SEGNAM': 'DEMO', 'SDATA': f'payload-{number}', 'SEGNUM': '01'}]}}}

    def check(self, output, number):
        document = output['SAPIDoc']['ARTMAS05']['IDOC']
        if document['EDI_DC40']['DOCNUM'] != number or document['DEMO']['SDATA'] != f'payload-{number}':
            raise AssertionError(f'SAP payload mismatch for {number}')
        self.checked.add(number)

    def acknowledge(self, delivery_id, success, response=None):
        # Direct archives write acknowledgements from a connector thread.
        try:
            on_loop = asyncio.get_running_loop() is self.loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self._acknowledged(delivery_id, success)
        else:
            self.loop.call_soon_threadsafe(self._acknowledged, delivery_id, success)

    def _acknowledged(self, delivery_id, success):
        self.inflight -= 1
        if not success or delivery_id not in self.checked or delivery_id in self.committed:
            self.errors.append(delivery_id)
            self.finish.set()
        self.committed.add(delivery_id)
        if len(self.committed) == self.count:
            self.finish.set()


class SapListenerThroughputTests(unittest.TestCase):
    def test_intake_timer_starts_after_the_bridge_supplies_the_document(self):
        cfg = {'operation': 'idoc_listener', 'programId': 'REPLAY', 'gatewayHost': 'replay.invalid',
               'gatewayService': 'sapgw00', 'mode': 'external', '_captureReceiveTiming': True}
        bridge = ReplayBridge(1)
        clock_readings = iter((100.0, 100.0025))

        def clock():
            self.assertEqual(bridge.position, 1)
            return next(clock_readings)

        async def exercise():
            with patch('app.sap.start_sap_listener', return_value=bridge), patch('app.sap.time.perf_counter', side_effect=clock):
                result = await SapAdapter().receive_idoc(cfg)
            self.assertAlmostEqual(result['_sapIntakeMs'], 2.5)

        asyncio.run(exercise())

    def test_debug_rolls_back_idoc_without_a_matching_transition(self):
        project = project_for_replay()
        task = project.tasks[0]
        task.transitions = []
        bridge = ReplayBridge(1)
        async def exercise():
            bridge.loop, bridge.finish = asyncio.get_running_loop(), asyncio.Event()
            bridge.checked.add('0')
            view = main.debugger.start(project, task.id, {}, {project.resources[0].id: project.resources[0]}, {}, [])
            session_id = view['sessionId']
            listener = asyncio.create_task(main._continuous_event_loop(project, task, task.activities[0], 'local', session_id))
            try:
                await asyncio.wait_for(bridge.finish.wait(), timeout=3)
                self.assertEqual(bridge.errors, ['0'], 'A rejected route must roll back its SAP delivery')
                arrivals = [entry['sapIDoc'] for entry in main.debugger.sessions[session_id]['logs'] if 'sapIDoc' in entry]
                self.assertEqual([item['documentNumber'] for item in arrivals], ['0'])
                rows = activity_timings(main.debugger.sessions[session_id]['logs'])
                intakes = [row for row in rows if row['activityId'] == 'listener']
                self.assertEqual(len(intakes), 1)
                self.assertEqual(intakes[0]['timingScope'], 'idoc_intake')
                self.assertGreater(intakes[0]['durationMs'], 0)
            finally:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)
                main.debugger.sessions.pop(session_id, None)
                main.runtime_states.pop(project.id, None)
        with patch('app.sap.start_sap_listener', return_value=bridge), patch('app.main._persist_debug_logs', new_callable=AsyncMock):
            asyncio.run(exercise())

    def test_unsplit_package_is_rolled_back_and_bridge_error_is_reported_while_idle(self):
        cfg = {'operation': 'idoc_listener', 'programId': 'REPLAY', 'gatewayHost': 'replay.invalid',
               'gatewayService': 'sapgw00', 'mode': 'external'}
        bridge = Mock()
        bridge.process.poll.return_value = None
        bridge.next_event = AsyncMock(side_effect=[
            {'event': 'sap_request', 'deliveryId': 'package', 'payload': {'tables': {
                'IDOC_CONTROL_REC_40': [{'DOCNUM': '1'}, {'DOCNUM': '2'}],
            }}},
            {'event': 'jco_log', 'level': 'ERROR', 'phase': 'request_callback', 'TID': 'failed-tid',
             'error': 'Malformed IDoc package'},
        ])
        adapter = SapAdapter()
        async def exercise():
            with patch('app.sap.start_sap_listener', return_value=bridge):
                with self.assertRaisesRegex(ValueError, 'multiple IDoc control rows'):
                    await adapter.receive_idoc(cfg)
                bridge.acknowledge.assert_called_once_with('package', False)
                result = await adapter.receive_idoc(cfg)
                self.assertFalse(result['received'])
                self.assertEqual(result['jcoDiagnostics'][0]['TID'], 'failed-tid')
                self.assertEqual(result['jcoDiagnostics'][0]['error'], 'Malformed IDoc package')
        asyncio.run(exercise())

    def test_waiting_for_a_cancelled_listener_allows_its_cleanup_to_finish(self):
        async def exercise():
            running, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            closed = False

            async def listener():
                nonlocal closed
                try:
                    running.set()
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
                    closed = True

            task = asyncio.create_task(listener())
            await running.wait()
            task.cancel()
            await cleaning.wait()
            waiter = asyncio.create_task(main._cancel_and_wait(task))
            await asyncio.sleep(0)
            release.set()
            await waiter
            self.assertTrue(closed)

        asyncio.run(exercise())

    def test_studio_and_both_archives_commit_every_parsed_idoc(self):
        project = project_for_replay()
        count = int(os.environ.get('MINA_SAP_REPLAY_RECORDS', '48'))

        async def measure(mode, run, bridge):
            bridge.loop, bridge.finish = asyncio.get_running_loop(), asyncio.Event()
            start = time.perf_counter()
            listener = asyncio.create_task(run)
            done = asyncio.create_task(bridge.finish.wait())
            try:
                completed, _ = await asyncio.wait({listener, done}, timeout=600, return_when=asyncio.FIRST_COMPLETED)
                if listener in completed:
                    await listener
                    self.fail('SAP listener stopped before all deliveries were acknowledged')
                self.assertEqual(bridge.errors, [])
                self.assertEqual(len(bridge.committed), count)
                self.assertEqual(len(bridge.checked), count)
                self.assertTrue(1 < bridge.maximum_inflight <= 8, bridge.maximum_inflight)
                print(f'Synthetic SAP replay ({mode}): {count:,} IDocs in {time.perf_counter() - start:.3f} seconds', flush=True)
            finally:
                listener.cancel()
                done.cancel()
                await asyncio.gather(listener, done, return_exceptions=True)

        def validate_runtime(runtime, bridge):
            run = runtime.run

            async def checked(*args, **kwargs):
                result = await run(*args, **kwargs)
                if result.status == 'completed':
                    bridge.check(result.output, kwargs['transport']['deliveryId'])
                return result

            return patch.object(runtime, 'run', checked)

        with self.subTest(mode='studio-run'), tempfile.TemporaryDirectory() as log_directory:
            bridge, runtime = ReplayBridge(count), WorkflowRuntime()
            task = project.tasks[0]
            try:
                with patch('app.sap.start_sap_listener', return_value=bridge), patch.object(main, 'runtime', runtime), \
                        patch.dict(os.environ, {'MINA_RUNTIME_LOG_DIR': log_directory}), validate_runtime(runtime, bridge):
                    asyncio.run(measure('studio-run', main._continuous_sap_event_loop(project, task, task.activities[0], 'local'), bridge))
                    history = main.runtime_states[project.id]['executions']
                    self.assertEqual(len(history), min(count, 100))
                    self.assertEqual(len({entry['sapIDoc']['documentNumber'] for entry in history}), len(history))
                    self.assertTrue(all(entry['sapIDoc']['transactionId'] for entry in history))
                    for entry in history:
                        intakes = [row for row in entry['activityTimings'] if row['activityId'] == 'listener']
                        self.assertEqual(len(intakes), 1)
                        self.assertEqual(intakes[0]['timingScope'], 'idoc_intake')
                        self.assertGreater(intakes[0]['durationMs'], 0)
                        self.assertNotIn('_sapIntakeMs', entry['activityOutputs']['listener']['output'])
            finally:
                close_project_log_handlers(project.id)
                main.runtime_states.pop(project.id, None)

        for mode, export, sap_module in [('python-engine', engine_python_files, 'application.engine.sap'),
                                         ('python-direct', raw_python_files, 'application.native.sap')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules):
                bridge = ReplayBridge(count)
                for name, content in export(project.model_dump(mode='json'), {'local': []}).items():
                    target = Path(folder) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                sys.path.insert(0, folder)
                try:
                    application = importlib.import_module('application.main')
                    with patch(f'{sap_module}.start_sap_listener', return_value=bridge):
                        if mode == 'python-engine':
                            with validate_runtime(application.RUNTIME, bridge):
                                asyncio.run(measure(mode, application.run_application('local'), bridge))
                        else:
                            task = application.TASKS['starter']

                            async def checked(context, **kwargs):
                                output = await task(context, **kwargs)
                                bridge.check(output, context.transport['deliveryId'])
                                return output

                            with patch.dict(application.TASKS, {'starter': checked}):
                                asyncio.run(measure(mode, application.managed_run(application.run_application('local')), bridge))
                            application.connectors.close_sap()
                finally:
                    sys.path.remove(folder)
