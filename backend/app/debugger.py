from __future__ import annotations
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
from .models import Project
from .runtime import WorkflowRuntime
from .time_utils import log_timestamp

class DebugManager:
    def __init__(self, runtime: WorkflowRuntime):
        self.runtime = runtime
        self.sessions: dict[str, dict] = {}

    def start(self, project: Project, task_id: str, initial: dict, resources: dict, properties: dict, breakpoints: list[str], environment: str = 'local', breakpoint_conditions: dict[str, str] | None = None, watches: list[str] | None = None, pause_on_error: bool = True):
        task = next((item for item in project.tasks if item.id == task_id), None)
        if not task: raise ValueError('Task not found')
        incoming = {edge.target for edge in task.transitions}
        root_activities = [item for item in task.activities if item.id not in incoming]
        starters = [item for item in root_activities if item.type in ('start','timer','http_listener') or (item.type in ('rest','soap','ems','jms','kafka','pubsub') and item.config.get('operation') in ('receiver','service','receive','receive_message','subscribe','queue_receiver','topic_subscriber'))]
        starters = starters or [item for item in task.activities if item.id not in incoming]
        if not starters: raise ValueError('Task has no starting activity')
        session_id = str(uuid4())
        execution_state = {'activities': {}, 'tasks': {task.id: {'name': task.name, 'input': deepcopy(initial), 'activities': {}}}}
        logs = [{'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug session started: {project.name} / {task.name}', 'taskId': task.id, 'sessionId': session_id}]
        group_plans = self.runtime.compile_groups(task)
        context = {'input': initial, 'vars': {}, 'last': initial, 'resources': resources, 'properties': properties, 'project': project, 'runtime': self.runtime, 'logs': logs, 'activities': execution_state['activities'], 'tasks': execution_state['tasks'], 'context': {'taskId': task.id, 'activityId': starters[0].id, 'environment': environment, 'debugSessionId': session_id, 'executionId': session_id}, '_process': task, 'groupStack': [], 'jdbcTransactions': {}}
        operation = starters[0].config.get('operation')
        continuous_listener = starters[0].type in ('timer', 'file', 'ems', 'jms', 'amqp', 'kafka', 'pubsub', 'sap') and operation in ('schedule', 'poll', 'queue_receiver', 'topic_subscriber', 'receive_message', 'receive', 'get', 'subscribe', 'idoc_listener', 'rfc_bapi_listener')
        self.sessions[session_id] = {
            'id': session_id, 'project': project, 'environment': environment, 'executionState': execution_state,
            'frames': [{'taskId': task.id, 'activityId': starters[0].id, 'context': context}],
            'breakpoints': set(breakpoints), 'logs': logs, 'status': 'listening' if continuous_listener else 'paused',
            'breakpointConditions': dict(breakpoint_conditions or {}), 'watches': list(dict.fromkeys(watches or [])),
            'pauseOnError': bool(pause_on_error), 'pauseReason': 'event-listener' if continuous_listener else 'entry',
            'listenerMode': continuous_listener, 'listenerTaskId': task.id, 'listenerActivityId': starters[0].id,
            'initial': initial, 'resources': resources, 'properties': properties,
            'groupPlans': {task.id: group_plans},
            'stopRequested': False,
        }
        if continuous_listener:
            logs.append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'listener', 'message': f'{starters[0].name} is ready and waiting for events', 'activityId': starters[0].id, 'taskId': task.id, 'sessionId': session_id})
        return self.view(self.sessions[session_id])

    def _evaluate(self, expression: str, ctx: dict):
        expression = str(expression or '').strip()
        if not expression: return None
        if expression.startswith('${') and expression.endswith('}'):
            return self.runtime.resolve(expression, ctx)
        if expression.startswith(('input.', 'last.', 'vars.', 'context.', 'properties.')):
            return self.runtime.resolve('${' + expression + '}', ctx)
        return self.runtime.resolve(expression, ctx)

    def _breakpoint_hit(self, state: dict, activity) -> bool:
        if not activity or activity.id not in state.get('breakpoints', set()): return False
        expression = str(state.get('breakpointConditions', {}).get(activity.id) or '').strip()
        if not expression:
            state['pauseReason'] = f'breakpoint:{activity.id}'
            return True
        frame = state.get('frames', [])[-1] if state.get('frames') else None
        try:
            matched = bool(self.runtime.condition(expression, frame['context'])) if frame else False
        except Exception as exc:
            state['logs'].append({'time': log_timestamp(), 'level': 'WARN', 'kind': 'debug', 'message': f'Conditional breakpoint on {activity.name} could not be evaluated: {exc}', 'activityId': activity.id})
            matched = True
        if matched: state['pauseReason'] = f'conditional-breakpoint:{activity.id}'
        return matched

    def rearm_listener(self, state: dict):
        if not state.get('listenerMode') or state.get('status') == 'stopped' or state.get('stopRequested'): return
        task = next(item for item in state['project'].tasks if item.id == state['listenerTaskId'])
        activity_id = state['listenerActivityId']
        execution_state = state['executionState']
        context = {
            'input': state.get('initial', {}), 'vars': {}, 'last': state.get('initial', {}),
            'resources': state['resources'], 'properties': state['properties'], 'project': state['project'],
            'runtime': self.runtime, 'logs': state['logs'], 'activities': execution_state['activities'],
            'tasks': execution_state['tasks'],
            'context': {'taskId': task.id, 'activityId': activity_id, 'environment': state['environment'], 'debugSessionId': state['id'], 'executionId': state['id']},
            '_process': task, 'groupStack': [], 'jdbcTransactions': {},
        }
        state['frames'] = [{'taskId': task.id, 'activityId': activity_id, 'context': context}]
        state['status'] = 'listening'

    async def trigger_event(self, session_id: str, output: dict):
        state = self.sessions.get(session_id)
        if not state or state.get('stopRequested') or not state.get('listenerMode') or state.get('status') != 'listening': return self.view(state) if state else None
        frame = state['frames'][-1]
        task = next(item for item in state['project'].tasks if item.id == frame['taskId'])
        activity = next(item for item in task.activities if item.id == frame['activityId'])
        ctx = frame['context']; ctx['last'] = output; ctx['context']['activityId'] = activity.id
        now = log_timestamp()
        state['logs'].append({'time': now, 'level': 'INFO', 'kind': 'event', 'message': f'Event received: {task.name} / {activity.name}', 'activityId': activity.id, 'taskId': task.id, 'sessionId': session_id})
        self.runtime.record_activity_output(activity, output, ctx, output)
        outgoing = [edge for edge in task.transitions if edge.source == activity.id]
        chosen_edges = self.runtime.select_group_transitions(self.runtime.eligible_success_transitions(outgoing, ctx), ctx, state.get('groupPlans', {}).get(task.id, {}))
        if not chosen_edges:
            state['logs'].append({'time': now, 'level': 'ERROR', 'kind': 'event', 'message': f'{activity.name} has no matching outgoing transition', 'activityId': activity.id, 'taskId': task.id})
            self.rearm_listener(state)
            return self.view(state)
        frame['parallelQueue'] = [edge.target for edge in chosen_edges[1:]]
        frame['activityId'] = chosen_edges[0].target
        state['status'] = 'running'
        while state['status'] == 'running' and not state.get('stopRequested'):
            current = self.current_activity(state)
            if self._breakpoint_hit(state, current):
                state['status'] = 'paused'
                break
            await self.step(state)
        if state['status'] == 'completed': self.rearm_listener(state)
        return self.view(state)

    async def action(self, session_id: str, action: str, options: dict | None = None):
        state = self.sessions.get(session_id)
        if not state: raise ValueError('Debug session not found')
        if action == 'stop':
            return await self.stop(session_id)
        options = options or {}
        if action in ('preview_activity', 'test_activity', 'mock_step'):
            if state['status'] != 'paused' or state.get('_testing'):
                raise ValueError('Pause the debugger before testing or supplying an activity result')
            frame = state['frames'][-1]
            task_id = options.get('task_id') or frame['taskId']
            task = next((item for item in state['project'].tasks if item.id == task_id), None)
            if not task: raise ValueError('Selected process was not found in the debug project')
            activity_id = options.get('activity_id') or frame['activityId']
            activity = next((item for item in task.activities if item.id == activity_id), None)
            if not activity: raise ValueError('Select an activity in the selected process')
            if action == 'mock_step':
                if task.id != frame['taskId'] or activity_id != frame['activityId']:
                    raise ValueError('Mock output can only be supplied for the currently paused activity')
                if 'value' not in options: raise ValueError('Supply a mock output value')
                state['_mockOutput'] = deepcopy(options['value'])
                state['_mockActivityId'] = activity_id
                try:
                    return await self.action(session_id, 'step_over')
                finally:
                    state.pop('_mockOutput', None)
                    state.pop('_mockActivityId', None)
            source = frame['context']
            ctx = {**source, **{key: deepcopy(source.get(key, {})) for key in
                               ('input', 'last', 'vars', 'context', 'activities', 'tasks', 'properties')},
                   'logs': [], 'groupStack': [], 'jdbcTransactions': {}}
            if 'value' in options:
                ctx['input'] = deepcopy(options['value'])
                ctx['last'] = deepcopy(options['value'])
            ctx['context']['activityId'] = activity.id
            ctx['context']['taskId'] = task.id
            ctx['_process'] = task
            if task.id != frame['taskId']:
                ctx['vars'] = {}
                ctx['activities'] = deepcopy(source.get('tasks', {}).get(task.id, {}).get('activities', {}))
            ctx['_debugInputOverrides'] = {activity.id: deepcopy(options.get('fields') or {})}
            result = {'activityId': activity.id, 'activityName': activity.name, 'taskId': task.id,
                      'mode': action, 'input': ctx['input'], 'status': 'preview'}
            started = perf_counter()
            state['_testing'] = True
            try:
                result['resolvedInputs'] = self.runtime.resolve_activity_config(activity, ctx)
                if action == 'test_activity':
                    result['output'] = await asyncio.wait_for(self.runtime.execute_with_policy(activity, ctx),
                        timeout=float(options.get('timeout_seconds', 10)))
                    result['status'] = 'passed'
                    if options.get('assertion'):
                        ctx['last'] = result['output']
                        passed = bool(self.runtime.condition(options['assertion'], ctx))
                        result['assertion'] = {'expression': options['assertion'], 'passed': passed}
                        result['status'] = 'passed' if passed else 'assertion_failed'
            except Exception as exc:
                result.update(status='failed', error=str(exc) or type(exc).__name__)
            finally:
                state['_testing'] = False
            result['durationMs'] = round((perf_counter() - started) * 1000, 3)
            result['logs'] = ctx['logs']
            state['lastActivityTest'] = result
            state['testHistory'] = (state.get('testHistory', []) + [
                {key: result.get(key) for key in ('activityId', 'activityName', 'mode', 'status', 'durationMs', 'error')}
            ])[-30:]
            return self.view(state)
        if state.get('_testing') and action not in ('configure', 'evaluate'):
            raise ValueError('An activity test is already running')
        if action == 'configure':
            if options.get('breakpoints') is not None: state['breakpoints'] = set(options['breakpoints'])
            if options.get('breakpoint_conditions') is not None: state['breakpointConditions'] = dict(options['breakpoint_conditions'])
            if options.get('watches') is not None: state['watches'] = list(dict.fromkeys(item for item in options['watches'] if str(item).strip()))
            if options.get('pause_on_error') is not None: state['pauseOnError'] = bool(options['pause_on_error'])
            return self.view(state)
        if action == 'evaluate':
            frame = state.get('frames', [])[-1] if state.get('frames') else None
            expression = str(options.get('expression') or '')
            try: state['lastEvaluation'] = {'expression': expression, 'value': self._evaluate(expression, frame['context']) if frame else None}
            except Exception as exc: state['lastEvaluation'] = {'expression': expression, 'error': str(exc)}
            return self.view(state)
        if action == 'set_value':
            if state.get('status') != 'paused': raise ValueError('Runtime values can only be changed while the debugger is paused')
            frame = state.get('frames', [])[-1] if state.get('frames') else None
            path = str(options.get('path') or '').strip()
            root, _, child = path.partition('.')
            if not frame or root not in ('input', 'last', 'vars'): raise ValueError('Editable paths are input, last, vars, or their dotted child paths')
            value = deepcopy(options.get('value'))
            if not child:
                if root == 'vars' and not isinstance(value, dict): raise ValueError('vars must be a JSON object')
                frame['context'][root] = value
            else:
                target = deepcopy(frame['context'].get(root, {}))
                if not isinstance(target, dict): raise ValueError(f'{root} is not an object; replace the entire {root} value instead')
                self.runtime.assign_path(target, child, value)
                frame['context'][root] = target
            state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'debug', 'message': f'Debug value changed: {path}', 'sessionId': session_id})
            return self.view(state)
        if state.get('stopRequested'):
            return self.view(state)
        if action == 'pause': state['status'] = 'paused'; state['pauseReason'] = 'user'; return self.view(state)
        if state.get('listenerMode') and state['status'] == 'listening': return self.view(state)
        if state['status'] in ('completed','failed','stopped'): return self.view(state)
        initial_depth = len(state['frames'])
        try:
            if action in ('step_in','jump_in'):
                await self.step(state, enter_subtask=True)
            elif action in ('step_out','jump_out'):
                while state['status'] not in ('completed','failed') and len(state['frames']) >= initial_depth: await self.step(state)
            elif action == 'step_over':
                await self.step(state)
            else:
                state['status'] = 'running'
                run_to = str(options.get('activity_id') or '') if action == 'run_to' else ''
                state['_autoContinue'] = True
                while state['status'] == 'running' and not state.get('stopRequested'):
                    await self.step(state)
                    current = self.current_activity(state)
                    if current and run_to and current.id == run_to:
                        state['status'] = 'paused'; state['pauseReason'] = f'run-to:{run_to}'
                    elif self._breakpoint_hit(state, current): state['status'] = 'paused'
                state['_autoContinue'] = False
            if state['status'] == 'running': state['status'] = 'paused'; state['pauseReason'] = action
            if state.get('listenerMode') and state['status'] == 'completed': self.rearm_listener(state)
        except asyncio.CancelledError:
            # Stop cancels the task currently driving Continue/Step.  This is
            # an intentional lifecycle transition, not a failed activity.
            state['_autoContinue'] = False
            raise
        except Exception as exc:
            state['_autoContinue'] = False
            state['logs'].append({'time': log_timestamp(), 'level': 'ERROR', 'message': str(exc), 'activityId': self.current_activity(state).id if self.current_activity(state) else None})
            state['status'] = 'failed'
        return self.view(state)

    async def stop(self, session_id: str):
        """Rollback open group resources and make a debug stop idempotent."""
        state = self.sessions.get(session_id)
        if not state: raise ValueError('Debug session not found')
        state['stopRequested'] = True
        state['status'] = 'stopping'
        state['pauseReason'] = 'stop'
        for frame in reversed(state.get('frames', [])):
            plans = state.get('groupPlans', {}).get(frame['taskId'], {})
            while frame['context'].get('groupStack'):
                group_state = frame['context']['groupStack'].pop()
                plan = plans.get(group_state.get('id'))
                if not plan: continue
                try:
                    await self.runtime._finish_group(group_state, plan, frame['context'], False)
                except Exception as exc:
                    state['logs'].append({'time': log_timestamp(), 'level': 'WARN', 'kind': 'lifecycle', 'message': f'Resource cleanup warning: {exc}', 'sessionId': session_id})
            frame['context'].get('jdbcTransactions', {}).clear()
            frame.pop('parallelQueue', None)
        state['status'] = 'stopped'
        message = f'Debug session stopped: {state["project"].name}'
        if not state['logs'] or state['logs'][-1].get('message') != message:
            state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': message, 'sessionId': session_id})
        return self.view(state)

    async def step(self, state: dict, enter_subtask=False):
        if state.get('stopRequested'):
            state['status'] = 'stopped'
            return
        if not state['frames']: state['status'] = 'completed'; return
        frame = state['frames'][-1]; project = state['project']; task = next(item for item in project.tasks if item.id == frame['taskId'])
        plans = state.setdefault('groupPlans', {}).setdefault(task.id, self.runtime.compile_groups(task))
        ctx = frame['context']; ctx.setdefault('_process', task); ctx.setdefault('groupStack', []); ctx.setdefault('jdbcTransactions', {})
        entered = await self.runtime.enter_group_boundaries(frame['activityId'], ctx, plans)
        if entered is None:
            frame['activityId'] = ''; state['status'] = 'completed'; return
        frame['activityId'] = entered
        activity = next(item for item in task.activities if item.id == frame['activityId'])
        if '_mockOutput' in state and state.get('_mockActivityId') != activity.id:
            raise ValueError('Group scheduling changed the current activity; supply mock output at its next pause')
        state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity', 'message': f'Activity started: {task.name} / {activity.name}', 'activityId': activity.id, 'taskId': task.id, 'activityType': activity.type, 'operation': activity.config.get('operation') or activity.type})
        activity_started = perf_counter()
        if activity.type == 'call_task' and '_mockOutput' not in state:
            dynamic_id = self.runtime.resolve(activity.config.get('dynamicTaskId', ''), ctx)
            target_id = str(dynamic_id or activity.config.get('taskId') or '').strip()
            target = next((item for item in project.tasks if (item.id == target_id or item.name.casefold() == target_id.casefold()) and item.kind == 'subtask'), None)
            if target:
                incoming = {edge.target for edge in target.transitions}; starter = next((item for item in target.activities if item.type == 'start'), None) or next(item for item in target.activities if item.id not in incoming)
                values = self.runtime.map_input_values(activity.config.get('inputMappings', {}), ctx)
                mapped = self.runtime.unwrap_boundary(values, 'payload', ctx['last'])
                child_context = {**ctx, 'input': mapped, 'last': mapped, 'context': {'taskId': target.id, 'activityId': starter.id, 'environment': project.active_environment, 'debugSessionId': state['id'], 'executionId': state['id']}, '_process': target, 'groupStack': [], 'jdbcTransactions': {}}
                ctx['tasks'].setdefault(target.id, {'name': target.name, 'activities': {}})
                state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'call', 'message': f'Entering Sub Task: {target.name}', 'activityId': activity.id, 'taskId': task.id, 'calledTaskId': target.id})
                ctx['tasks'][target.id]['input'] = mapped
                state['frames'].append({'taskId': target.id, 'activityId': starter.id, 'context': child_context, 'callInput': mapped})
                # Step In pauses on the child Start; Continue keeps the debug
                # engine running through the child frame and returns to the
                # caller only after the child End completes.
                state['status'] = 'paused' if enter_subtask else 'running'
                return
        ctx['context']['activityId'] = activity.id
        activity_input = ctx['last']
        try:
            if '_mockOutput' in state:
                ctx['last'] = state.pop('_mockOutput')
                state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'debug',
                                     'message': f'Mock output supplied: {activity.name}', 'activityId': activity.id})
            else:
                ctx['last'] = await self.runtime.execute_with_policy(activity, ctx)
        except Exception as exc:
            duration = round((perf_counter() - activity_started) * 1000, 3)
            state['logs'].append({'time': log_timestamp(), 'level': 'ERROR', 'kind': 'activity', 'message': f'Activity failed: {task.name} / {activity.name} in {duration:.3f} ms: {exc}', 'activityId': activity.id, 'taskId': task.id, 'durationMs': duration})
            outgoing = [edge for edge in task.transitions if edge.source == activity.id]
            error_edge = next((edge for edge in outgoing if edge.type == 'error'), None)
            fault = self.runtime.fault_payload(exc, activity.id)
            state['lastException'] = fault
            ctx['last'] = fault; ctx['context']['error'] = fault; ctx['vars']['error'] = fault
            if error_edge:
                target = await self.runtime.leave_group_boundaries(activity.id, error_edge.target, ctx, plans, success=False)
                if target:
                    frame['activityId'] = target
                    pause = state.get('pauseOnError') or not state.get('_autoContinue')
                    state['status'] = 'paused' if pause else 'running'
                    if pause: state['pauseReason'] = 'exception' if state.get('pauseOnError') else 'step'
                    return
            retry_target = await self.runtime.retry_failed_group(ctx, plans)
            if retry_target:
                frame['activityId'] = retry_target
                pause = state.get('pauseOnError') or not state.get('_autoContinue')
                state['status'] = 'paused' if pause else 'running'
                if pause: state['pauseReason'] = 'exception' if state.get('pauseOnError') else 'step'
                return
            while ctx.get('groupStack'):
                group_state = ctx['groupStack'].pop(); await self.runtime._finish_group(group_state, plans[group_state['id']], ctx, False)
            raise
        duration = round((perf_counter() - activity_started) * 1000, 3)
        state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity', 'message': f'Activity completed: {task.name} / {activity.name} in {duration:.3f} ms', 'activityId': activity.id, 'taskId': task.id, 'durationMs': duration})
        if isinstance(ctx['last'], dict) and isinstance(ctx['last'].get('publishTiming'), dict):
            timing = ctx['last']['publishTiming']
            state['logs'][-1]['publishTiming'] = timing
            state['logs'][-1]['message'] += f" (send queue {timing.get('queueMs', 0)} ms; Java bridge {timing.get('bridgeMs', 0)} ms)"
        self.runtime.record_activity_output(activity, ctx['last'], ctx, activity_input)
        outgoing = [edge for edge in task.transitions if edge.source == activity.id]
        chosen_edges = self.runtime.select_group_transitions(self.runtime.eligible_success_transitions(outgoing, ctx), ctx, plans)
        if activity.type == 'end' or not chosen_edges:
            target = await self.runtime.leave_group_boundaries(activity.id, None, ctx, plans)
            if target:
                frame['activityId'] = target
                return
            pending = frame.get('parallelQueue') or []
            if activity.type == 'end' and pending:
                frame['activityId'] = pending.pop(0)
                frame['parallelQueue'] = pending
                return
            completed = state['frames'].pop()
            completed['context']['tasks'].setdefault(completed['taskId'], {'activities': {}})['output'] = completed['context']['last']
            if not state['frames']:
                state['output'] = completed['context']['last']; state['status'] = 'completed'
                state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug job completed: {project.name} / {task.name}'})
                return
            parent = state['frames'][-1]; parent['context']['last'] = completed['context']['last']
            parent_task = next(item for item in project.tasks if item.id == parent['taskId']); call = next(item for item in parent_task.activities if item.id == parent['activityId'])
            parent['context']['_activityMetadata'] = {'calledTaskId': completed['taskId']}
            self.runtime.record_activity_output(call, completed['context']['last'], parent['context'], completed.get('callInput'))
            edge = next((item for item in parent_task.transitions if item.source == call.id and item.type == 'success'), None)
            if edge: parent['activityId'] = edge.target
            return
        pending = frame.get('parallelQueue') or []
        frame['parallelQueue'] = pending + [edge.target for edge in chosen_edges[1:]]
        target = await self.runtime.leave_group_boundaries(activity.id, chosen_edges[0].target, ctx, plans)
        if target is None:
            state['status'] = 'completed'; return
        frame['activityId'] = target

    def current_activity(self, state):
        if not state['frames']: return None
        frame = state['frames'][-1]; task = next(item for item in state['project'].tasks if item.id == frame['taskId'])
        return next((item for item in task.activities if item.id == frame['activityId']), None)

    def view(self, state):
        current = self.current_activity(state)
        execution_state = state.get('executionState', {})
        group_stack = state['frames'][-1]['context'].get('groupStack', []) if state.get('frames') else []
        active_ids = []
        for frame in state.get('frames', []):
            if frame.get('activityId'): active_ids.append(frame['activityId'])
            active_ids.extend(frame.get('parallelQueue') or [])
        frame = state['frames'][-1] if state.get('frames') else None
        ctx = frame.get('context', {}) if frame else {}
        watch_values = []
        # Keep testing results separate from the actual workflow outputs.
        for expression in state.get('watches', []):
            try: watch_values.append({'expression': expression, 'value': self._evaluate(expression, ctx)})
            except Exception as exc: watch_values.append({'expression': expression, 'error': str(exc)})
        return {'lastActivityTest': state.get('lastActivityTest'), 'testHistory': state.get('testHistory', []), 'sessionId': state['id'], 'status': state['status'], 'pauseReason': state.get('pauseReason'), 'currentActivityId': current.id if current else None, 'currentActivityIds': list(dict.fromkeys(active_ids)), 'currentTaskId': state['frames'][-1]['taskId'] if state['frames'] else None, 'currentGroupIds': [item['id'] for item in group_stack], 'groupIterations': {item['id']: item.get('iteration', 0) for item in group_stack}, 'callStack': [{'taskId': frame['taskId'], 'activityId': frame['activityId'], 'groupIds': [item['id'] for item in frame['context'].get('groupStack', [])]} for frame in state['frames']], 'logs': state['logs'], 'output': state.get('output', {}), 'activityOutputs': execution_state.get('activities', {}), 'taskOutputs': execution_state.get('tasks', {}), 'endpoints': state.get('endpoints', []), 'breakpoints': sorted(state.get('breakpoints', set())), 'breakpointConditions': state.get('breakpointConditions', {}), 'pauseOnError': state.get('pauseOnError', True), 'watches': state.get('watches', []), 'watchValues': watch_values, 'variables': {'input': ctx.get('input', {}), 'last': ctx.get('last', {}), 'vars': ctx.get('vars', {}), 'context': ctx.get('context', {})}, 'lastException': state.get('lastException'), 'lastEvaluation': state.get('lastEvaluation')}
