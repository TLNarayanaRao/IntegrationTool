import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from app.jdbc import (
    JdbcAdapterError, _connection_url, _databricks_settings, _db2_connection_string,
    _java_driver_class, _java_jdbc_url, _normalize_sql, _parameters, _sqlserver_connection_string, _uses_java, execute as jdbc_execute,
    metadata as jdbc_metadata,
)
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

    def test_jdbc_prepared_parameter_metadata_coerces_runtime_input_types(self):
        values = _parameters({
            "preparedParameters": [
                {"name": "orderId", "type": "integer"},
                {"name": "active", "type": "boolean"},
                {"name": "amount", "type": "number"},
            ],
            "parameters": {"orderId": "42", "active": "true", "amount": "19.75"},
        })
        self.assertEqual(values, {"orderId": 42, "active": True, "amount": 19.75})
        sql, parameters = _normalize_sql("SELECT value::text FROM orders WHERE id=:orderId", values, "sqlserver")
        self.assertEqual(sql, "SELECT value::text FROM orders WHERE id=?")
        self.assertEqual(parameters, [42])

    def test_sqlserver_builds_odbc_string_from_jdbc_fields_and_uses_qmark_parameters(self):
        drivers = ["PostgreSQL Unicode(x64)", "ODBC Driver 18 for SQL Server"]
        connection_string = _sqlserver_connection_string({
            "url": "jdbc:sqlserver://db.example.test:1433;databaseName=orders;encrypt=true;trustServerCertificate=true",
            "username": "fabric",
            "password": "p;ass}word",
        }, drivers)
        self.assertIn("DRIVER={ODBC Driver 18 for SQL Server}", connection_string)
        self.assertIn("SERVER={db.example.test,1433}", connection_string)
        self.assertIn("DATABASE={orders}", connection_string)
        self.assertIn("PWD={p;ass}}word}", connection_string)
        self.assertIn("Encrypt=yes", connection_string)
        self.assertIn("TrustServerCertificate=yes", connection_string)
        sql, parameters = _normalize_sql("SELECT * FROM orders WHERE id=:id AND status=:status", {"id": 7, "status": "NEW"}, "sqlserver")
        self.assertEqual(sql, "SELECT * FROM orders WHERE id=? AND status=?")
        self.assertEqual(parameters, [7, "NEW"])

    def test_sqlserver_and_oracle_default_to_pure_jdbc_without_native_clients(self):
        sqlserver = {"driver":"sqlserver", "host":"db01", "port":1433, "database":"orders", "encrypt":True, "trustServerCertificate":False}
        self.assertTrue(_uses_java(sqlserver))
        self.assertEqual(_java_driver_class(sqlserver), "com.microsoft.sqlserver.jdbc.SQLServerDriver")
        self.assertEqual(_java_jdbc_url(sqlserver), "jdbc:sqlserver://db01:1433;databaseName=orders;encrypt=true;trustServerCertificate=false")
        oracle = {"driver":"oracle", "host":"ora01", "port":1521, "serviceName":"ORCLPDB1"}
        self.assertTrue(_uses_java(oracle))
        self.assertEqual(_java_driver_class(oracle), "oracle.jdbc.OracleDriver")
        self.assertEqual(_java_jdbc_url(oracle), "jdbc:oracle:thin:@//ora01:1521/ORCLPDB1")

    def test_sqlserver_adds_driver_to_odbc_attributes_and_reports_missing_driver(self):
        value = _sqlserver_connection_string({"url": "Server=db01;Database=orders;Trusted_Connection=yes"}, ["ODBC Driver 17 for SQL Server"])
        self.assertTrue(value.startswith("DRIVER={ODBC Driver 17 for SQL Server};Server=db01"))
        with self.assertRaisesRegex(JdbcAdapterError, "Install Microsoft ODBC Driver 18"):
            _sqlserver_connection_string({"host": "db01"}, ["PostgreSQL Unicode(x64)"])

    def test_database_jdbc_urls_are_normalized_for_native_drivers(self):
        self.assertEqual(_connection_url({"url": "jdbc:postgresql://db01:5432/orders"}, "jdbc:"), "postgresql://db01:5432/orders")
        db2 = _db2_connection_string({"url": "jdbc:db2://db02:50001/inventory", "username": "fabric", "password": "secret"})
        self.assertIn("DATABASE=inventory", db2)
        self.assertIn("HOSTNAME=db02", db2)
        self.assertIn("PORT=50001", db2)
        sql, values = _normalize_sql("SELECT * FROM item WHERE id=:id", {"id": 9}, "db2")
        self.assertEqual((sql, values), ("SELECT * FROM item WHERE id=?", [9]))
        oracle_sql, oracle_values = _normalize_sql("SELECT * FROM item WHERE id=:id", {"id": 9}, "oracle")
        self.assertEqual((oracle_sql, oracle_values), ("SELECT * FROM item WHERE id=:id", {"id": 9}))

    def test_databricks_jdbc_url_and_pat_settings(self):
        settings = _databricks_settings({
            "url": "jdbc:databricks://dbc-example.cloud.databricks.com:443/default;httpPath=/sql/1.0/warehouses/abc;AuthMech=3;Auth_AccessToken=token-value",
            "catalog": "main", "schema": "sales", "authentication": "Personal Access Token",
        })
        self.assertEqual(settings["server_hostname"], "dbc-example.cloud.databricks.com")
        self.assertEqual(settings["http_path"], "/sql/1.0/warehouses/abc")
        self.assertEqual(settings["access_token"], "token-value")
        self.assertEqual(settings["catalog"], "main")
        sql, values = _normalize_sql("SELECT * FROM orders WHERE state=:state", {"state": "OPEN"}, "databricks")
        self.assertEqual((sql, values), ("SELECT * FROM orders WHERE state=?", ["OPEN"]))

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
