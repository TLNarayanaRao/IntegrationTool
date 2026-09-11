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
    def test_iterate_collection_from_task_data_runs_once_per_member(self):
        class CurrentElementRuntime(WorkflowRuntime):
            def __init__(self): super().__init__(); self.elements = []; self.accumulated = None
            async def execute(self, current, ctx):
                if current.id == "work":
                    self.elements.append(ctx["vars"]["currentElement"])
                    return {"processedId": ctx["vars"]["currentElement"]["id"]}
                if current.id == "after":
                    self.accumulated = ctx["vars"].get("processed")
                    return {"count": len(self.accumulated or [])}
                return await super().execute(current, ctx)
        process = ProcessDefinition(
            id="iterate-data", name="Iterate Data",
            activities=[activity("start", "start"), activity("work"), activity("after"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="work"), Transition(id="b", source="work", target="after"), Transition(id="c", source="after", target="end")],
            groups=[GroupDefinition(id="items", type="iterate", name="Items", member_activity_ids=["work"], config={"source": "${input.orders}", "currentElementName": "order", "indexVariable": "index", "accumulateOutput": True, "accumulatorVariable": "processed"})],
        )
        runtime = CurrentElementRuntime()
        result = asyncio.run(runtime.run(process, {"orders": [{"id": 1}, {"id": 2}, {"id": 3}]}))
        self.assertEqual(result.status, "completed")
        self.assertEqual([item["id"] for item in runtime.elements], [1, 2, 3])
        self.assertEqual(runtime.accumulated, [{"processedId": 1}, {"processedId": 2}, {"processedId": 3}])

    def test_repeat_on_error_resolves_retry_limit_from_environment_properties(self):
        class FailingRuntime(WorkflowRuntime):
            def __init__(self): super().__init__(); self.attempts = 0
            async def execute(self, current, ctx):
                if current.id == "fail": self.attempts += 1; raise RuntimeError("still unavailable")
                return await super().execute(current, ctx)
        process = ProcessDefinition(
            id="retry-properties", name="Retry Properties",
            activities=[activity("start", "start"), activity("fail"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="fail"), Transition(id="b", source="fail", target="end")],
            groups=[GroupDefinition(id="retry", type="repeat_on_error", name="Retry", member_activity_ids=["fail"], config={"stopCondition": "${vars.index} >= 10", "retryCount": "${properties.advanced.retryCount}", "retryIntervalSeconds": "${properties.advanced.retryIntervalSeconds}"})],
        )
        runtime = FailingRuntime()
        result = asyncio.run(runtime.run(process, {}, properties={"advanced.retryCount": 1, "advanced.retryIntervalSeconds": 0}))
        self.assertEqual(result.status, "failed")
        self.assertEqual(runtime.attempts, 2)

    def test_repeat_on_error_retries_complete_group_and_exposes_fault_data(self):
        class FlakyRuntime(WorkflowRuntime):
            def __init__(self): super().__init__(); self.attempts = 0; self.observed_errors = []
            async def execute(self, current, ctx):
                if current.id == "flaky":
                    self.attempts += 1
                    if self.attempts > 1: self.observed_errors.append(ctx["vars"].get("error"))
                    if self.attempts < 3: raise RuntimeError(f"temporary-{self.attempts}")
                    return {"recovered": True}
                return await super().execute(current, ctx)
        process = ProcessDefinition(
            id="retry-data", name="Retry Data",
            activities=[activity("start", "start"), activity("flaky"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="flaky"), Transition(id="b", source="flaky", target="end")],
            groups=[GroupDefinition(id="retry", type="repeat_on_error", name="Retry", member_activity_ids=["flaky"], config={"stopCondition": "${vars.index} >= 5", "retryCount": 5, "indexVariable": "index"})],
        )
        runtime = FlakyRuntime()
        result = asyncio.run(runtime.run(process, {}))
        self.assertEqual(result.status, "completed")
        self.assertEqual(runtime.attempts, 3)
        self.assertEqual(runtime.observed_errors[0]["message"], "temporary-1")

    def test_critical_section_serializes_concurrent_jobs_until_group_exit(self):
        class ObservedRuntime(WorkflowRuntime):
            def __init__(self): super().__init__(); self.active = 0; self.maximum_active = 0
            async def execute(self, current, ctx):
                if current.id == "work":
                    self.active += 1; self.maximum_active = max(self.maximum_active, self.active)
                    await asyncio.sleep(0.025)
                    self.active -= 1
                    return {"complete": True}
                return await super().execute(current, ctx)
        process = ProcessDefinition(
            id="critical", name="Critical",
            activities=[activity("start", "start"), activity("work"), activity("end", "end")],
            transitions=[Transition(id="a", source="start", target="work"), Transition(id="b", source="work", target="end")],
            groups=[GroupDefinition(id="lock", type="critical_section", name="Locked", member_activity_ids=["work"], config={"lockName": "shared-test-lock"})],
        )
        runtime = ObservedRuntime()
        async def run_both(): return await asyncio.gather(runtime.run(process, {"job": 1}), runtime.run(process, {"job": 2}))
        results = asyncio.run(run_both())
        self.assertTrue(all(result.status == "completed" for result in results))
        self.assertEqual(runtime.maximum_active, 1)

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
