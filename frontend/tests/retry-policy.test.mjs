import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const main=await readFile(new URL('../src/main.tsx',import.meta.url),'utf8');
const resilience=await readFile(new URL('../src/activityResilience.ts',import.meta.url),'utf8');
const ast=ts.createSourceFile('main.tsx',main,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const defaults=ast.statements.find(s=>s.declarationList?.declarations.some(d=>d.name.text==='advancedDefaults'));
const context=vm.createContext({});
const source=resilience.replace(/^export /gm,'')+'\n'+defaults.getText(ast);
vm.runInContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);

test('retry controls appear for outbound operations and exclude inbound receivers',()=>{
  for(const [kind,operation] of [['http','request'],['rest','invoke'],['jms','get_queue_message'],['amqp','send'],['kafka','send']]){
    const defaults=vm.runInContext(`advancedDefaults(${JSON.stringify(kind)},${JSON.stringify(operation)})`,context);
    for(const key of ['retryEnabled','retryCount','retryBackoff','retryMaxIntervalSeconds','retryMaxElapsedSeconds','retryJitter','retryFaultTypes'])assert(key in defaults,key);
  }
  for(const [kind,operation] of [['rest','receiver'],['amqp','receive'],['kafka','receive'],['jms','receive_message']]){
    assert.equal(vm.runInContext(`Object.keys(advancedDefaults(${JSON.stringify(kind)},${JSON.stringify(operation)})).some(k=>k.startsWith('retry'))`,context),false);
  }
});

test('circuit controls are opt-in and exclude HTTP, inbound, reply and settlement operations',()=>{
  for (const [kind,operation] of [['jdbc','query'],['ftp','get'],['jms','send_message'],['pubsub','publish']]) {
    const settings=vm.runInContext(`advancedDefaults(${JSON.stringify(kind)},${JSON.stringify(operation)})`,context);
    assert.equal(settings.circuitEnabled,false);
    assert.equal(settings.circuitFailureThreshold,5);
    assert.equal(settings.circuitCooldownSeconds,30);
  }
  for (const [kind,operation] of [['http','request'],['rest','invoke'],['amqp','receive'],['amqp','dead_letter'],['ems','reply']]) {
    const settings=vm.runInContext(`advancedDefaults(${JSON.stringify(kind)},${JSON.stringify(operation)})`,context);
    assert(!('circuitEnabled' in settings));
  }
});
