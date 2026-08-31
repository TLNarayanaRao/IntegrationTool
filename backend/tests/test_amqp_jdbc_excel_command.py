import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from app.jdbc import execute as jdbc_execute, metadata as jdbc_metadata
from app.models import Activity, SharedResource
from app.runtime import WorkflowRuntime


class AmqpJdbcExcelCommandTests(unittest.TestCase):
    def context(self, resources=None, payload=None):
        value = payload or {}
        return {"input": value, "last": value, "vars": {}, "resources": resources or {}, "properties": {}, "logs": [], "context": {}, "activities": {}, "tasks": {}}

    def test_jdbc_query_update_dynamic_parameters_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            database = str(Path(folder) / "orders.db")
            connection = {"driver": "sqlite", "url": database}
            jdbc_execute(connection, {"operation": "dynamic", "sql": "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT, status TEXT)"})
            inserted = jdbc_execute(connection, {"operation": "insert", "sql": "INSERT INTO orders(customer,status) VALUES (:customer,:status)", "parameters": {"customer": "Ada", "status": "NEW"}})
            self.assertEqual(inserted["noOfUpdates"], 1)
            queried = jdbc_execute(connection, {"operation": "query", "sql": "SELECT id,customer,status FROM orders WHERE status=:status", "parameters": {"status": "NEW"}, "maxRows": 10})
            self.assertEqual(queried["resultSet"]["Record"][0]["customer"], "Ada")
            self.assertEqual([item["name"] for item in queried["columns"]], ["id", "customer", "status"])
            catalog = jdbc_metadata(connection)
            self.assertEqual(catalog["tables"][0]["name"], "orders")
            self.assertEqual(catalog["tables"][0]["columns"][0]["name"], "id")

    def test_amqp_memory_send_receive_confirm_and_dead_letter(self):
        runtime = WorkflowRuntime()
        resource = SharedResource(id="amqp", type="amqp", name="AMQP", config={"mode": "memory", "brokerType": "RabbitMQ"})
        resources = {resource.id: resource}
        send = Activity(id="send", type="amqp", name="Send", config={"operation": "send", "resourceId": "amqp", "queueName": "orders", "body": "hello"})
        received = Activity(id="get", type="amqp", name="Get", config={"operation": "get", "resourceId": "amqp", "queueName": "orders", "acknowledgeMode": "Client"})
        asyncio.run(runtime.execute(send, self.context(resources)))
        message = asyncio.run(runtime.execute(received, self.context(resources)))
        self.assertEqual(message["body"], "hello")
        self.assertTrue(message["settlementToken"].startswith("amqp:"))
        self.assertTrue(asyncio.run(runtime.confirm_messages(message["settlementToken"]))["confirmed"])
        asyncio.run(runtime.execute(send, self.context(resources)))
        message = asyncio.run(runtime.execute(received, self.context(resources)))
        dead = Activity(id="dead", type="amqp", name="Dead", config={"operation": "dead_letter", "resourceId": "amqp", "settlementToken": message["settlementToken"], "deadLetterReason": "invalid"})
        result = asyncio.run(runtime.execute(dead, self.context(resources)))
        self.assertEqual(result["status"], "Success")
        self.assertEqual(len(runtime.messages["amqp:orders:$deadletter"]), 1)

    def test_external_command_captures_and_splits_output(self):
        runtime = WorkflowRuntime()
        command = f'{sys.executable} -c "print(123);print(456)"'
        activity = Activity(id="command", type="basic", name="Command", config={"operation": "external_command", "command": command, "provideCommandOutput": True, "outputLineSplitting": "AtOperatingSystemLineEnd"})
        result = asyncio.run(runtime.execute(activity, self.context()))
        self.assertEqual(result["returnCode"], 0)
        self.assertEqual(result["output"], ["123", "456"])

    @unittest.skipUnless(__import__("importlib").util.find_spec("openpyxl"), "openpyxl is installed by backend requirements")
    def test_excel_reads_all_tabs_and_builds_nested_json(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "orders.xlsx"; workbook = Workbook(); first = workbook.active; first.title = "Orders"
            first.append(["id", "customer.name", "customer.city"]); first.append([1, "Ada", "London"])
            second = workbook.create_sheet("Summary"); second.append(["count"]); second.append([1]); workbook.save(path); workbook.close()
            result = WorkflowRuntime.read_excel({"filePath": str(path), "headerRow": 1, "startRow": 2, "nestedHeaders": True})
            self.assertEqual(result["workbook"]["sheetCount"], 2)
            self.assertEqual(result["workbook"]["sheets"][0]["rows"][0]["customer"]["name"], "Ada")


if __name__ == "__main__":
    unittest.main()
