import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const root=new URL('../',import.meta.url);
const read=path=>fs.readFileSync(new URL(path,root),'utf8');
function evaluate(source,require=()=>{throw new Error('Unexpected import');},extra={}) {
  const context=vm.createContext({exports:{},require,...extra});
  vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,context);
  return context.exports;
}
// Evaluate the real activity catalog, removing only the group heading icons.
const source=ts.createSourceFile('main.tsx',read('src/main.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let initializer;
for(const statement of source.statements) if(ts.isVariableStatement(statement)) {
  for(const declaration of statement.declarationList.declarations) if(declaration.name.getText(source)==='packs') initializer=declaration.initializer;
}
const transformed=ts.transform(initializer,[context=>node=>ts.visitNode(node,function visit(item){
  if(ts.isPropertyAssignment(item)&&item.name.getText(source)==='icon') return ts.factory.createPropertyAssignment('icon',ts.factory.createNull());
  return ts.visitEachChild(item,visit,context);
})]);
const packs=evaluate('exports.packs='+ts.createPrinter().printNode(ts.EmitHint.Expression,transformed.transformed[0],source)).packs;
transformed.dispose();
const entries=packs.flatMap(pack=>pack.items),catalog=new Map();
for(const entry of entries) catalog.set(entry.type,[...(catalog.get(entry.type)||[]),entry]);
const bundledIcons=Object.fromEntries(fs.readdirSync(new URL('src/assets/activity-icons/',root))
  .filter(name=>name.endsWith('.svg')).map(name=>['./assets/activity-icons/'+name,'/bundled/'+name]));
const urls=evaluate(read('src/activityIconUrl.ts').replace(/const bundledIcons = [\s\S]*?\n\}\);/,'const bundledIcons = globalThis.icons;'),undefined,{icons:bundledIcons});
const icons=evaluate(read('src/studioIcons.ts'),name=>{
  assert.equal(name,'./activityIconUrl');return urls;
});

test('every picker entry resolves to the same canvas artwork and an existing file',()=>{
  assert(entries.length>=100);
  for(const entry of entries) {
    assert.equal(icons.activityIconAsset({type:entry.type,config:{operation:entry.operation}},catalog),entry.asset,entry.label);
    assert.equal(icons.activityIconAsset(entry,catalog),entry.asset,entry.label);
    const url=urls.activityIconUrl(entry.asset);
    const path=url.startsWith('/bundled/')?'src/assets/activity-icons/'+url.slice(9):'public'+url;
    assert(fs.existsSync(new URL(path,root)),`${entry.label}: missing ${url}`);
  }
});

test('legacy mapper types keep Mapper artwork; unknown activities never borrow Start or End',()=>{
  for(const type of ['mapper','transform','ai_transform']) assert.equal(icons.activityIconAsset({type},catalog),'mapper-symbol.svg');
  assert.equal(icons.activityIconAsset({type:'future_activity'},catalog),'activity.svg');
});

test('connection menu and explorer share existing icons, including bundled JMS and Snowflake artwork',()=>{
  for(const type of ['http','http_client','http_server','ftp','sftp','ems','jms','kafka','pubsub','jdbc','snowflake','amqp','sap','sap_tid']) {
    const url=icons.connectionIconUrl(type);
    assert(url,type);
    assert(fs.existsSync(new URL(url.startsWith('/bundled/')?'src/assets/activity-icons/'+url.slice(9):'public'+url,root)),`${type}: ${url}`);
  }
  assert.equal(icons.connectionIconUrl('http_server'),icons.connectionIconUrl('http'));
  assert.equal(icons.connectionIconUrl('http_client'),icons.connectionIconUrl('http'));
  for(const type of ['jms','snowflake']) assert(icons.connectionIconUrl(type).startsWith('/bundled/'));
});
