"""Native ASGI host using the same transport and security as Studio/Engine."""
import os

from .config import environment
from .core import Context, resolve
from .registry import EVENT_STARTERS, TASKS
from .native.http_server import serve

async def serve_http(task_ids,environment_name):
    properties,resources=environment(environment_name);context=Context({},properties,resources,environment_name=environment_name);routes=[]
    for task_id in task_ids:
        activity_id, _, template, _ = EVENT_STARTERS[task_id]
        config = resolve(template, context)
        resource = resources.get(str(config.get('resourceId') or ''))
        connection=resolve(resource.config,context) if resource else {}
        if os.environ.get('MINA_HTTP_HOST'):
            connection['host'] = os.environ['MINA_HTTP_HOST']
        if os.environ.get('MINA_HTTP_PORT'):
            connection['port'] = int(os.environ['MINA_HTTP_PORT'])
        routes.append(((task_id,activity_id),connection,config))
    async def handle(metadata,payload):
        task_id,activity_id=metadata
        return await TASKS[task_id](Context(payload,properties,resources,environment_name=environment_name),start_after=activity_id,event_output=payload)
    await serve(routes,handle)
