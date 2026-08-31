import asyncio
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.models import Activity, SharedResource
from app.runtime import WorkflowRuntime
from app.snowflake import SnowflakeAdapterError, entity_metadata, execute, list_entities


class SnowflakeConnectorTests(unittest.TestCase):
    def setUp(self):
        self.resource = SharedResource(
            id="snowflake-main", type="snowflake", name="Snowflake JDBC",
            config={
                "mode": "mock", "account": "demo.us-west-2.aws", "warehouse": "COMPUTE_WH",
                "database": "SALES", "schema": "PUBLIC",
                "mockEntities": [{
                    "database": "SALES", "schema": "PUBLIC", "name": "ORDERS", "entityType": "BASE TABLE",
                    "columns": [
                        {"name": "ORDER_ID", "dataType": "NUMBER", "xsdType": "integer", "notNull": True, "primaryKey": True},
                        {"name": "CUSTOMER", "dataType": "VARCHAR", "xsdType": "string", "notNull": False, "primaryKey": False},
                    ],
                }],
            },
        )

    def runtime(self, operation, config, payload):
        activity = Activity(id="sf", type="snowflake", name=f"Snowflake {operation}", config={"operation": operation, "resourceId": self.resource.id, **config})
        context = {"input": payload, "last": payload, "vars": {}, "resources": {self.resource.id: self.resource}, "properties": {}, "logs": [], "context": {}}
        return asyncio.run(WorkflowRuntime().execute(activity, context))

    def test_mock_insert_query_update_delete_and_bulk_load_contracts(self):
        inserted = self.runtime("insert", {"batchSize": 100}, [{"ORDER_ID": 1}, {"ORDER_ID": 2}])
        self.assertEqual(inserted, {"rowsAttempted": 2, "rowsAffected": 2, "batchFailures": []})
        queried = self.runtime("query", {"maximumRows": 1, "mockRows": [{"ORDER_ID": 1}, {"ORDER_ID": 2}]}, {})
        self.assertEqual(queried, {"rows": [{"ORDER_ID": 1}], "rowCount": 1})
        self.assertEqual(self.runtime("update", {"mockRowsAffected": 3}, {"ORDER_ID": 1})["rowsAffected"], 3)
        self.assertEqual(self.runtime("delete", {"mockRowsAffected": 1}, {"ORDER_ID": 1})["rowsAffected"], 1)
        bulk = self.runtime("bulk_load", {"filePath": "orders.csv"}, [{"ORDER_ID": 1}])
        self.assertEqual(bulk["loadResults"][0]["STATUS"], "LOADED")
        self.assertEqual(bulk["loadResults"][0]["ROWS_LOADED"], 1)

    def test_metadata_retrieval_stores_table_view_columns_and_xsd_types(self):
        entities = list_entities(self.resource.config, pattern="ORDER")
        self.assertEqual(entities[0]["name"], "ORDERS")
        metadata = entity_metadata(self.resource.config, "SALES", "PUBLIC", "ORDERS")
        self.assertEqual(metadata["columns"][0]["xsdType"], "integer")
        self.assertTrue(metadata["columns"][0]["primaryKey"])
        with self.assertRaises(SnowflakeAdapterError):
            entity_metadata(self.resource.config, "SALES", "PUBLIC", "MISSING")

    def test_connection_and_entity_endpoints_support_design_time_mock(self):
        client = TestClient(app)
        connection = client.post("/api/connections/test", json=self.resource.model_dump())
        self.assertEqual(connection.status_code, 200)
        self.assertTrue(connection.json()["ok"])
        discovered = client.post("/api/snowflake/entities", json={"resource": self.resource.model_dump(), "pattern": "ORDER"})
        self.assertEqual(discovered.status_code, 200)
        self.assertEqual(discovered.json()["entities"][0]["entityType"], "BASE TABLE")
        downloaded = client.post("/api/snowflake/entities", json={"resource": self.resource.model_dump(), "database": "SALES", "schema": "PUBLIC", "entity": "ORDERS"})
        self.assertEqual(downloaded.json()["entity"]["columns"][1]["xsdType"], "string")

    def test_insert_merge_requires_documented_batch_size_and_match_columns(self):
        # Mock mode exposes deterministic results; external validation is asserted through the builder contract.
        class Connection:
            def cursor(self): return self
            def close(self): pass
            def commit(self): pass
            def execute(self, *args, **kwargs): self.rowcount = 0; return self
            def executemany(self, *args, **kwargs): self.rowcount = 0; return self

        from unittest.mock import patch
        with patch("app.snowflake.connect", return_value=Connection()):
            with self.assertRaises(SnowflakeAdapterError):
                execute({"database": "SALES", "schema": "PUBLIC"}, {"operation": "insert", "entity": "ORDERS", "merge": True, "batchSize": 100, "mergeOnColumns": "ORDER_ID"}, [{"ORDER_ID": 1}])


if __name__ == "__main__":
    unittest.main()
