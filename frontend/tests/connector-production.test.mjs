import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=await readFile(new URL('../src/ActivityEditor.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('editor.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const context=vm.createContext({React:{createElement:(type,props,...children)=>({type,props,children:children.flat(Infinity)})},
 f:(key,label,type='text',help='')=>({key,label,type,help}),d:(key,label,type='string',required=false)=>({key,label,type,required}),commonErrors:[],useState:value=>[value,()=>{}],useRef:value=>({current:value}),HTTP_METHODS:JSON.parse(source.match(/export const HTTP_METHODS = (\[[^;]+);/)[1]),Database:'icon',RefreshCw:'icon',FlaskConical:'icon'});
for(const name of ['activityContract','runtimeMappableInputs','JdbcDesigner','FieldEditor']){
 const node=ast.statements.find(item=>item.name?.text===name);
 vm.runInContext(ts.transpileModule(node.getText(ast).replace(/^export /,''),{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText,context);
}
const all=node=>node&&typeof node==='object'?[node,...(node.children||[]).flatMap(all)]:[];
test('legacy listener methods have a visible repair action preserving valid methods',()=>{
 let changed;
 const nodes=all(context.FieldEditor({field:{key:'methods',label:'Methods',type:'methods'},value:'GET,POST,CONNECT',set:(key,value)=>{changed={key,value};}}));
 assert.ok(nodes.some(node=>node.props?.role==='alert'));
 nodes.find(node=>node.type==='button'&&node.children.includes('Remove unsupported methods')).props.onClick();
 assert.deepEqual(changed,{key:'methods',value:'GET,POST'});
});
test('Studio exposes streaming, atomic upload and decompression limits as dynamic Inputs',()=>{
 for(const type of ['ftp','sftp']){
  const get=context.activityContract({type,config:{operation:'get'}});
  for(const key of ['localPath','maxDownloadBytes','overwrite','createDirectories'])assert.ok(get.input.some(item=>item.key===key),key);
  const put=context.activityContract({type,config:{operation:'put'}});
  assert.ok(put.input.some(item=>item.key==='atomicUpload'));assert.equal(put.input.find(item=>item.key==='content').required,false);
  assert.ok(context.activityContract({type,config:{operation:'dir'}}).input.some(item=>item.key==='maxEntries'));
 }
 const read=context.activityContract({type:'file',config:{operation:'read'}});
 assert.ok(read.input.some(item=>item.key==='maxReadBytes'));assert.ok(read.configuration.some(item=>item.key==='compression'));
 assert.ok(context.activityContract({type:'file',config:{operation:'list'}}).input.some(item=>item.key==='maxEntries'));
});
test('Studio keeps OUT parameters out of required Inputs and exposes typed outputs',()=>{
 const node={type:'jdbc',config:{operation:'call',preparedParameters:[{name:'id',type:'integer',direction:'IN'},{name:'total',type:'integer',direction:'OUT'}]}};
 const contract=context.activityContract(node),inputs=context.runtimeMappableInputs(node,contract);
 assert.ok(inputs.some(item=>item.key==='parameters.id'));assert.ok(!inputs.some(item=>item.key==='parameters.total'));
 assert.equal(contract.output.find(item=>item.key==='outParameters.total').type,'integer');
});
test('Studio procedure controls add parameters and block duplicate names',()=>{
 let patch;
 const render=config=>all(context.JdbcDesigner({config,resource:{config:{driver:'oracle'}},properties:[],setConfig:value=>{patch=value;}}));
 let nodes=render({operation:'call',preparedParameters:[]});nodes.find(n=>n.type==='button'&&n.children.includes('Add procedure parameter')).props.onClick();
 assert.equal(patch.preparedParameters[0].direction,'IN');
 nodes=render({operation:'call',preparedParameters:[{name:'same',type:'integer'},{name:'same',type:'integer',direction:'OUT'}]});
 assert.ok(nodes.some(n=>n.props?.role==='alert'));
 assert.equal(nodes.find(n=>n.type==='button'&&n.children.some(child=>child===' Run & fetch')).props.disabled,true);
 assert.ok(nodes.some(n=>n.type==='select'&&n.props['aria-label']==='Direction for same'));
 nodes.find(n=>n.props?.['aria-label']==='Remove parameter same').props.onClick();
 assert.equal(patch.preparedParameters.length,1);
});
