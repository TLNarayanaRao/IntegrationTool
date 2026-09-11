import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import Activity, GroupDefinition, ProcessDefinition, SharedResource, Transition
from app.runtime import WorkflowRuntime
from app.jdbc import JavaJdbcTransaction, execute as jdbc_execute


def activity(identifier, kind="basic", operation="empty", **config):
    return Activity(id=identifier, type=kind, name=identifier.title(), config={"operation": operation, **config})


class GroupRuntimeTests(unittest.TestCase):
    def test_java_jdbc_transaction_reuses_worker_then_commits_once(self):
        class Worker:
            def __init__(self): self.requests = []; self.closed = False
            def request(self, action, values=None, timeout=35):
                self.requests.append((action, values)); return {"ok": True, "rowCount": 1}
            def close(self): self.closed = True
        worker = Worker()
        connection_config = {"driver": "sqlserver", "connectionMode": "jdbc", "url": "jdbc:sqlserver://db:1433;databaseName=test", "driverClass": "com.microsoft.sqlserver.jdbc.SQLServerDriver"}
        with patch("app.jdbc.start_jdbc_worker", return_value=worker):
            transaction = JavaJdbcTransaction(connection_config)
            first = jdbc_execute(connection_config, {"operation": "update", "sql": "update sample set value=?", "parameters": [1]}, transaction, False)
            second = jdbc_execute(connection_config, {"operation": "query", "sql": "select value from sample"}, transaction, False)
            transaction.commit(); transaction.close()
        self.assertEqual(first["rowCount"], 1); self.assertEqual(second["rowCount"], 1)
        self.assertEqual([item[0] for item in worker.requests], ["execute", "execute", "commit"])
        self.assertTrue(worker.closed)

    def test_java_jdbc_transaction_close_rolls_back_uncommitted_worker(self):
        class Worker:
            def __init__(self): self.requests = []; self.closed = False
            def request(self, action, values=None, timeout=35): self.requests.append(action); return {"ok": True}
            def close(self): self.closed = True
        worker = Worker(); config = {"driver": "oracle", "connectionMode": "jdbc", "url": "jdbc:oracle:thin:@//db:1521/ORCL", "driverClass": "oracle.jdbc.OracleDriver"}
        with patch("app.jdbc.start_jdbc_worker", return_value=worker):
            transaction = JavaJdbcTransaction(config); transaction.close()
        self.assertEqual(worker.requests, ["rollback"]); self.assertTrue(worker.closed)

    def test_repeat_and_iterate_groups_are_scheduled_by_the_runtime(self):
        process = ProcessDefinition(
            id="loops", name="Loops",
            activities=[activity("start", "start"), activity("work", "log", message="iteration"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="work"), Transition(id="b", source="work", target="end")],
            groups=[GroupDefinition(id="repeat", type="repeat", name="Repeat", member_activity_ids=["work"], config={"condition": "${vars.index} >= 3", "maxIterations": 10})],
        )
        result = asyncio.run(WorkflowRuntime().run(process, {}))
        self.assertEqual(result.status, "completed")
        self.assertEqual(sum(1 for item in result.logs if item.get("message", "").startswith("Activity started: Loops / Work")), 3)
        self.assertEqual(sum(1 for item in result.logs if item.get("kind") == "group" and "iteration" in item.get("message", "").lower()), 2)

    def test_if_group_can_skip_its_body(self):
        process = ProcessDefinition(
            id="condition", name="Condition",
            activities=[activity("start", "start"), activity("work", "log", message="must not run"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="work"), Transition(id="b", source="work", target="end")],
            groups=[GroupDefinition(id="if", type="if", name="Conditional", member_activity_ids=["work"], config={"condition": "${input.enabled} == true"})],
        )
        result = asyncio.run(WorkflowRuntime().run(process, {"enabled": False}))
        self.assertEqual(result.status, "completed")
        self.assertNotIn("work", result.activity_outputs)

    def test_jdbc_transaction_rolls_back_when_group_fault_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.sqlite"
            import sqlite3
            connection = sqlite3.connect(path); connection.execute("create table events (value text)"); connection.commit(); connection.close()
            resource = SharedResource(id="db", type="jdbc", name="DB", config={"driver": "sqlite", "url": str(path)})
            process = ProcessDefinition(
                id="transaction", name="Transaction",
                activities=[activity("start", "start"), activity("insert", "jdbc", operation="insert", resourceId="db", sql="insert into events(value) values (?)", parameters=["x"]), activity("fail", "throw", message="rollback"), activity("end", "end")],
                transitions=[Transition(id="a", source="start", target="insert"), Transition(id="b", source="insert", target="fail"), Transition(id="c", source="fail", target="end")],
                groups=[GroupDefinition(id="tx", type="transaction_jdbc", name="Transaction", member_activity_ids=["insert", "fail"], config={"resourceId": "db"})],
            )
            result = asyncio.run(WorkflowRuntime().run(process, {}, {"db": resource}))
            self.assertEqual(result.status, "failed")
            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("select count(*) from events").fetchone()[0], 0)
            connection.close()

    def test_invalid_group_boundary_and_pick_first_fail_explicitly(self):
        process = ProcessDefinition(
            id="invalid", name="Invalid",
            activities=[activity("start", "start"), activity("one"), activity("two"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="one"), Transition(id="b", source="start", target="two"), Transition(id="c", source="one", target="end"), Transition(id="d", source="two", target="end")],
            groups=[GroupDefinition(id="pick", type="pick_first", name="Pick", member_activity_ids=["one", "two"])],
        )
        result = asyncio.run(WorkflowRuntime().run(process, {}))
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("not runtime-qualified" in item.get("message", "") for item in result.logs))


if __name__ == "__main__":
    unittest.main()
