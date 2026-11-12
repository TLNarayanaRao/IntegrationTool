import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const pkg=JSON.parse(await readFile(new URL('../package.json',import.meta.url),'utf8'));
test('installer excludes frontend build tools from runtime dependencies',()=>{
 for(const name of ['vite','typescript','@vitejs/plugin-react']){
  assert.ok(pkg.devDependencies[name]);assert.equal(pkg.dependencies[name],undefined);
 }
 assert.ok(pkg.build.extraResources.some(item=>item.to==='legal'));
 assert.match(pkg.scripts.prebuild,/licenses:build/);
});
test('renderer ships notices and a resolved software inventory',async()=>{
 const bom=JSON.parse(await readFile(new URL('../public/legal/SBOM.cdx.json',import.meta.url),'utf8'));
 assert.equal(bom.bomFormat,'CycloneDX');assert.equal(bom.specVersion,'1.6');
 for(const name of ['react','react-dom','scheduler','lucide-react']){
  assert.ok(bom.components.some(item=>item.name===name&&item.version));
 }
 const notices=await readFile(new URL('../public/legal/THIRD_PARTY_NOTICES.txt',import.meta.url),'utf8');
 assert.match(notices,/react-dom/);assert.match(notices,/lucide-react/);
 assert.match(await readFile(new URL('../public/legal/licenses/npm/react/LICENSE',import.meta.url),'utf8'),/Meta Platforms/);
});
