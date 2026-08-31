import unittest

from app.models import Activity, Project, SharedResource
from app.runtime import WorkflowRuntime


class MapperCodeGeneralTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_mapping_custom_function_python_and_general_activities(self):
        runtime = WorkflowRuntime()
        project = Project(
            id="extensions",
            name="Extensions",
            custom_functions=[{
                "id": "fn-normalize",
                "name": "normalize",
                "parameters": ["value"],
                "expression": "upperCase(trim($value))",
            }],
        )
        context = {
            "input": {"records": [{"group": "a", "id": 1}, {"group": "a", "id": 2}]},
            "last": {}, "vars": {}, "properties": {}, "resources": {}, "activities": {}, "tasks": {},
            "context": {"taskId": "main", "activityId": "test"}, "logs": [], "project": project,
        }
        mapped = runtime.map_input_values({
            "name": "custom:normalize('  customer  ')",
            "groups": {"$rule": "for-each-group", "source": "${input.records}", "groupBy": "group"},
            "optional": {"$rule": "if", "source": "value", "condition": "false"},
        }, context)
        self.assertEqual(mapped["name"], "CUSTOMER")
        self.assertEqual(mapped["groups"][0]["key"], "a")
        self.assertNotIn("optional", mapped)

        python = Activity(id="python", type="python", name="Python", config={
            "function": "double", "sourceCode": "def double(value):\n    return value * 2", "parameters": [21]
        })
        self.assertEqual((await runtime.execute(python, context))["result"], 42)

        assign = Activity(id="assign", type="basic", name="Assign", config={"operation": "assign", "variable": "answer", "value": 42})
        await runtime.execute(assign, context)
        self.assertEqual(context["vars"]["answer"], 42)
        set_shared = Activity(id="set", type="basic", name="Set", config={"operation": "set_shared_variable", "name": "counter", "value": 7})
        get_shared = Activity(id="get", type="basic", name="Get", config={"operation": "get_shared_variable", "name": "counter"})
        await runtime.execute(set_shared, context)
        self.assertEqual((await runtime.execute(get_shared, context))["value"], 7)
        checkpoint = Activity(id="checkpoint", type="basic", name="Persist state", config={"operation": "checkpoint", "checkpointName": "before-send", "includeProcessState": True})
        created = await runtime.execute(checkpoint, context)
        self.assertEqual(created["name"], "before-send")
        self.assertEqual(context["checkpoints"][0]["state"]["vars"]["answer"], 42)

    async def test_jms_send_receive_headers_properties_and_client_acknowledgement(self):
        runtime = WorkflowRuntime()
        resource = SharedResource(id="jms", type="jms", name="Local JMS", config={"mode": "memory"})
        context = {"input": {}, "last": {"order": 7}, "vars": {}, "properties": {}, "resources": {"jms": resource}, "activities": {}, "tasks": {}, "context": {}, "logs": []}
        sent = await runtime.execute(Activity(id="send", type="jms", name="Send", config={"operation": "send_message", "resourceId": "jms", "destination": "orders", "message": "${last}", "correlationId": "corr-7", "replyTo": "order.replies", "type": "Order", "priority": 8, "dynamicProperties": {"tenant": "west"}}), context)
        self.assertTrue(sent["published"])
        received = await runtime.execute(Activity(id="get", type="jms", name="Get", config={"operation": "get_queue_message", "resourceId": "jms", "queue": "orders", "acknowledgeMode": "Client"}), context)
        self.assertEqual(received["body"], {"order": 7})
        self.assertEqual(received["headers"]["JMSCorrelationID"], "corr-7")
        self.assertEqual(received["headers"]["JMSReplyTo"], "order.replies")
        self.assertEqual(received["headers"]["JMSPriority"], 8)
        self.assertEqual(received["properties"], {"tenant": "west"})
        context["last"] = received
        confirmed = await runtime.execute(Activity(id="confirm", type="confirm", name="Confirm", config={"ackId": received["ackId"]}), context)
        self.assertTrue(confirmed["confirmed"])


if __name__ == "__main__":
    unittest.main()
