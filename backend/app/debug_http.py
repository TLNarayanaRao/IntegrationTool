"""Bridge live HTTP requests into a single interactive debug session."""
from __future__ import annotations
import asyncio
from .http_transport import HTTPFault
from .http_policy import trace_context

def finish_request(state,error=None):
    pending=state.get('httpPending')
    if pending is not None and not pending.done():
        if error:pending.set_exception(RuntimeError(error))
        else:pending.set_result(state.get('output'))

class HTTPDebugBridge:
    def __init__(self,debugger,state):
        self.debugger=debugger;self.state=state;self.busy=False

    async def __call__(self,metadata,payload):
        state=self.state
        if self.busy:raise HTTPFault('A request is already being debugged. Continue or stop that request first.','HTTP_DEBUG_BUSY',503)
        if state.get('stopRequested') or state.get('status')!='listening':raise HTTPFault('HTTP debugger is not listening','HTTP_DEBUG_UNAVAILABLE',503)
        self.busy=True;pending=asyncio.get_running_loop().create_future();state['httpPending']=pending
        state['_httpTraceContext'] = trace_context.get()
        task_id,activity_id=metadata
        state.update(listenerTaskId=task_id,listenerActivityId=activity_id)
        task=next(item for item in state['project'].tasks if item.id==task_id)
        state['groupPlans'].setdefault(task_id,self.debugger.runtime.compile_groups(task))
        self.debugger.rearm_listener(state,complete_request=False)
        try:
            await self.debugger.trigger_event(state['id'],payload)
            return await pending
        except asyncio.CancelledError:
            # A disconnected/timed-out HTTP request cannot leave a stale paused job.
            pending.cancel()
            await self.debugger.stop(state['id'])
            raise
        except Exception:
            pending.cancel()
            state['status']='failed'
            raise
        finally:
            state.pop('httpPending',None)
            state.pop('_httpTraceContext',None)
            if not pending.done():pending.cancel()
            elif not pending.cancelled():pending.exception()  # Observe an error if trigger_event raised first.
            self.busy=False
