import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const functions = [];
for (const [file, names] of [
  ["SharedConnectionSelect.tsx", ["matchesConnection"]],
  ["EndpointSchemaPicker.tsx", ["schemaText", "schemaChoiceName", "savedSchemaChoice"]],
  ["HttpContentTypePicker.tsx", ["savedContentTypes"]],
  ["HttpRequestParameters.tsx", ["validateRequestParameters"]],
  ["HttpEndpointSetup.tsx", ["isHttpEndpoint", "newEndpointDraft", "endpointConfig"]],
  ["main.tsx", ["uniqueActivityName", "isTaskTerminal", "withHttpResponse", "ensureTaskEnd"]],
]) {
  const source = await readFile(new URL(`../src/${file}`, import.meta.url), "utf8");
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  functions.push(...ast.statements.filter(statement => names.includes(statement.name?.text) ||
    statement.declarationList?.declarations.some(declaration => names.includes(declaration.name.text)))
    .map(statement => statement.getText(ast).replace(/^export /, "")));
}
const helpers = vm.createContext({
  HTTP_METHODS: ["GET", "POST", "PUT"], activityReferenceName: value => value, advancedDefaults: () => ({}),
});
vm.runInContext(ts.transpileModule(functions.join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, helpers);
const { newEndpointDraft, endpointConfig, isHttpEndpoint, savedSchemaChoice } = helpers;
const resources = [
  { id: "client", type: "http", config: { connectorMode: "client" } },
  { id: "server", type: "http", config: { connectorMode: "server" } },
];
const schemas = [{ id: "payload", name: "payload.schema.json", content: '{"type":"object"}' }];

test("a configured HTTP starter replaces its default End with a response that survives normalization", () => {
  for (const type of ["http_listener", "rest"]) {
    const task = {
      id: "endpoint",
      activities: [
        { id: "Start", name: "Start", type, position: { x: 70, y: 150 }, config: { responseSchema: schemas[0].content } },
        { id: "End", name: "End", type: "end", position: { x: 350, y: 150 }, config: {} },
      ],
      transitions: [{ id: "edge", source: "Start", target: "End", type: "success" }],
    };
    const result = vm.runInContext("withHttpResponse", helpers)(task);
    assert.equal(result.activities.length, 2);
    const response = result.activities[1];
    assert.equal(response.type, "http_response");
    assert.equal(response.config.operation, "response");
    assert.equal(result.transitions[0].target, response.id);
    assert.equal(vm.runInContext("ensureTaskEnd", helpers)(result), result);
    assert.equal(task.activities[1].type, "end");
  }
});

test("only the requested inbound activities enter endpoint setup", () => {
  assert(isHttpEndpoint("http_listener", "listen"));
  assert(isHttpEndpoint("rest", "receiver"));
  assert(!isHttpEndpoint("rest", "invoke"));
  assert(!isHttpEndpoint("http", "request"));
});

test("setup saves the runtime route and schema fields with validation enabled", () => {
  const config = endpointConfig({
    ...newEndpointDraft(), resourceId: "server", path: "/orders/{id}", methods: ["POST", "PUT"],
    request: { source: "payload", text: "" }, response: { source: "@inline", text: '{"type":"string"}' },
    requestContentTypes: ["application/json", "application/xml"],
  }, { resources, schemas });
  assert.deepEqual(JSON.parse(JSON.stringify(config)), {
    resourceId: "server", path: "/orders/{id}", methods: "POST,PUT", requestContentTypes: ["application/json", "application/xml"],
    requestSchema: '{"type":"object"}', requestSchemaName: "payload.schema.json", validateRequest: true,
    responseSchema: '{"type":"string"}', responseSchemaName: "Inline JSON Schema", validateResponse: true,
  });
});

test("selecting an XSD keeps media types automatic unless the user supplies them", () => {
  helpers.DOMParser = class {
    parseFromString() {
      return { querySelector: () => null, documentElement: { localName: "schema", namespaceURI: "http://www.w3.org/2001/XMLSchema" } };
    }
  };
  const response = { source: "@file", name: "reply.xsd", text: '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>' };
  const draft = { ...newEndpointDraft(), resourceId: "server", response, methods: ["GET"] };
  const options = { resources, schemas };
  const auto = endpointConfig(draft, options);
  assert.equal(auto.responseSchemaName, "reply.xsd");
  assert.equal(auto.responseContentTypes, undefined);
  const custom = endpointConfig({ ...draft, requestContentTypes: ["text/xml"], responseContentTypes: ["application/vnd.mina.reply+xml", "application/json"] }, options);
  assert.deepEqual(Array.from(custom.requestContentTypes), ["text/xml"]);
  assert.deepEqual(Array.from(custom.responseContentTypes), ["application/vnd.mina.reply+xml", "application/json"]);
  assert.deepEqual(Array.from(helpers.savedContentTypes(undefined, "application/xml")), ["application/xml"]);
  assert.equal(helpers.savedContentTypes([], "application/xml").length, 0);
});

test("setup rejects incompatible connections, malformed routes and schema text before creation", () => {
  const draft = { ...newEndpointDraft(), resourceId: "server", methods: ["GET"] };
  const options = { resources, schemas };
  assert.throws(() => endpointConfig({ ...draft, resourceId: "client" }, options), /HTTP server connection/);
  assert.throws(() => endpointConfig({ ...draft, path: "/orders/{bad-id}?x=1" }, options), /URI path/);
  assert.throws(() => endpointConfig({ ...draft, methods: [] }, options), /HTTP method/);
  assert.throws(() => endpointConfig({ ...draft, request: { source: "@inline", text: "[]" } }, options), /valid JSON Schema/);
  assert(!("validateRequest" in endpointConfig(draft, options)));
});

test("a GET-only setup persists only GET and validates request parameter declarations", () => {
  const fresh = newEndpointDraft();
  assert.equal(fresh.methods.length, 0);
  const draft = { ...fresh, resourceId: "server", path: "/orders/{id}", methods: ["GET"],
    requestParameters: [{in: "path", name: "id", type: "integer", required: true},
      {in: "header", name: " X-Request-ID ", type: "string", required: true}] };
  const options = {resources, schemas};
  const config = endpointConfig(draft, options);
  assert.equal(config.methods, "GET");
  assert.equal(config.requestParameters[1].name, "X-Request-ID");
  assert.throws(() => endpointConfig({...draft, path: "/orders"}, options), /URI parameter/);
});

test("saved definitions keep their display names and legacy inline XSD has a fallback label", () => {
  assert.equal(savedSchemaChoice(schemas[0].content, schemas[0].name, schemas).source, "payload");
  assert.equal(savedSchemaChoice("<xs:schema/>", "orders.xsd", schemas).name, "orders.xsd");
  assert.equal(savedSchemaChoice("<xs:schema/>", undefined, schemas).name, "Saved XSD");
});
