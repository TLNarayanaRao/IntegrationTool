import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/taskEntry.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { taskEntryMode } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

const start = { id: "start", type: "start" };
const end = { id: "end", type: "end" };
const receiver = { id: "receiver", type: "kafka", config: { operation: "get" } };

test("a legacy starter with a plain Start is displayed as a subtask", () => {
  assert.equal(taskEntryMode({ kind: "starter", activities: [start, end], transitions: [{ target: "end" }] }), "subtask");
});

test("only a receiver at the task entry point makes it an event starter", () => {
  assert.equal(taskEntryMode({
    kind: "starter", activities: [start, receiver, end], transitions: [{ target: "receiver" }, { target: "end" }],
  }), "subtask");
  assert.equal(taskEntryMode({ kind: "starter", activities: [receiver, end], transitions: [{ target: "end" }] }), "starter");
});

test("a callable task with Start is still a subtask", () => {
  assert.equal(taskEntryMode({ kind: "subtask", activities: [start, end], transitions: [{ target: "end" }] }), "subtask");
});
