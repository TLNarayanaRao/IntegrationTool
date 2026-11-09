import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("main.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set([
  "defaultProperties", "newEnvironmentProperties", "connectorType", "connectorPropertyPrefix", "protocolPropertyTemplates",
  "propertyBindingKey", "connectionPropertyValue", "addMissingProperties",
  "addProtocolProperties", "connectionFieldSets", "connectionDefaults", "seedAddedProtocols",
]);
const helpers = ast.statements.filter(statement => names.has(statement.name?.text) ||
  statement.declarationList?.declarations.some(declaration => names.has(declaration.name.text)));
const moduleCode = ts.transpileModule(helpers.map(statement => statement.getText(ast)).join("\n"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;
const api = vm.runInNewContext(`${moduleCode}\n({ ${[...names].join(", ")} })`);
const values = items => Object.fromEntries(items.map(item => [item.key, item.value]));

test("new environments use core properties and templates for protocols in use", () => {
  const core = values(api.newEnvironmentProperties());
  assert.equal(core["advanced.retryCount"], 3);
  assert.equal(Object.keys(core).some(key => key.startsWith("connections.")), false);
  const next = values(api.newEnvironmentProperties(["kafka"]));
  assert.equal(next["connections.kafka.bootstrapServers"], "localhost:9092");
  assert.equal(Object.keys(next).some(key => key.startsWith("connections.sap.")), false);
});

test("adding a resource and a protocol activity seeds their settings in each environment", () => {
  const key = "connections.kafka.bootstrapServers";
  const project = {
    id: "workspace",
    resources: [],
    tasks: [],
    active_environment: "local",
    properties: { local: [], dev: [{ key, value: "dev-broker:9092", data_type: "string" }], qa: [] },
  };
  const resource = { id: "broker", type: "kafka", config: { bootstrapServers: "local-broker:9092", password: "secret" } };
  const result = api.seedAddedProtocols(project, {
    ...project,
    resources: [resource],
    tasks: [{ id: "main", activities: [{ id: "start", type: "rest" }] }],
  });
  assert.equal(values(result.properties.local)[key], "local-broker:9092");
  assert.equal(values(result.properties.dev)[key], "dev-broker:9092");
  assert.equal(values(result.properties.qa)[key], "localhost:9092");
  assert.equal(values(result.properties.local)["connections.kafka.password"], "");
  assert.equal(values(result.properties.local)["connections.http.port"], 8080);
  assert.equal(values(result.properties.local)["connections.http.oauthClientSecret"], "");
  assert.equal(Object.keys(values(result.properties.local)).every(key => /^connections\.(kafka|http)\./.test(key)), true);
  const edited = { ...result, properties: { ...result.properties, local: [] } };
  assert.equal(api.seedAddedProtocols(result, edited), edited);
});

test("connection defaults work without generated properties and HTTP activities share one template", () => {
  const defaults = api.connectionDefaults("kafka");
  assert.equal(defaults.bootstrapServers, "localhost:9092");
  assert.equal(Object.values(defaults).some(value => api.propertyBindingKey(value)), false);
  const templates = api.protocolPropertyTemplates(["http", "http_listener", "rest", "soap"]);
  assert.equal(templates.length, api.protocolPropertyTemplates(["http"]).length);
  assert.equal(values(templates)["connections.http.port"], 8080);
});

test("every supported shared connection has a template for each required and optional field", () => {
  for (const [type, fields] of Object.entries(api.connectionFieldSets)) {
    const templates = new Map(api.protocolPropertyTemplates([type]).map(item => [item.key, item]));
    for (const field of fields) {
      const key = api.connectorPropertyPrefix(type) + field.key;
      assert.ok(templates.has(key), key);
      if (field.password || field.jsonFile) assert.equal(templates.get(key).data_type, "password", key);
    }
  }
});
