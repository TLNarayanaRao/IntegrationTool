// Cross-layer test bridge: use the same deletion and persistence code as Studio.
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../../src/mapperLoopMappings.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {activityMappingRules,activityMappingsFromRules,removeMappingSubtree}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
let input='';for await(const chunk of process.stdin)input+=chunk;
const requests=JSON.parse(input);
process.stdout.write(JSON.stringify(requests.map(({mappings,target,occurrenceId,duplicateRoot})=>{
 const array=Array.isArray(mappings);
 const cleared=removeMappingSubtree(array ? mappings : activityMappingRules(mappings),target,occurrenceId,duplicateRoot);
 return array ? cleared : activityMappingsFromRules(cleared);
})));
