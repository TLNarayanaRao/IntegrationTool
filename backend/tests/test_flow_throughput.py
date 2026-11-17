"""Correctness of complete-flow measurement; memory brokers do not prove rates."""
import argparse
import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load():
    path = Path(__file__).parents[2] / 'scripts/flow-throughput.py'
    spec = importlib.util.spec_from_file_location('flow_throughput', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class CompleteFlowHarnessTests(unittest.TestCase):
    def test_debug_cleanup_is_not_evicted_by_bounded_history(self):
        module=load();project=module.project_for('mapper',{})
        with tempfile.TemporaryDirectory() as folder:
            executor=module.Executor('debug',project,str(Path(folder)/'worker.log'))
            executor.manager.history_limit=1
            def cleanup(session):
                executor.manager.sessions['newer']={'status':'completed'}
                executor.manager._prune_history('newer')
                self.assertIn(session,executor.manager.sessions)
                self.assertEqual(executor.manager.sessions[session]['status'],'stopping')
            async def exercise():
                try:
                    with patch.object(module,'terminate_execution_processes',side_effect=cleanup):
                        result=await executor.execute('publish',{'records':[module.record('qa',0,1024)[0]]})
                    self.assertEqual(result[0]['seq'],0)
                finally:await executor.close()
            asyncio.run(exercise())

    def test_run_and_debug_execute_every_mapping_and_loop_transition(self):
        module = load()
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            for family in ('mapper', 'transformer', 'kafka', 'jms', 'pubsub'):
                for mode in ('run', 'debug'):
                    args = argparse.Namespace(family=family, mode=mode, records=19, deadline=30,
                        workers=2, batch_size=5, payload_bytes=1024, diagnostics=folder)
                    report = asyncio.run(module.measure(args, {'dedicatedTestResources': True,
                        'connection': {'mode': 'memory'}, 'destinations': ['first', 'second']}))
                    self.assertTrue(report['passed'], (family, mode, report))
                    self.assertEqual(report['uniquePayloadsVerified'], 19)
                    self.assertGreater(report['normalRunDebugLogEntries'], 19)

    def test_wrong_mapper_result_cannot_be_reported_as_throughput(self):
        module = load(); original = module.Executor.execute
        async def corrupt(executor, task, initial):
            result = await original(executor, task, initial)
            if task == 'publish':
                rows = result.get('result', result) if isinstance(result, dict) else result
                rows[0]['name'] = 'corrupted'
            return result
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            args = argparse.Namespace(family='mapper', mode='run', records=5, deadline=30,
                workers=1, batch_size=5, payload_bytes=1024, diagnostics=folder)
            with patch.object(module.Executor, 'execute', corrupt):
                report = asyncio.run(module.measure(args, {}))
            self.assertFalse(report['passed']); self.assertEqual(report['exceptionType'], 'AssertionError')

    def test_real_generated_mapper_archives_preserve_all_batch_outputs(self):
        module = load()
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            for mode in ('python-direct', 'python-engine'):
                args = argparse.Namespace(family='mapper', mode=mode, records=11, deadline=30,
                    workers=1, batch_size=4, payload_bytes=1024, diagnostics=folder)
                report = asyncio.run(module.measure(args, {}))
                self.assertTrue(report['passed'], report)
                self.assertEqual(report['uniquePayloadsVerified'], 11)

    def test_deadline_failure_is_reported_and_pending_work_is_cancelled(self):
        module = load()
        async def slow(*_): await asyncio.sleep(2)
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            args = argparse.Namespace(family='mapper', mode='run', records=5, deadline=.01,
                workers=1, batch_size=5, payload_bytes=1024, diagnostics=folder)
            with patch.object(module.Executor, 'execute', slow):
                report = asyncio.run(module.measure(args, {}))
            self.assertFalse(report['passed']); self.assertEqual(report['records'], 0)
            self.assertEqual(report['exceptionType'], 'TimeoutError')

    def test_business_destination_without_qa_marker_is_rejected(self):
        module = load()
        args = argparse.Namespace(family='kafka')
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            asyncio.run(module.measure(args, {}))


if __name__ == '__main__': unittest.main()
