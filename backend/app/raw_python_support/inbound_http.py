"""Native ASGI host using the same transport and security as Studio/Engine."""
from .config import environment
from .core import Context, resolve
from .registry import EVENT_STARTERS, TASKS
from .native.http_server import serve

async def serve_http(task_ids,environment_name):
    properties,resources=environment(environment_name);context=Context({},properties,resources,environment_name=environment_name);routes=[]
    for task_id in task_ids:
        activity_id,kind,config,name=EVENT_STARTERS[task_id];resource=resources.get(str(config.get('resourceId') or ''))
        connection=resolve(resource.config,context) if resource else {}
        routes.append(((task_id,activity_id),connection,resolve(config,context)))
    async def handle(metadata,payload):
        task_id,activity_id=metadata
        return await TASKS[task_id](Context(payload,properties,resources,environment_name=environment_name),start_after=activity_id,event_output=payload)
    await serve(routes,handle)
