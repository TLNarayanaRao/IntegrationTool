import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
const naming = await readFile(new URL("../src/studioObjectName.ts", import.meta.url), "utf8");
const ast = ts.createSourceFile("main.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = ast.statements.find(statement => ts.isVariableStatement(statement) &&
  statement.declarationList.declarations.some(item => item.name.getText(ast) === "normalizeObjectNames"));
const code = ts.transpileModule(`${naming}\n${declaration.getText(ast)}\nexport { normalizeObjectNames };`, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
}).outputText;
const { normalizeObjectNames } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("Studio hyphenates object names and keeps existing named calls bound to the task ID", () => {
  const project = {
    id: "project", name: "Example  Project",
    tasks: [
      { id: "root", kind: "starter", name: "Order Starter", groups: [{ name: "Validate Order" }], activities: [
        { type: "call_task", name: "Call Child", config: { taskId: "child flow", dynamicTaskId: "${properties.routing.target}" } },
      ] },
      { id: "child-id", kind: "subtask", name: "Child Flow", activities: [] },
    ],
    resources: [{ id: "db", name: "Local Database" }],
    schemas: [{ id: "schema", name: "Order Details.xsd" }],
    custom_functions: [{ id: "fn", name: "Normalize Value" }],
  };
  const normalized = normalizeObjectNames(project);
  assert.equal(normalized.name, "Example-Project");
  assert.equal(normalized.tasks[0].name, "Order-Starter");
  assert.equal(normalized.tasks[0].groups[0].name, "Validate-Order");
  assert.deepEqual(normalized.tasks[0].activities[0], {
    type: "call_task", name: "Call-Child", config: { taskId: "child-id", dynamicTaskId: "${properties.routing.target}" },
  });
  assert.equal(normalized.tasks[1].name, "Child-Flow");
  assert.deepEqual(normalized.resources[0], { id: "db", name: "Local-Database" });
  assert.equal(normalized.schemas[0].name, "Order-Details.xsd");
  assert.equal(normalized.custom_functions[0].name, "Normalize-Value");
});
