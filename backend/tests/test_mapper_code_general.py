import unittest

from app.models import Activity, Project
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


if __name__ == "__main__":
    unittest.main()
