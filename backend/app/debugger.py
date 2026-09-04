from __future__ import annotations
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

    def start(self, project: Project, task_id: str, initial: dict, resources: dict, properties: dict, breakpoints: list[str], environment: str = 'local'):
        task = next((item for item in project.tasks if item.id == task_id), None)
        if not task: raise ValueError('Task not found')
        incoming = {edge.target for edge in task.transitions}
        root_activities = [item for item in task.activities if item.id not in incoming]
        starters = [item for item in root_activities if item.type in ('start','timer','http_listener') or (item.type in ('rest','soap','ems','jms','kafka','pubsub') and item.config.get('operation') in ('receiver','service','receive','receive_message','subscribe','queue_receiver','topic_subscriber'))]
        starters = starters or [item for item in task.activities if item.id not in incoming]
        if not starters: raise ValueError('Task has no starting activity')
        session_id = str(uuid4())
        execution_state = {'activities': {}, 'tasks': {task.id: {'name': task.name, 'activities': {}}}}
        logs = [{'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug session started: {project.name} / {task.name}', 'taskId': task.id, 'sessionId': session_id}]
        context = {'input': initial, 'vars': {}, 'last': initial, 'resources': resources, 'properties': properties, 'project': project, 'runtime': self.runtime, 'logs': logs, 'activities': execution_state['activities'], 'tasks': execution_state['tasks'], 'context': {'taskId': task.id, 'activityId': starters[0].id, 'environment': environment}}
        operation = starters[0].config.get('operation')
        continuous_listener = starters[0].type in ('timer', 'file', 'ems', 'jms', 'amqp', 'kafka', 'pubsub', 'sap') and operation in ('schedule', 'poll', 'queue_receiver', 'topic_subscriber', 'receive_message', 'receive', 'get', 'subscribe', 'idoc_listener', 'rfc_bapi_listener')
        self.sessions[session_id] = {
            'id': session_id, 'project': project, 'environment': environment, 'executionState': execution_state,
            'frames': [{'taskId': task.id, 'activityId': starters[0].id, 'context': context}],
            'breakpoints': set(breakpoints), 'logs': logs, 'status': 'listening' if continuous_listener else 'paused',
            'listenerMode': continuous_listener, 'listenerTaskId': task.id, 'listenerActivityId': starters[0].id,
            'initial': initial, 'resources': resources, 'properties': properties,
        }
        if continuous_listener:
            logs.append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'listener', 'message': f'{starters[0].name} is ready and waiting for events', 'activityId': starters[0].id, 'taskId': task.id, 'sessionId': session_id})
        return self.view(self.sessions[session_id])

    def rearm_listener(self, state: dict):
        if not state.get('listenerMode') or state.get('status') == 'stopped': return
        task = next(item for item in state['project'].tasks if item.id == state['listenerTaskId'])
        activity_id = state['listenerActivityId']
        execution_state = state['executionState']
        context = {
            'input': state.get('initial', {}), 'vars': {}, 'last': state.get('initial', {}),
            'resources': state['resources'], 'properties': state['properties'], 'project': state['project'],
            'runtime': self.runtime, 'logs': state['logs'], 'activities': execution_state['activities'],
            'tasks': execution_state['tasks'],
            'context': {'taskId': task.id, 'activityId': activity_id, 'environment': state['environment']},
        }
        state['frames'] = [{'taskId': task.id, 'activityId': activity_id, 'context': context}]
        state['status'] = 'listening'

    async def trigger_event(self, session_id: str, output: dict):
        state = self.sessions.get(session_id)
        if not state or not state.get('listenerMode') or state.get('status') != 'listening': return self.view(state) if state else None
        frame = state['frames'][-1]
        task = next(item for item in state['project'].tasks if item.id == frame['taskId'])
        activity = next(item for item in task.activities if item.id == frame['activityId'])
        ctx = frame['context']; ctx['last'] = output; ctx['context']['activityId'] = activity.id
        now = log_timestamp()
        state['logs'].append({'time': now, 'level': 'INFO', 'kind': 'event', 'message': f'Event received: {task.name} / {activity.name}', 'activityId': activity.id, 'taskId': task.id, 'sessionId': session_id})
        self.runtime.record_activity_output(activity, output, ctx)
        outgoing = [edge for edge in task.transitions if edge.source == activity.id]
        chosen = next((edge for edge in outgoing if edge.type == 'success_condition' and self.runtime.condition(edge.condition, ctx)), None) or next((edge for edge in outgoing if edge.type == 'success'), None) or next((edge for edge in outgoing if edge.type == 'success_no_match'), None)
        if not chosen:
            state['logs'].append({'time': now, 'level': 'ERROR', 'kind': 'event', 'message': f'{activity.name} has no matching outgoing transition', 'activityId': activity.id, 'taskId': task.id})
            self.rearm_listener(state)
            return self.view(state)
        frame['activityId'] = chosen.target
        state['status'] = 'running'
        while state['status'] == 'running':
            current = self.current_activity(state)
            if current and current.id in state['breakpoints']:
                state['status'] = 'paused'
                break
            await self.step(state)
        if state['status'] == 'completed': self.rearm_listener(state)
        return self.view(state)

    async def action(self, session_id: str, action: str):
        state = self.sessions.get(session_id)
        if not state: raise ValueError('Debug session not found')
        if action == 'stop':
            state['status'] = 'stopped'
            state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug session stopped: {state["project"].name}', 'sessionId': session_id})
            return self.view(state)
        if action == 'pause': state['status'] = 'paused'; return self.view(state)
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
                first = True
                while state['status'] == 'running':
                    await self.step(state)
                    current = self.current_activity(state)
                    if not first and current and current.id in state['breakpoints']: state['status'] = 'paused'
                    first = False
            if state['status'] == 'running': state['status'] = 'paused'
            if state.get('listenerMode') and state['status'] == 'completed': self.rearm_listener(state)
        except Exception as exc:
            state['logs'].append({'time': log_timestamp(), 'level': 'ERROR', 'message': str(exc), 'activityId': self.current_activity(state).id if self.current_activity(state) else None})
            state['status'] = 'failed'
        return self.view(state)

    async def step(self, state: dict, enter_subtask=False):
        if not state['frames']: state['status'] = 'completed'; return
        frame = state['frames'][-1]; project = state['project']; task = next(item for item in project.tasks if item.id == frame['taskId'])
        activity = next(item for item in task.activities if item.id == frame['activityId']); ctx = frame['context']
        state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity', 'message': f'Activity started: {task.name} / {activity.name}', 'activityId': activity.id, 'taskId': task.id, 'activityType': activity.type, 'operation': activity.config.get('operation') or activity.type})
        activity_started = perf_counter()
        if enter_subtask and activity.type == 'call_task':
            dynamic_id = self.runtime.resolve(activity.config.get('dynamicTaskId', ''), ctx)
            target_id = str(dynamic_id or activity.config.get('taskId') or '').strip()
            target = next((item for item in project.tasks if (item.id == target_id or item.name.casefold() == target_id.casefold()) and item.kind == 'subtask'), None)
            if target:
                incoming = {edge.target for edge in target.transitions}; starter = next((item for item in target.activities if item.type == 'start'), None) or next(item for item in target.activities if item.id not in incoming)
                values = self.runtime.map_input_values(activity.config.get('inputMappings', {}), ctx)
                mapped = self.runtime.unwrap_boundary(values, 'payload', ctx['last'])
                child_context = {**ctx, 'input': mapped, 'last': mapped, 'context': {'taskId': target.id, 'activityId': starter.id, 'environment': project.active_environment}}
                ctx['tasks'].setdefault(target.id, {'name': target.name, 'activities': {}})
                state['frames'].append({'taskId': target.id, 'activityId': starter.id, 'context': child_context}); state['status'] = 'paused'; return
        ctx['context']['activityId'] = activity.id
        try:
            ctx['last'] = await self.runtime.execute_with_policy(activity, ctx)
        except Exception as exc:
            duration = round((perf_counter() - activity_started) * 1000, 3)
            state['logs'].append({'time': log_timestamp(), 'level': 'ERROR', 'kind': 'activity', 'message': f'Activity failed: {task.name} / {activity.name} in {duration:.3f} ms: {exc}', 'activityId': activity.id, 'taskId': task.id, 'durationMs': duration})
            raise
        duration = round((perf_counter() - activity_started) * 1000, 3)
        state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'activity', 'message': f'Activity completed: {task.name} / {activity.name} in {duration:.3f} ms', 'activityId': activity.id, 'taskId': task.id, 'durationMs': duration})
        self.runtime.record_activity_output(activity, ctx['last'], ctx)
        outgoing = [edge for edge in task.transitions if edge.source == activity.id]
        chosen = next((edge for edge in outgoing if edge.type == 'success_condition' and self.runtime.condition(edge.condition, ctx)), None) or next((edge for edge in outgoing if edge.type == 'success'), None) or next((edge for edge in outgoing if edge.type == 'success_no_match'), None)
        if activity.type == 'end' or not chosen:
            completed = state['frames'].pop()
            completed['context']['tasks'].setdefault(completed['taskId'], {'activities': {}})['output'] = completed['context']['last']
            if not state['frames']:
                state['output'] = completed['context']['last']; state['status'] = 'completed'
                state['logs'].append({'time': log_timestamp(), 'level': 'INFO', 'kind': 'lifecycle', 'message': f'Debug job completed: {project.name} / {task.name}'})
                return
            parent = state['frames'][-1]; parent['context']['last'] = completed['context']['last']
            parent_task = next(item for item in project.tasks if item.id == parent['taskId']); call = next(item for item in parent_task.activities if item.id == parent['activityId'])
            self.runtime.record_activity_output(call, completed['context']['last'], parent['context'])
            edge = next((item for item in parent_task.transitions if item.source == call.id and item.type == 'success'), None)
            if edge: parent['activityId'] = edge.target
            return
        frame['activityId'] = chosen.target

    def current_activity(self, state):
        if not state['frames']: return None
        frame = state['frames'][-1]; task = next(item for item in state['project'].tasks if item.id == frame['taskId'])
        return next((item for item in task.activities if item.id == frame['activityId']), None)

    def view(self, state):
        current = self.current_activity(state)
        execution_state = state.get('executionState', {})
        return {'sessionId': state['id'], 'status': state['status'], 'currentActivityId': current.id if current else None, 'currentTaskId': state['frames'][-1]['taskId'] if state['frames'] else None, 'callStack': [{'taskId': frame['taskId'], 'activityId': frame['activityId']} for frame in state['frames']], 'logs': state['logs'], 'output': state.get('output', {}), 'activityOutputs': execution_state.get('activities', {}), 'taskOutputs': execution_state.get('tasks', {}), 'endpoints': state.get('endpoints', [])}
