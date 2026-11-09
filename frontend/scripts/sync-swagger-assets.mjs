// Bundle offline Swagger UI assets into a Python module for all deployment formats.
import fs from 'node:fs/promises';
import {gzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
const base=new URL('../node_modules/swagger-ui-dist/',import.meta.url);
const metadata=JSON.parse(await fs.readFile(new URL('package.json',base),'utf8'));
const assets={};
for(const name of ['swagger-ui-bundle.js','swagger-ui.css','LICENSE','NOTICE']){
 const bytes=await fs.readFile(new URL(name,base));
 assets[name]={data:gzipSync(bytes,{level:9,mtime:0}).toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex')};
}
await fs.writeFile(new URL('../../backend/app/swagger_assets.py',import.meta.url),
 `"""Generated offline Swagger UI ${metadata.version}. Apache-2.0; LICENSE/NOTICE served alongside assets.\nRebuild: node frontend/scripts/sync-swagger-assets.mjs\n"""\nVERSION = ${JSON.stringify(metadata.version)}\nASSETS = ${JSON.stringify(assets)}\n`);
console.log(`Bundled Swagger UI ${metadata.version}: ${Object.keys(assets).length} offline assets.`);
