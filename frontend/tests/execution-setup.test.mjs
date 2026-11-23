import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(compile(source)).toString("base64")}`;
const entry = moduleUrl(await readFile(new URL("../src/taskEntry.ts", import.meta.url), "utf8"));
const source = await readFile(new URL("../src/executionSetup.ts", import.meta.url), "utf8");
const { executionReadiness, launchEntry, parseLaunchInput } = await import(moduleUrl(source.replace('"./taskEntry"', JSON.stringify(entry))));

const activity = (id, type, config = {}) => ({ id, type, name: id, config });
const task = (id, activities, kind = "starter") => ({
  id, name: id, kind, activities, transitions: activities.slice(1).map(item => ({ target: item.id })),
});

test("downstream receivers stay ordinary activities and live entries get appropriate launch modes", () => {
  const receiver = activity("kafka", "kafka", {operation: "get"});
  assert.deepEqual(launchEntry(task("flow", [activity("Start", "start"), receiver])), {kind: "once", name: "Start"});
  assert.deepEqual(launchEntry(task("flow", [receiver])), {kind: "listener", name: "kafka"});
  assert.deepEqual(launchEntry(task("flow", [activity("http", "rest", {operation: "receiver"})])), {kind: "listener", name: "http"});
  assert.deepEqual(launchEntry(task("flow", [activity("timer", "timer", {operation: "schedule"})])), {kind: "schedule", name: "timer"});
  assert.equal(launchEntry({...task("two", [receiver, activity("timer", "timer")]), transitions: []}).kind, "invalid");
});

test("readiness follows selected-profile dependencies, reports missing keys, and omits property values", () => {
  const main = task("main", [activity("Start", "start"), activity("Call", "call_task", {taskId: "sub"})]);
  const sub = task("sub", [
    activity("sub-start", "start"),
    activity("Send", "kafka", {resourceId: "${properties.sender.id}"}),
    activity("Bridge", "sap", {messagingResourceId: "broker"}),
    activity("Dynamic", "call_task", {dynamicTaskId: "${input.task}", taskId: "main"}),
    activity("Unresolved", "jdbc", {resourceId: "${properties.wrong.id}"}),
  ], "subtask");
  const project = {tasks: [main, sub, task("unrelated", [activity("other", "jdbc", {resourceId: "unused"})])],
    resources: [{id: "qa-sender", name: "QA sender", type: "kafka", config: {password: "${properties.sender.secret}", port: "${properties.sender.port}"}},
      {id: "broker", name: "Broker", type: "jms", config: {url: "${properties.broker.url}"}}],
    properties: {qa: [{key: "sender.id", value: "qa-sender"}, {key: "wrong.id", value: "sensitive-mistyped-binding"}, {key: "sender.port", value: 0}, {key: "sender.secret", value: " "}]},
  };
  const report = executionReadiness(project, main, "qa");
  assert.deepEqual(report.taskIds, ["main", "sub"]);
  assert.deepEqual(report.connections.map(item => [item.id, item.usedBy[0], item.missing]), [
    ["qa-sender", "sub / Send", false], ["broker", "sub / Bridge", false], ["properties.wrong.id", "sub / Unresolved", true],
  ]);
  assert.deepEqual(report.propertyFindings, [{key: "broker.url", status: "Missing"}, {key: "sender.secret", status: "Empty"}]);
  assert.equal(report.runtimeDependencies, true);
  assert.doesNotMatch(JSON.stringify(report), /sensitive-mistyped-binding|unused/);
});

test("launch input retains JSON object values and rejects other JSON payload types", () => {
  assert.deepEqual(parseLaunchInput('{"amount":0,"items":[{"paid":false}]}'), {amount: 0, items: [{paid: false}]});
  for (const value of ["null", "[]", "7", '"text"']) assert.throws(() => parseLaunchInput(value), /JSON object/);
  assert.throws(() => parseLaunchInput("{"), SyntaxError);
});
