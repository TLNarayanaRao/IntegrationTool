import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=['activityContract','httpRequestOccurrences','cardinalitySymbol'];
const code=ts.transpileModule(ast.statements.filter(item=>names.includes(item.name?.text))
  .map(item=>item.getText(ast).replace(/^export /,'')).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const context=vm.createContext({d:(key,label,type='string',required=false,help='')=>({key,label,type,required,help}),f:(key,label,type,help)=>({key,label,type,help})});
vm.runInContext(code,context);
const fields=context.activityContract({type:'http_response',config:{}}).input;

test('HTTP Send Response offers optional standard and repeating custom headers by default',()=>{
  for(const key of ['HTTPHeaders','HTTPHeaders.Content-Type','HTTPHeaders.StatusLine','HTTPHeaders.Cookies',
    'HTTPHeaders.StatusLine.httpVersion','HTTPHeaders.StatusLine.statusCode','HTTPHeaders.StatusLine.reasonPhrase',
    'DynamicHTTPHeaders','DynamicHTTPHeaders.Headers','DynamicHTTPHeaders.Headers.headerName','DynamicHTTPHeaders.Headers.headerValue']){
    const field=fields.find(item=>item.key===key);
    assert.ok(field,key);assert.equal(field.required,false,key);assert.ok(field.help,key);
    assert.equal(context.cardinalitySymbol(field),['HTTPHeaders.Cookies','DynamicHTTPHeaders.Headers'].includes(key)?'*':'?',key);
  }
  for(const key of ['headers','body','binaryContent','fileName'])assert.ok(fields.some(item=>item.key===key),key);
  assert.equal(fields.find(item=>item.key==='HTTPHeaders.StatusLine').type,'object');
  assert.equal(fields.find(item=>item.key==='HTTPHeaders.StatusLine').validationType,'object|string');
  assert.equal(fields.find(item=>item.key==='HTTPHeaders.StatusLine.statusCode').type,'integer');
});

test('independent dynamic response header entries keep both name/value child fields',()=>{
  const mappings={'DynamicHTTPHeaders.Headers.0':'{}','DynamicHTTPHeaders.Headers.0.headerName':'"X-First"','DynamicHTTPHeaders.Headers.1':'{}'};
  const rows=context.httpRequestOccurrences(fields,mappings);
  for(const index of [0,1])for(const child of ['headerName','headerValue'])
    assert.ok(rows.some(item=>item.key===`DynamicHTTPHeaders.Headers.${index}.${child}`));
  assert.ok(rows.some(item=>item.key==='HTTPHeaders.Content-Type'));
  assert.ok(fields.some(item=>item.key==='DynamicHTTPHeaders.Headers.headerName'));
  assert.equal(mappings['DynamicHTTPHeaders.Headers.0.headerName'],'"X-First"');
  const refreshed=context.httpRequestOccurrences(rows,{...mappings,'DynamicHTTPHeaders.Headers.2':'{}'});
  assert.ok(refreshed.some(item=>item.key==='DynamicHTTPHeaders.Headers.2.headerValue'));
  assert.ok(!refreshed.some(item=>item.key.includes('Headers.0.0')));
});
