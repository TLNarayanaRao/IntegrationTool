import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import ts from 'typescript';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const source=await fs.readFile(path.join(root,'frontend/src/xsdSelection.ts'),'utf8');
const editor=await fs.readFile(path.join(root,'frontend/src/ActivityEditor.tsx'),'utf8');
const ast=ts.createSourceFile('editor.tsx',editor,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=['transformSchemaFields','schemaDataFields','boundaryFields','mapperSchemaFields','activityContract','resolvedActivityContract','httpRequestFields'];
const tree=ast.statements.filter(node=>names.includes(node.name?.text)||node.declarationList?.declarations.some(declaration=>['d','f','commonErrors','HTTP_METHODS'].includes(declaration.name.getText(ast)))).map(node=>node.getText(ast)).join('\n');
const code=ts.transpileModule(source+'\n'+tree,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/^export /gm,'');
const schema=await fs.readFile(path.join(root,'docs/assets/ItemEnterpriseLakebase.xsd'),'utf8');
const script=code+`\n(()=>{const text=${JSON.stringify(schema)};
 const noNamespace='<schema xmlns="http://www.w3.org/2001/XMLSchema" xmlns:xs="http://www.w3.org/2001/XMLSchema"><complexType name="Record"><sequence><element name="value" type="xs:string"/></sequence></complexType></schema>';
 const noNamespaceText=selectXsdStructure(noNamespace,'type|{}Record');
 if(transformSchemaFields({targetSchemaText:noNamespaceText})[0]?.name!=='Record')throw new Error('No-namespace type wrapper was lost');
 const noNamespaceDoc=new DOMParser().parseFromString(noNamespaceText,'application/xml');
 const entry=Array.from(noNamespaceDoc.documentElement.children).find(node=>node.getAttributeNS(XSD_SELECTION_NS,'generated'));
 if(!entry||entry.lookupNamespaceURI(null))throw new Error('No-namespace type QName has an incorrect default namespace: '+noNamespaceText);
 return xsdStructures(text).map(option=>{
 const contract=selectXsdStructure(text,option.id);const fields=transformSchemaFields({targetSchemaText:contract});
 const schemas=[{id:'selected',name:'Item.xsd',content:text}];
 const mapper=mapperSchemaFields({targetSchemaId:'selected',targetSchemaText:contract},schemas);
 if(mapper.filter(field=>field.depth===0).map(field=>field.name).join()!==fields[0]?.name)throw new Error('Mapper reload changed selection');
 for(const type of ['start','end']){const task={activities:[{type,config:{interfaceSchemaId:'selected',interfaceSchemaText:contract}}]};const rows=boundaryFields(task,type,schemas);if(rows.some(row=>row.key!==fields[0]?.name&&!row.key.startsWith(fields[0]?.name+'.')))throw new Error('Task interface leaked sibling structures');}
 if(!fields.length)throw new Error('No fields for '+option.id);
 if(fields.filter(field=>field.depth===0).length!==1)throw new Error('Multiple entry roots for '+option.id);
 for(const type of ['http_listener','rest']){
  const endpoint={type,config:{operation:type==='rest'?'receiver':'listen',requestSchema:contract,responseSchema:contract}};
  const input=resolvedActivityContract(endpoint,{activities:[endpoint]},[],schemas);
  const source=input.output.filter(field=>field.key.startsWith('xmlBody.'));
  if(!source.length||source.some(field=>!field.key.startsWith('xmlBody.'+fields[0].name)))throw new Error('Receiver schema selection changed');
  const reply=resolvedActivityContract({type:'http_response',config:{}},{activities:[endpoint]},[],schemas);
  if(reply.input.filter(field=>field.key.startsWith('body.')).some(field=>!field.key.startsWith('body.'+fields[0].name)))throw new Error('Reply schema selection changed');
 }
 const changed=new DOMParser().parseFromString(text,'application/xml');
 for(const node of Array.from(changed.documentElement.children))if(node.getAttribute('name')===option.name&&node.localName===(option.kind==='Element'?'element':'complexType'))node.remove();
 const unavailable=selectedSchemaText(new XMLSerializer().serializeToString(changed),contract);
 if(xsdSelection(unavailable)!==option.id)throw new Error('Missing choice silently changed');
 if(transformSchemaFields({targetSchemaText:unavailable}).length)throw new Error('Unavailable choice exposed another structure');
 const restored=selectedSchemaText(text,contract);
 if(xsdSelection(restored)!==option.id)throw new Error('Selection was lost');
 return {...option,text:contract,root:fields[0].name,paths:fields.map(field=>field.path)};
});})()`;
const folder=await fs.mkdtemp(path.join(os.tmpdir(),'mina-xsd-selection-'));
try{
 const request=path.join(folder,'request.json'),result=path.join(folder,'result.json');
 await fs.writeFile(request,JSON.stringify({script}));
 const environment={...process.env};delete environment.ELECTRON_RUN_AS_NODE;
 const electron=path.join(root,'frontend/node_modules/electron/dist/electron.exe');
 const run=spawnSync(electron,[path.join(root,'frontend/tests/fixtures/xsd-selection-electron.cjs'),request,result],{env:environment,encoding:'utf8',windowsHide:true,timeout:45000});
 const answer=JSON.parse(await fs.readFile(result,'utf8'));
 if(run.status!==0||answer.error)throw new Error(answer.error||run.stderr||String(run.error));
 process.stdout.write(JSON.stringify(answer.result));
}finally{await fs.rm(folder,{recursive:true,force:true});}
