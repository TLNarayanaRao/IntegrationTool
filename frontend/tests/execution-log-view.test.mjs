import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = await readFile(new URL("../src/ExecutionLogView.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const moduleScope = { exports: {}, require: () => ({}) };
vm.runInNewContext(compiled, moduleScope);
const { filterExecutionLogs, executionLogReport, summarizeActivityTimings } = moduleScope.exports;

const entries = [
  { level: "WARNING", message: "Slow publish", correlationId: "id-1", taskId: "Outbound", durationMs: 50,
    payload: { password: "fixture" } },
  { level: "error", message: "Connection refused", correlationId: "id-2", threadId: "parallel-1" },
  { level: "WARN", message: "Slow publish", correlationId: "id-10" },
];

test("execution filters combine severity, text and exact correlation IDs", () => {
  assert.equal(filterExecutionLogs(entries, "WARN", "outbound publish", "id-1")[0], entries[0]);
  assert.equal(filterExecutionLogs(entries, "WARN", "slow", "id-1").length, 1);
  assert.equal(filterExecutionLogs(entries, "ERROR", "parallel-1 connection", "").length, 1);
  assert.equal(filterExecutionLogs(entries, "", "fixture", "").length, 0);
});

test("metadata export captures timing and identifiers without payloads or messages", () => {
  const report = executionLogReport(filterExecutionLogs(entries, "WARN", "Outbound", ""));
  assert.deepEqual(JSON.parse(report.trim()), { level: "WARNING", taskId: "Outbound", correlationId: "id-1", durationMs: 50 });
  assert.doesNotMatch(report, /fixture|password|publish/);
});

test("activity timings count finished invocations by task, activity and measurement scope", () => {
  const first = { kind: "activity", taskId: "first", activityId: "Publish", level: "INFO", durationMs: 25 };
  const second = { kind: "activity", taskId: "other", runtimeActivityId: "Publish", level: "ERROR", durationMs: 60 };
  const rows = [
    first, second, { ...first, level: "ERROR", durationMs: 50 },
    { ...first, timingScope: "call_setup", durationMs: 1 },
    { ...first, kind: "lifecycle", durationMs: 1000 },
    { ...first, durationMs: NaN }, { ...first, durationMs: undefined },
  ];
  const timings = summarizeActivityTimings(rows);
  assert.equal(timings.length, 3);
  assert.deepEqual(JSON.parse(JSON.stringify(timings[0])), {
    taskId: "first", activityId: "Publish", activityName: "Publish", taskName: "first", scope: "",
    invocations: 2, failures: 1, totalMs: 75, maxMs: 50,
  });
  assert.equal(timings[1].failures, 1);
  assert.equal(timings[2].totalMs, 1);
  assert.equal(filterExecutionLogs(rows, "", "", "", { taskId: "other", activityId: "Publish" })[0], second);
});

test("live logs follow new rows until the user scrolls away, then can resume", () => {
  const states = [];
  const effects = [];
  const log = { scrollHeight: 500, clientHeight: 100, scrollTop: 0 };
  let stateIndex = 0, previousDependencies;
  const jsx = (type, props) => ({ type, props });
  const hooks = {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = value; }];
    },
    useRef() { return { current: log }; },
    useMemo(compute) { return compute(); },
    useEffect(effect, dependencies) {
      if (!previousDependencies || dependencies.some((value, index) => value !== previousDependencies[index])) effects.push(effect);
      previousDependencies = dependencies;
    },
  };
  const viewScope = { exports: {}, require: name => name === "react" ? hooks : { jsx, jsxs: jsx } };
  vm.runInNewContext(compiled, viewScope);
  let rows = [...entries];
  const render = () => {
    stateIndex = 0;
    const view = viewScope.exports.default({ entries: rows, resolveActivity: () => undefined });
    effects.splice(0).forEach(effect => effect());
    return view.props.children;
  };
  render();
  assert.equal(log.scrollTop, 500);
  log.scrollHeight = 700;
  rows = [...rows, { message: "Next row" }];
  const [, list] = render();
  assert.equal(log.scrollTop, 700);
  log.scrollTop = 50;
  list.props.onScroll({ currentTarget: log });
  rows = [...rows, { message: "Another row" }];
  log.scrollHeight = 900;
  const [controls] = render();
  assert.equal(log.scrollTop, 50);
  const follow = controls.props.children.find(item => item?.props?.children === "Follow latest");
  follow.props.onClick();
  render();
  assert.equal(log.scrollTop, 900);
});
