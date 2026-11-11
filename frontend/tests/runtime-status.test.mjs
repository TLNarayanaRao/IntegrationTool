import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = await readFile(new URL("../src/RuntimeStatus.tsx", import.meta.url), "utf8");
const code = ts.transpileModule(source, {compilerOptions:{
  module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2020, jsx:ts.JsxEmit.React,
  jsxFactory:"create", jsxFragmentFactory:"Fragment",
}}).outputText;
const nodes = tree => tree && typeof tree === "object" ? [tree,...(tree.children || []).flatMap(nodes)] : [];

function harness({healthy = true, desktop = false, progress} = {}) {
  const states = [], effects = [], timers = new Map();
  let stateIndex, effectIndex, tree, clock = Date.now(), timerId = 0;
  const create = (type, props, ...children) => ({type,props:props || {},children:children.flat(Infinity)});
  const hooks = {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = initial;
      return [states[index],value => {states[index] = typeof value === "function" ? value(states[index]) : value;}];
    },
    useEffect(callback,deps) {
      const index = effectIndex++, previous = effects[index];
      if (!previous || deps.some((value,i) => value !== previous.deps[i])) {
        previous?.cleanup?.();
        effects[index] = {deps,callback};
      }
    },
  };
  const window = {
    setTimeout(callback,delay) {const id = ++timerId; timers.set(id,{callback,delay}); return id;},
    clearTimeout(id) {timers.delete(id);},
    ...(desktop ? {minaDesktop:{getStartupStatus:async () => ({step:3,total:3,label:"Studio and runtime ready",elapsedMs:100,failed:false}),
      onStartupStatus:() => () => {}}} : {}),
  };
  const context = vm.createContext({
    exports:{}, create, Fragment:"fragment", window, AbortController,
    Date:class extends Date {static now() {return clock;}},
    require(name) {return name === "react" ? hooks : name === "lucide-react" ? new Proxy({}, {get:(_,key)=>String(key)}) : {default:"modal"};},
    fetch:async url => ({ok:url === "/api/health" ? healthy : !!progress, status:url === "/api/health" ? healthy ? 200 : 503 : progress ? 200 : 404,
      json:async () => url === "/api/health" ? {status:healthy ? "ok" : "error"} : progress || {detail:"Not Found"}}),
  });
  vm.runInContext(code,context);
  const render = () => {
    stateIndex = effectIndex = 0;
    tree = context.exports.default({projectId:"workspace"});
    for (const effect of effects) if (effect.callback) {
      const callback = effect.callback; delete effect.callback; effect.cleanup = callback();
    }
  };
  const flush = async () => {for (let i=0;i<8;i++) {render(); await new Promise(setImmediate);} render();};
  const button = () => nodes(tree).find(node => node.type === "button" && node.props["aria-label"]?.startsWith("Runtime status:"));
  return {flush,button,nodes:() => nodes(tree),
    async open() {button().props.onClick();await flush();},
    async close() {nodes(tree).find(node=>node.type === "button" && node.children.includes("Close")).props.onClick();await flush();},
    async recover() {healthy = true;clock += 11000;for (const [id,timer] of [...timers]) {timers.delete(id);timer.callback();} await flush();},
  };
}

test("missing activity progress does not change a healthy runtime to unavailable when opening or closing details",async()=>{
  const app = harness();
  await app.flush();
  assert.equal(app.button().props["aria-label"],"Runtime status: Runtime ready");
  await app.open();
  assert(app.nodes().some(node=>node.type === "p" && node.children.some(text=>typeof text === "string" && text.includes("Activity progress details are unavailable"))));
  assert.equal(app.button().props["aria-label"],"Runtime status: Runtime ready");
  await app.close();
  assert.equal(app.button().props["aria-label"],"Runtime status: Runtime ready");
});

test("live health overrides stale desktop startup readiness and recovers without reopening Studio",async()=>{
  const app = harness({healthy:false,desktop:true});
  await app.flush();
  assert.equal(app.button().props["aria-label"],"Runtime status: Runtime unavailable");
  await app.open();
  await app.close();
  assert.equal(app.button().props["aria-label"],"Runtime status: Runtime unavailable");
  await app.recover();
  assert.equal(app.button().props["aria-label"],"Runtime status: Runtime ready");
});

test("closing details keeps a reported running status visible in the footer",async()=>{
  const app = harness({progress:{status:"running",activities:[{taskId:"main",taskName:"Main",activityId:"wait",activityName:"Waiting",startedAt:"now"}]}});
  await app.flush();
  await app.open();
  assert.equal(app.button().props["aria-label"],"Runtime status: Waiting");
  await app.close();
  assert.equal(app.button().props["aria-label"],"Runtime status: Waiting");
});
