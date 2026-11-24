import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = await readFile(new URL("../src/endpointRequests.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const moduleScope = { exports: {}, URL };
vm.runInNewContext(compiled, moduleScope);
const { endpointRequestFile } = moduleScope.exports;

test("HTTP request files include configured methods and path variables and omit credentials and query strings", () => {
  const requests = endpointRequestFile("https://name:secret@example.test:8081/orders/{id}/{id}?token=private#fragment",
    ["GET", "get", "PATCH", "GET\r\nAuthorization"]);
  assert.equal(requests.split("@id = replace-me").length, 2);
  assert.equal(requests.split("GET https://example.test:8081/orders/{{id}}/{{id}}").length, 2);
  assert.ok(requests.includes("PATCH https://example.test:8081/orders/{{id}}/{{id}}"));
  assert.doesNotMatch(requests, /name:secret|token|private|fragment|Authorization/);
});

test("unsupported protocols, malformed inputs and non-HTTP entries have no request file", () => {
  for (const url of ["ftp://example.test/file", "/local", "https://example.test/\nOPTIONS"]) {
    assert.equal(endpointRequestFile(url, ["GET"]), null);
  }
  assert.equal(endpointRequestFile("https://example.test", ["CONNECT"]), null);
});
