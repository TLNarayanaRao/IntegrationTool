from __future__ import annotations
import asyncio,os
from collections import defaultdict, deque
from copy import deepcopy
from .debug_trace import DebugTrace
from .execution_analytics import PUBLISH_PHASES, publish_phases
from .flow_graph import parallel_plan
from time import perf_counter
from uuid import uuid4
from .models import Project, find_subtask
from .runtime import WorkflowRuntime
from .observability import instrument, messaging_carrier
from .sap import idoc_delivery_details
from .time_utils import log_timestamp

class _DebugLogs(list):
    def __init__(self,values,limit):
        super().__init__(values);self.limit=limit;self.dropped=0
    def append(self,value):
        super().append(value)
        excess=max(0,len(self)-self.limit)
        if excess:del self[:excess];self.dropped+=excess
    def extend(self,values):
        for value in values:self.append(value)
    def __iadd__(self,values):self.extend(values);return self

class DebugManager:
    def __init__(self, runtime: WorkflowRuntime):
        self.runtime = runtime
        self.sessions: dict[str, dict] = {}
        def limit(name,default):
            try:return max(1,int(os.environ.get(name,default)))
            except (ValueError,TypeError):return default
        self.history_limit=limit('MINA_DEBUG_HISTORY_LIMIT',8)
        self.log_limit=limit('MINA_DEBUG_LOG_LIMIT',10000)
        self.trace_limit = limit('MINA_DEBUG_TRACE_LIMIT', 5000)

    def _prune_history(self,current):
        terminal=[key for key,state in self.sessions.items() if state.get('status') in ('completed','failed','stopped')]
        excess=max(0,len(terminal)-self.history_limit)
        for key in terminal:
            if not excess:break
            if key==current:continue
            self.sessions.pop(key,None);excess-=1

    @staticmethod
    def _branch_context(ctx):
        return {**ctx, 'input': deepcopy(ctx['input']), 'last': deepcopy(ctx['last']),
                'vars': deepcopy(ctx['vars']), 'context': dict(ctx['context'])}

    def _schedule_branches(self, state, frame, task, edges, target=None):
        trace = state['trace']
        targets = [edge.target for edge in edges]
        if len(targets) > 1:
            stack = frame.setdefault('parallelStack', [])
            plan = parallel_plan([(edge.source, edge.target, edge.type) for edge in task.transitions], targets,
                                 [node.id for node in task.activities if node.type in ('end', 'http_response')],
                                 boundary=stack[-1]['join'] if stack else None, fork=frame['activityId'])
            by_target = defaultdict(deque)
            for edge in edges:
                by_target[edge.target].append(edge)
            def traced(part, parent):
                if isinstance(part, str):
                    return {'thread': trace.new_thread('branch', task, part, parent), 'edge': by_target[part].popleft()}
                thread = trace.new_thread('branch group', task, None, parent)
                return {'thread': thread, 'join': part['join'],
                        'branches': [traced(child, thread) for child in part['branches']]}
            self._push_parallel(state, frame, {'join': plan['join'],
                                                'branches': [traced(part, frame.get('threadId')) for part in plan['branches']]})
        elif target is not None and target != targets[0]:
            self._redirect(state, frame, target, 'group loop')
        else:
            trace.edge(frame, edges[0])
            frame['activityId'] = targets[0]

    def _push_parallel(self, state, frame, plan):
        base = self._branch_context(frame['context'])
        thread = frame.get('threadId')
        state['trace'].set_thread(thread, 'waiting')
        frame.setdefault('parallelStack', []).append({'join': plan['join'], 'pending': plan['branches'][1:],
                                                       'base': base, 'threadId': thread})
        self._start_parallel_part(state, frame, plan['branches'][0], base)

    def _start_parallel_part(self, state, frame, part, base):
        frame['context'] = self._branch_context(base)
        frame['threadId'] = part['thread']
        trace = state['trace']
        trace.set_thread(part['thread'], 'active')
        if 'edge' in part:
            trace.edge(frame, part['edge'])
            frame['activityId'] = part['edge'].target
        else:
            self._push_parallel(state, frame, part)

    def _advance_parallel(self, state, frame, terminal=False):
        stack = frame.get('parallelStack') or []
        if not stack or not (terminal or frame['activityId'] == stack[-1]['join']): return False
        block = stack[-1]
        output = frame['context']['last']
        trace = state['trace']
        trace.set_thread(frame.get('threadId'), 'completed')
        if block['pending']:
            self._start_parallel_part(state, frame, block['pending'].pop(0), block['base'])
            return True
        stack.pop()
        frame['threadId'] = block['threadId']
        trace.set_thread(frame.get('threadId'), 'active')
        frame['context'] = block['base']
        frame['context']['last'] = output
        if block['join'] is not None:
            frame['activityId'] = block['join']
            trace.event(frame, 'join', activityId=block['join'])
            return True
        # A terminal nested fork may also finish an enclosing branch.
        return self._advance_parallel(state, frame, terminal=True) if stack else False

    def _settle_branches(self, state):
        if state['frames']:
            frame = state['frames'][-1]
            while frame.get('parallelStack') and frame['activityId'] == frame['parallelStack'][-1]['join']:
                self._advance_parallel(state, frame)

    @staticmethod
    def _redirect(state, frame, target, reason):
        state['trace'].event(frame, 'redirect', activityId=frame['activityId'], targetActivityId=target, reason=reason)
        frame['activityId'] = target

    def start(self, project: Project, task_id: str, initial: dict, resources: dict, properties: dict, breakpoints: list[str], environment: str = 'local', breakpoint_conditions: dict[str, str] | None = None, watches: list[str] | None = None, pause_on_error: bool = True, capture_trace: bool = True):
        task = next((item for item in project.tasks if item.id == task_id), None)
        if not task: raise ValueError('Task not found')
        if task.library_origin: raise ValueError('Debug a project task that calls this library subtask.')
        incoming = {edge.target for edge in task.transitions}
        root_activities = [item for item in task.activities if item.id not in incoming]
        starters = [item for item in root_activities if item.type in ('start','timer','http_listener') or (item.type in ('rest','soap','ems','jms','kafka','pubsub') and item.config.get('operation') in ('receiver','service','receive','receive_message','subscribe','queue_receiver','topic_subscriber'))]
        starters = starters or [item for item in task.activities if item.id not in incoming]
        if not starters: raise ValueError('Task has no starting activity')
        session_id = str(uuid4())
        execution_state = {'activities': {}, 'tasks': {task.id: {'name': task.name, 'input': deepcopy(initial), 'activities': {}}}}
        logs = [{'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug session started: {project.name} / {task.name}', 'taskId': task.id, 'sessionId': session_id}]
        logs=_DebugLogs(logs,self.log_limit)
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
            'trace': DebugTrace(self.trace_limit, capture_trace),
            'entryTaskId': task.id,
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

    def rearm_listener(self, state: dict, complete_request=True):
        state.pop('_brokerTraceCarrier', None)
        if complete_request and state.get('httpPending') is not None:
            from .debug_http import finish_request
            finish_request(state)
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
        state['pauseReason'] = 'event-listener'

    async def trigger_event(self, session_id: str, output: dict):
        state = self.sessions.get(session_id)
        if not state or state.get('stopRequested') or not state.get('listenerMode') or state.get('status') != 'listening': return self.view(state) if state else None
        frame = state['frames'][-1]
        task = next(item for item in state['project'].tasks if item.id == frame['taskId'])
        activity = next(item for item in task.activities if item.id == frame['activityId'])
        intake_started = perf_counter()
        ctx = frame['context']; ctx['input'] = output; ctx['last'] = output; ctx['context']['activityId'] = activity.id
        state['_brokerTraceCarrier'] = messaging_carrier(output)
        trace = state['trace']
        trace.open_job(frame, task)
        trace.resume()
        trace.set_thread(frame.get('threadId'), 'active')
        now = log_timestamp()
        arrival = {'time': now, 'level': 'INFO', 'kind': 'event', 'message': f'Event received: {task.name} / {activity.name}', 'activityId': activity.id, 'taskId': task.id, 'sessionId': session_id}
        self.runtime.record_activity_output(activity, output, ctx, output)
        operation = activity.config.get('operation') or activity.type
        idoc = activity.type == 'sap' and operation == 'idoc_listener'
        duration = (perf_counter() - intake_started) * 1000
        timing_scope = 'event_handoff'
        if idoc:
            duration += ctx.get('transport', {}).get('sapIntakeMs', 0.0)
            arrival['sapIDoc'] = idoc_delivery_details(output)
            timing_scope = 'idoc_intake'
        arrival.update(activityName=activity.name, activityType=activity.type, operation=operation,
                       durationMs=round(duration, 3), timingScope=timing_scope)
        trace.activity(frame, activity, 'received', duration)
        state['logs'].append(arrival)
        outgoing = [edge for edge in task.transitions if edge.source == activity.id]
        chosen_edges = self.runtime.select_group_transitions(self.runtime.eligible_success_transitions(outgoing, ctx), ctx, state.get('groupPlans', {}).get(task.id, {}))
        if not chosen_edges:
            if activity.type == 'sap' and ctx.get('transport') is not None:
                ctx['transport']['eventFailed'] = True
            message = f'{activity.name} has no matching outgoing transition'
            state['logs'].append({'time': now, 'level': 'ERROR', 'kind': 'event', 'message': message, 'activityId': activity.id, 'taskId': task.id})
            trace.finish_job('failed')
            from .debug_http import finish_request
            finish_request(state, message)
            self.rearm_listener(state, complete_request=False)
            return self.view(state)
        self._schedule_branches(state, frame, task, chosen_edges)
        self._settle_branches(state)
        if state.pop('breakOnNextEvent', False):
            state['status'] = 'paused'
            state['pauseReason'] = 'next-event'
            trace.suspend()
            return self.view(state)
        return await self._drive(state, 'continue', {}, check_entry=True)

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
            if not task: raise ValueError('The selected process was not found')
            if task.library_origin: raise ValueError('Select an editable project task in the debugger')
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
            state['_testDriver'] = asyncio.current_task()
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
                state.pop('_testDriver', None)
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
        if action == 'load_task_input':
            frame = state['frames'][-1] if state.get('frames') else None
            current = self.current_activity(state)
            if (state.get('status') != 'paused' or not frame or not current or current.type != 'start'
                    or options.get('task_id') != frame['taskId'] or options.get('activity_id') != current.id
                    or current.id in frame['context'].get('activities', {}) or 'value' not in options):
                raise ValueError('Pause on the selected task’s Start activity before loading task input')
            context = frame['context']
            context['input'] = deepcopy(options['value'])
            context['last'] = deepcopy(options['value'])
            record = context.get('tasks', {}).get(frame['taskId'])
            if record is not None:
                record['input'] = deepcopy(options['value'])
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
        if state.get('stopRequested') or state['status'] in ('completed', 'failed', 'stopped'):
            return self.view(state)
        if action == 'pause':
            if state['status'] == 'running':
                state['pauseRequested'] = True
            return self.view(state)
        if action == 'break_next_event':
            if not state.get('listenerMode'):
                raise ValueError('Break on next event requires a listener session')
            state['breakOnNextEvent'] = not state.get('breakOnNextEvent', False)
            return self.view(state)
        if state['status'] == 'listening':
            return self.view(state)
        if action == 'run_to':
            task_id = options.get('task_id') or state['frames'][-1]['taskId']
            target = next((task for task in state['project'].tasks if task.id == task_id), None)
            if not target or target.library_origin or not any(item.id == options.get('activity_id') for item in target.activities):
                raise ValueError('Select a run-to target in the debug project')
            options = {**options, 'task_id': task_id}
        return await self._drive(state, action, options)

    @instrument('mina.debug', lambda self, state, action, *_args, **_kwargs: {'mina.mode': 'debug', 'mina.debug.action': action},
                lambda self, state, *_args, **_kwargs: state.get('_brokerTraceCarrier') or {})
    async def _drive(self, state, action, options, *, check_entry=False):
        if state.get('_driver'):
            raise ValueError('The debugger is already executing. Pause it before stepping.')
        state['_driver'] = asyncio.current_task()
        state['status'] = 'running'
        trace = state['trace']
        if not trace.job:
            frame = state['frames'][0]
            task = next(task for task in state['project'].tasks if task.id == frame['taskId'])
            trace.open_job(frame, task)
            trace.set_thread(frame.get('threadId'), 'active')
        trace.resume()
        initial_depth = len(state['frames'])
        enter = action in ('step_in', 'jump_in')
        over = action == 'step_over'
        out = action in ('step_out', 'jump_out')
        state['_autoContinue'] = not (enter or over)
        try:
            inspect_current = check_entry
            while state['status'] == 'running' and not state.get('stopRequested'):
                if state.pop('pauseRequested', False):
                    state.update(status='paused', pauseReason='user')
                    break
                if inspect_current or action == 'run_to':
                    current = self.current_activity(state)
                    if (current and action == 'run_to' and current.id == options['activity_id']
                            and state['frames'][-1]['taskId'] == options['task_id']):
                        state.update(status='paused', pauseReason=f'run-to:{current.id}')
                        break
                    if inspect_current and action != 'continue_without_breakpoints' and self._breakpoint_hit(state, current):
                        state['status'] = 'paused'
                        break
                await self.step(state, enter_subtask=enter)
                if state['status'] == 'running' and (enter or (over and len(state['frames']) <= initial_depth)
                                                     or (out and len(state['frames']) < initial_depth)):
                    state.update(status='paused', pauseReason=action)
                inspect_current = True
                if state['status'] == 'running':
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            if not state.get('stopRequested') and state['status'] == 'running':
                state.update(status='paused', pauseReason='interrupted')
            raise
        except Exception as exc:
            current = self.current_activity(state)
            state['logs'].append({'time': log_timestamp(), 'level': 'ERROR', 'message': str(exc), 'activityId': current.id if current else None})
            state['status'] = 'failed'
            from .debug_http import finish_request
            finish_request(state,'HTTP debug execution failed')
        finally:
            state.pop('_driver', None)
            state.pop('_autoContinue', None)
            if state['status'] != 'running':
                state.pop('pauseRequested', None)
            trace.suspend()
            if state['status'] in ('completed', 'failed'):
                trace.finish_job(state['status'])
            if state.get('listenerMode') and state['status'] == 'completed':
                self.rearm_listener(state)
        return self.view(state)

    async def stop(self, session_id: str):
        """Rollback open group resources and make a debug stop idempotent."""
        state = self.sessions.get(session_id)
        if not state: raise ValueError('Debug session not found')
        state['stopRequested'] = True
        from .debug_http import finish_request
        finish_request(state,'HTTP debug session stopped')
        state['status'] = 'stopping'
        state['pauseReason'] = 'stop'
        drivers = {state.get('_driver'), state.get('_testDriver')} - {None, asyncio.current_task()}
        for driver in drivers:
            driver.cancel()
        if drivers:
            await asyncio.wait(drivers, timeout=3)
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
        state['trace'].finish_job('stopped')
        message = f'Debug session stopped: {state["project"].name}'
        if not state['logs'] or state['logs'][-1].get('message') != message:
            state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': message, 'sessionId': session_id})
        return self.view(state)

    async def step(self, state: dict, enter_subtask=False):
        trace = state.get('_httpTraceContext')
        if trace is None:
            await self._step(state, enter_subtask)
            self._settle_branches(state)
            return
        from .http_policy import trace_context
        token = trace_context.set(trace)
        try:
            await self._step(state, enter_subtask)
            self._settle_branches(state)
        finally:
            trace_context.reset(token)

    async def _step(self, state: dict, enter_subtask=False):
        if state.get('stopRequested'):
            state['status'] = 'stopped'
            return
        if not state['frames']: state['status'] = 'completed'; return
        self._settle_branches(state)
        frame = state['frames'][-1]; project = state['project']; task = next(item for item in project.tasks if item.id == frame['taskId'])
        if task.id not in state['groupPlans']:
            state['groupPlans'][task.id] = self.runtime.compile_groups(task)
        plans = state['groupPlans'][task.id]
        ctx = frame['context']; ctx.setdefault('_process', task); ctx.setdefault('groupStack', []); ctx.setdefault('jdbcTransactions', {})
        try:
            entered = await self.runtime.enter_group_boundaries(frame['activityId'], ctx, plans)
        except Exception as error:
            activity = next(item for item in task.activities if item.id == frame['activityId'])
            if not await self._handle_fault(state, frame, task, activity, error, 0):
                self._fail_frame_threads(state['trace'], frame)
                state.update(status='failed', pauseReason='exception')
            return
        if entered is None:
            await self._complete_frame(state, frame, task)
            return
        if entered != frame['activityId']:
            self._redirect(state, frame, entered, 'group boundary')
            return
        activity = next(item for item in task.activities if item.id == frame['activityId'])
        if '_mockOutput' in state and state.get('_mockActivityId') != activity.id:
            raise ValueError('Group scheduling changed the current activity; supply mock output at its next pause')
        state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity', 'message': f'Activity started: {task.name} / {activity.name}', 'activityId': activity.id, 'taskId': task.id, 'activityType': activity.type, 'operation': activity.config.get('operation') or activity.type})
        activity_started = perf_counter()
        trace = state['trace']
        trace.event(frame, 'activity_start', activityId=activity.id, activityName=activity.name)
        activity_input = ctx['last']
        mocked = '_mockOutput' in state
        try:
            if activity.type == 'call_task' and not mocked:
                config = self.runtime.resolve_activity_config(activity, ctx)
                dynamic_id = self.runtime.resolve(config.get('dynamicTaskId', ''), ctx)
                target_id = str(dynamic_id or config.get('taskId') or '').strip()
                target = find_subtask(project.tasks, target_id, caller_id=task.id)
                if target and not target.library_origin:
                    incoming = {edge.target for edge in target.transitions}
                    starter = next((item for item in target.activities if item.type == 'start'), None)
                    if starter is None:
                        starter = next(item for item in target.activities if item.id not in incoming)
                    values = self.runtime.map_input_values(activity.config.get('inputMappings', {}), ctx)
                    mapped = self.runtime.unwrap_boundary(values, 'payload', ctx['last'])
                    child_context = {**ctx, 'input': mapped, 'last': mapped, 'context': {'taskId': target.id, 'activityId': starter.id, 'environment': state['environment'], 'debugSessionId': state['id'], 'executionId': state['id']}, '_process': target, 'groupStack': [], 'jdbcTransactions': {}, 'formatCursors': {}}
                    ctx['tasks'].setdefault(target.id, {'name': target.name, 'activities': {}})
                    state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'call', 'message': f'Entering Sub Task: {target.name}', 'activityId': activity.id, 'taskId': task.id, 'calledTaskId': target.id})
                    ctx['tasks'][target.id]['input'] = mapped
                    child_thread = trace.new_thread('subtask', target, starter.id, frame.get('threadId'))
                    trace.event(frame, 'call', activityId=activity.id, targetTaskId=target.id,
                                targetActivityId=starter.id, targetThreadId=child_thread)
                    trace.set_thread(frame.get('threadId'), 'waiting')
                    trace.set_thread(child_thread, 'active')
                    state['frames'].append({'taskId': target.id, 'activityId': starter.id, 'context': child_context,
                                            'threadId': child_thread, 'callInput': mapped,
                                            'callSetupMs': (perf_counter() - activity_started) * 1000})
                    if enter_subtask:
                        state.update(status='paused', pauseReason='step-in')
                    return
            ctx['context']['activityId'] = activity.id
            if mocked:
                ctx['last'] = state.pop('_mockOutput')
                state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'debug',
                                     'message': f'Mock output supplied: {activity.name}', 'activityId': activity.id})
            else:
                ctx['last'] = await self.runtime.execute_with_policy(activity, ctx)
        except Exception as exc:
            duration = (perf_counter() - activity_started) * 1000
            timing_scope = 'call_setup' if activity.type == 'call_task' else None
            while not await self._handle_fault(state, frame, task, activity, exc, duration, timing_scope):
                if len(state['frames']) == 1:
                    raise
                failed = state['frames'].pop()
                self._fail_frame_threads(trace, failed)
                frame = state['frames'][-1]
                trace.set_thread(frame.get('threadId'), 'active')
                task = next(item for item in project.tasks if item.id == frame['taskId'])
                activity = next(item for item in task.activities if item.id == frame['activityId'])
                trace.event(frame, 'return', activityId=activity.id, targetThreadId=failed.get('threadId'), outcome='failed')
                duration = failed['callSetupMs']
                timing_scope = 'call_setup'
            return
        duration = round((perf_counter() - activity_started) * 1000, 3)
        trace.activity(frame, activity, 'mocked' if mocked else 'completed', duration)
        state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity', 'message': f'Activity completed: {task.name} / {activity.name} in {duration:.3f} ms', 'activityId': activity.id, 'activityName': activity.name, 'activityType': activity.type, 'taskId': task.id, 'durationMs': duration})
        if activity.type in ('ems', 'jms', 'pubsub') and isinstance(ctx['last'], dict):
            timing = publish_phases(ctx['last'].get('publishTiming'))
            if timing:
                state['logs'][-1]['publishTiming'] = timing
                breakdown = ', '.join(f'{PUBLISH_PHASES[key]} {value:.3f} ms' for key, value in timing.items() if key != 'totalMs')
                state['logs'][-1]['message'] += f' ({breakdown})'
        self.runtime.record_activity_output(activity, ctx['last'], ctx, activity_input)
        await self._follow_success(state, frame, task, activity)

    async def _handle_fault(self, state, frame, task, activity, error, duration, timing_scope=None):
        trace = state['trace']
        trace.activity(frame, activity, 'failed', duration)
        state['logs'].append({'time': log_timestamp(), 'level': 'ERROR', 'kind': 'activity', 'message': f'Activity failed: {task.name} / {activity.name} in {duration:.3f} ms: {error}', 'activityId': activity.id, 'activityName': activity.name, 'activityType': activity.type, 'taskId': task.id, 'durationMs': round(duration, 3), **({'timingScope': timing_scope} if timing_scope else {})})
        ctx = frame['context']
        plans = state['groupPlans'][task.id]
        fault = self.runtime.fault_payload(error, activity.id)
        state['lastException'] = fault
        ctx['last'] = fault
        ctx['context']['error'] = fault
        ctx['vars']['error'] = fault
        edge = next((edge for edge in task.transitions if edge.source == activity.id and edge.type == 'error'), None)
        target = await self.runtime.leave_group_boundaries(activity.id, edge.target, ctx, plans, success=False) if edge else None
        if target:
            self._schedule_branches(state, frame, task, [edge], target)
        else:
            target = await self.runtime.recover_group_fault(ctx, plans, fault)
            if target:
                self._redirect(state, frame, target, 'group fault handler')
        if not target:
            caught = self.runtime.route_catch(task.activities, ctx, fault)
            if caught:
                target = caught.id
                self._redirect(state, frame, target, 'task catch')
        if target and (state.get('pauseOnError') or not state.get('_autoContinue')):
            state.update(status='paused', pauseReason='exception' if state.get('pauseOnError') else 'step')
        return bool(target)

    @staticmethod
    def _fail_frame_threads(trace, frame):
        trace.set_thread(frame.get('threadId'), 'failed')
        pending = []
        for block in frame.get('parallelStack') or []:
            trace.set_thread(block['threadId'], 'failed')
            pending.extend(block['pending'])
        while pending:
            part = pending.pop()
            trace.set_thread(part['thread'], 'skipped')
            pending.extend(part.get('branches', []))

    async def _follow_success(self, state, frame, task, activity):
        ctx = frame['context']
        plans = state['groupPlans'][task.id]
        outgoing = [edge for edge in task.transitions if edge.source == activity.id]
        edges = self.runtime.select_group_transitions(self.runtime.eligible_success_transitions(outgoing, ctx), ctx, plans)
        if activity.type in ('end', 'http_response'):
            edges = []
        target = await self.runtime.leave_group_boundaries(activity.id, edges[0].target if edges else None, ctx, plans)
        if target is None:
            await self._complete_frame(state, frame, task)
            return
        if edges:
            self._schedule_branches(state, frame, task, edges, target)
        else:
            self._redirect(state, frame, target, 'group loop')

    async def _complete_frame(self, state, frame, task):
        if self._advance_parallel(state, frame, terminal=True):
            return
        trace = state['trace']
        trace.set_thread(frame.get('threadId'), 'completed')
        completed = state['frames'].pop()
        output = completed['context']['last']
        completed['context']['tasks'].setdefault(task.id, {'activities': {}})['output'] = output
        project = state['project']
        if not state['frames']:
            state.update(output=output, status='completed')
            state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug job completed: {project.name} / {task.name}'})
            return
        parent = state['frames'][-1]
        parent['context']['last'] = output
        parent_task = next(item for item in project.tasks if item.id == parent['taskId'])
        call = next(item for item in parent_task.activities if item.id == parent['activityId'])
        trace.set_thread(parent.get('threadId'), 'active')
        trace.event(parent, 'return', activityId=call.id, targetThreadId=completed.get('threadId'), outcome='completed')
        duration = round(completed['callSetupMs'], 3)
        trace.activity(parent, call, 'completed', duration)
        state['logs'].append({
            'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity',
            'message': f'Activity completed: {parent_task.name} / {call.name} (call setup {duration:.3f} ms)',
            'activityId': call.id, 'activityName': call.name, 'activityType': call.type,
            'taskId': parent_task.id, 'durationMs': duration, 'timingScope': 'call_setup',
        })
        parent['context']['_activityMetadata'] = {'calledTaskId': task.id}
        self.runtime.record_activity_output(call, output, parent['context'], completed['callInput'])
        await self._follow_success(state, parent, parent_task, call)

    def current_activity(self, state):
        if not state['frames']: return None
        frame = state['frames'][-1]; task = next(item for item in state['project'].tasks if item.id == frame['taskId'])
        return next((item for item in task.activities if item.id == frame['activityId']), None)

    def view(self, state):
        if isinstance(state.get('logs'),_DebugLogs):state['logEntriesDropped']=state['logs'].dropped
        excess=max(0,len(state.get('logs',[]))-self.log_limit)
        if excess:
            del state['logs'][:excess]
            state['logEntriesDropped']=state.get('logEntriesDropped',0)+excess
        self._prune_history(state.get('id'))
        current = self.current_activity(state)
        execution_state = state.get('executionState', {})
        group_stack = state['frames'][-1]['context'].get('groupStack', []) if state.get('frames') else []
        active_ids = []
        for frame in state.get('frames', []):
            if frame.get('activityId'): active_ids.append(frame['activityId'])
            active_ids.extend(frame.get('parallelQueue') or [])
            for block in frame.get('parallelStack') or []:
                pending = list(block['pending'])
                while pending:
                    part = pending.pop()
                    if 'edge' in part: active_ids.append(part['edge'].target)
                    else: pending.extend(part['branches'])
        frame = state['frames'][-1] if state.get('frames') else None
        ctx = frame.get('context', {}) if frame else {}
        watch_values = []
        # Keep testing results separate from the actual workflow outputs.
        for expression in state.get('watches', []):
            try: watch_values.append({'expression': expression, 'value': self._evaluate(expression, ctx)})
            except Exception as exc: watch_values.append({'expression': expression, 'error': str(exc)})
        return {'metrics': state['trace'].summary(), 'recentTransitions': list(dict.fromkeys(state['trace'].recent_edges)),
                'activeThreadId': frame.get('threadId') if frame and state['status'] in ('paused', 'running') else None,
                'entryTaskId': state['entryTaskId'], 'listenerMode': state['listenerMode'], 'breakOnNextEvent': state.get('breakOnNextEvent', False),
                'pauseRequested': state.get('pauseRequested', False),
                'lastActivityTest': state.get('lastActivityTest'), 'testHistory': state.get('testHistory', []), 'sessionId': state['id'], 'status': state['status'], 'pauseReason': state.get('pauseReason'), 'currentActivityId': current.id if current else None, 'currentActivityIds': list(dict.fromkeys(active_ids)), 'currentTaskId': state['frames'][-1]['taskId'] if state['frames'] else None, 'currentGroupIds': [item['id'] for item in group_stack], 'groupIterations': {item['id']: item.get('iteration', 0) for item in group_stack}, 'callStack': [{'taskId': frame['taskId'], 'activityId': frame['activityId'], 'groupIds': [item['id'] for item in frame['context'].get('groupStack', [])]} for frame in state['frames']], 'logs': state['logs'], 'logEntriesDropped':state.get('logEntriesDropped',0), 'output': state.get('output', {}), 'activityOutputs': execution_state.get('activities', {}), 'taskOutputs': execution_state.get('tasks', {}), 'endpoints': state.get('endpoints', []), 'breakpoints': sorted(state.get('breakpoints', set())), 'breakpointConditions': state.get('breakpointConditions', {}), 'pauseOnError': state.get('pauseOnError', True), 'watches': state.get('watches', []), 'watchValues': watch_values, 'variables': {'input': ctx.get('input', {}), 'last': ctx.get('last', {}), 'vars': ctx.get('vars', {}), 'context': ctx.get('context', {})}, 'lastException': state.get('lastException'), 'lastEvaluation': state.get('lastEvaluation')}
