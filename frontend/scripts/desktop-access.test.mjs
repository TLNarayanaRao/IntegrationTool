import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import assert from "node:assert/strict";
import test from "node:test";
import launcher from "../electron/desktop-access.cjs";

test("port announcement survives fragmented stdout and skips invalid announcements", async () => {
  const process = new EventEmitter();
  process.stdout = new PassThrough();
  const ready = launcher.waitForPort(process, new AbortController().signal, 1000);
  process.stdout.write("diagnostic\nMINA_DESKTOP_PORT=70000\nMINA_DESKT");
  process.stdout.end("OP_PORT=49876\r\n");
  assert.equal(await ready, 49876);
});

test("port wait rejects runtime exit and cancellation", async () => {
  const process = new EventEmitter();
  process.stdout = new PassThrough();
  const ready = launcher.waitForPort(process, new AbortController().signal, 1000);
  process.emit("exit", 7);
  await assert.rejects(ready, /code 7/);
  const startup = new AbortController();
  const second = launcher.waitForPort(process, startup.signal, 1000);
  startup.abort();
  await assert.rejects(second, { name: "AbortError" });
});

test("Studio credential applies only to its renderer API and exact runtime origin", () => {
  const contents = new EventEmitter();
  let interceptor;
  contents.id = 42;
  contents.session = { webRequest: { onBeforeSendHeaders: (_, callback) => { interceptor = callback; } } };
  const origin = "http://127.0.0.1:49876";
  launcher.protectStudioRequests(contents, origin, "owned");
  const token = (url, id = contents.id, initiating, requestHeaders = {}) => {
    let result;
    interceptor({ url, webContentsId: id, initiatorOrigin: initiating, requestHeaders }, headers => { result = headers.requestHeaders; });
    return result[launcher.header];
  };
  assert.equal(token(origin + "/api/projects"), "owned");
  assert.equal(token(origin + "/api/projects", 43), undefined);
  assert.equal(token("http://127.0.0.1:49877/api/projects"), undefined);
  assert.equal(token(origin + "/api/projects", 42, "https://external.invalid"), undefined);
  const redirectHeaders = { "x-mina-desktop-token": "owned" };
  token("https://external.invalid/", 42, origin, redirectHeaders);
  assert.deepEqual(redirectHeaders, {});
  assert.equal(token(origin + "/index.html"), undefined);
  let stopped = false;
  contents.emit("will-navigate", { preventDefault: () => { stopped = true; } }, "http://127.0.0.1:49877/");
  assert.equal(stopped, true);
});
