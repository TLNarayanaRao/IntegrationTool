import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source=await readFile(new URL('../src/main.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('main.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=['supportsOutboundRetry','advancedDefaults'];
const selected=ast.statements.filter(s=>s.declarationList?.declarations.some(d=>names.includes(d.name.text)));
const context=vm.createContext({});
vm.runInContext(ts.transpileModule(selected.map(s=>s.getText(ast)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);

test('retry controls appear for outbound operations and exclude inbound receivers',()=>{
  for(const [kind,operation] of [['http','request'],['rest','invoke'],['jms','get_queue_message'],['amqp','send'],['kafka','send']]){
    const defaults=vm.runInContext(`advancedDefaults(${JSON.stringify(kind)},${JSON.stringify(operation)})`,context);
    for(const key of ['retryEnabled','retryCount','retryBackoff','retryMaxIntervalSeconds','retryMaxElapsedSeconds','retryJitter','retryFaultTypes'])assert(key in defaults,key);
  }
  for(const [kind,operation] of [['rest','receiver'],['amqp','receive'],['kafka','receive'],['jms','receive_message']]){
    assert.equal(vm.runInContext(`Object.keys(advancedDefaults(${JSON.stringify(kind)},${JSON.stringify(operation)})).some(k=>k.startsWith('retry'))`,context),false);
  }
});
