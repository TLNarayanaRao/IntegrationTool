import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',import.meta.url));
const output=path.join(root,'frontend/public/legal');
await fs.mkdir(output,{recursive:true});
const components=[],lines=['MINA STUDIO — THIRD-PARTY NOTICES','These notices preserve third-party rights and do not relicense MINA or customer applications.'];
const pending=['react','react-dom','scheduler','lucide-react'],seen=new Set();
while(pending.length){
 const name=pending.pop();if(seen.has(name))continue;seen.add(name);
 const folder=path.join(root,'frontend/node_modules',name),pkg=JSON.parse(await fs.readFile(path.join(folder,'package.json'),'utf8'));
 pending.push(...Object.keys(pkg.dependencies||{}));
 const notices=(await fs.readdir(folder)).filter(file=>/licen[cs]e|notice|copying/i.test(file));
 if(!notices.length)throw new Error(`Missing third-party license for ${name}`);
 for(const file of notices){const dest=path.join(output,'licenses/npm',name,file);await fs.mkdir(path.dirname(dest),{recursive:true});await fs.copyFile(path.join(folder,file),dest);}
 const ref=`pkg:npm/${name}@${pkg.version}`;
 components.push({type:'library',name,version:pkg.version,'bom-ref':ref,purl:ref,licenses:[{license:{name:String(pkg.license)}}]});
 lines.push(`${name} ${pkg.version} — ${pkg.license}\n${notices.map(file=>`licenses/npm/${name}/${file}`).join('\n')}`);
}
for(const folder of ['java-icon','dashboard-icons']){
 await fs.cp(path.join(root,'compliance/third_party',folder),path.join(output,'licenses/assets',folder),{recursive:true});
 lines.push(`Additional bundled component/artwork notices: licenses/assets/${folder}`);
}
lines.push('Product names and trademarks identify supported integrations and remain with their owners. No endorsement is implied. Copyright licenses do not grant trademark rights.');
await fs.writeFile(path.join(output,'THIRD_PARTY_NOTICES.txt'),lines.join('\n\n')+'\n');
const pkg=JSON.parse(await fs.readFile(path.join(root,'frontend/package.json'),'utf8'));
const document={bomFormat:'CycloneDX',specVersion:'1.6',version:1,metadata:{component:{type:'application',name:'MINA Studio renderer',version:pkg.version,'bom-ref':'mina:renderer'}},components,dependencies:[{ref:'mina:renderer',dependsOn:components.map(c=>c['bom-ref'])}]};
await fs.writeFile(path.join(output,'SBOM.cdx.json'),JSON.stringify(document,null,2)+'\n');
await fs.writeFile(path.join(output,'index.html'),'<!doctype html><html lang="en"><meta charset="utf-8"><title>MINA third-party licenses</title><h1>MINA third-party licenses</h1><p><a href="THIRD_PARTY_NOTICES.txt">Notices and license locations</a></p><p><a href="SBOM.cdx.json">Renderer SBOM (CycloneDX 1.6)</a></p><p>Desktop runtime notices and corresponding source materials are also installed under resources/runtime/*/legal.</p></html>');
console.log(`Preserved licenses for ${components.length} renderer components.`);
