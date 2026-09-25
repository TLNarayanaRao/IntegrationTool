// Build an offline reference from the same contracts used by Studio.
// Only checked-in product definitions and an explicit guide allowlist are read.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import ts from 'typescript';
import { connectorDetails, connectorFieldHelp } from './connector-documentation.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const out = path.join(root, 'frontend/public/help');
const read = name => fs.readFile(path.join(root, name), 'utf8');
const slug = text => String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const sha = text => createHash('sha256').update(text).digest('hex');
const guides = [
 ['Getting started', 'DOCUMENTATION.md'],
 ['Studio', 'DEBUG_TESTING.md'], ['Studio', 'DEBUGGING.md'], ['Studio', 'FILE_UTILITIES.md'],
 ['Operations', 'RUNTIME_LOGGING.md'], ['Operations', 'ADMINISTRATOR_GUIDE.md'],
 ['Operations', 'control-plane-operator-workspace.md'], ['Deployment', 'PYTHON_EXPORT.md'],
 ['Deployment', 'VENDOR_DRIVERS.md'], ['Deployment', 'ENVIRONMENT_VARIABLES.md'],
 ['Connectors', 'SAP_INTEGRATION.md'], ['Connectors', 'EMS_RUN_CONNECTION_REUSE.md'],
 ['Connectors', 'KAFKA_PUBLISHING.md'], ['Security', 'SECURITY_REVIEW_2026-09-22.md'],
 ['Security', 'WEB_DEPENDENCY_SECURITY.md'],
];
const sourceFiles = ['frontend/src/main.tsx', 'frontend/src/ActivityEditor.tsx', 'frontend/src/ActivityPicker.tsx', 'frontend/src/mapper-functions.ts', 'frontend/package.json', 'backend/app/runtime.py', 'backend/app/sap.py', 'backend/app/java_bridge.py', 'java-bridge/src/com/integrationfabric/bridge/FabricJavaBridge.java', 'frontend/scripts/connector-documentation.mjs', 'frontend/scripts/build-documentation.mjs', 'scripts/build-documentation-pdf.py', 'frontend/public/help/documentation.js', 'frontend/public/help/documentation.css', 'frontend/public/help/index.html', ...guides.map(([, f]) => `docs/${f}`)];
const sources = new Map(await Promise.all(sourceFiles.map(async name => [name, await read(name)])));
const fingerprint = sha(sourceFiles.map(name => `${name}\n${sources.get(name)}`).join('\n'));
if (process.argv.includes('--check')) {
 const receipt = JSON.parse(await read('frontend/public/help/documentation-build.json'));
 if (receipt.fingerprint !== fingerprint) throw new Error('Documentation is stale. Run npm run docs:build (requires Python and reportlab).');
 for (const [name, digest] of Object.entries(receipt.files)) {
  if (sha(await fs.readFile(path.join(out, name))) !== digest) throw new Error(`Documentation artifact changed or missing: ${name}. Run npm run docs:build.`);
 }
 console.log('Documentation source coverage and PDF/web fingerprints verified.');
 process.exit(0);
}
// Extract named pure declarations with the TS parser, never regex-evaluate UI code.
function declarations(file, names, stripIcons = false) {
 const source = ts.createSourceFile(file, sources.get(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
 const found = new Map();
 for (const statement of source.statements) {
  if (ts.isFunctionDeclaration(statement) && statement.name && names.includes(statement.name.text)) found.set(statement.name.text, statement.getText(source).replace(/^export\s+/, ''));
  if (ts.isVariableStatement(statement)) for (const d of statement.declarationList.declarations) {
   if (ts.isIdentifier(d.name) && names.includes(d.name.text)) {
    let init = d.initializer;
    if (stripIcons && d.name.text === 'packs') {
     const transform = ts.transform(init, [ctx => node => {
      const visit = n => ts.isPropertyAssignment(n) && n.name.getText(source) === 'icon' ? undefined : ts.visitEachChild(n, visit, ctx);
      return ts.visitNode(node, visit);
     }]);
     init = transform.transformed[0];
    }
    found.set(d.name.text, `const ${d.name.text} = ${ts.createPrinter().printNode(ts.EmitHint.Expression, init, source)};`);
   }
  }
 }
 for (const name of names) if (!found.has(name)) throw new Error(`Documentation extractor cannot find ${name} in ${file}`);
 return names.map(name => found.get(name)).join('\n');
}
const contractNames = ['f', 'd', 'commonErrors', 'HTTP_METHODS', 'isMapperActivity', 'activityContract', 'runtimeMappableInputs', 'activityDocumentation'];
const mainNames = ['packs', 'supportsOutboundRetry', 'advancedDefaults', 'defaultProperties', 'connectionFieldSets', 'propertyExpression', 'connectionDefaults', 'groupConfigDefaults'];
const extracted = declarations('frontend/src/ActivityEditor.tsx', contractNames) + '\n' + declarations('frontend/src/main.tsx', mainNames, true) + '\nexport {' + [...contractNames, ...mainNames].join(',') + '};';
const compile = code => ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const load = code => import(`data:text/javascript;base64,${Buffer.from(compile(code)).toString('base64')}`);
const defs = await load(extracted);
const { mapperFunctionCatalog } = await load(sources.get('frontend/src/mapper-functions.ts'));
const p = text => ({ kind: 'p', text });
const code = text => ({ kind: 'code', text });
const section = (title, blocks) => ({ title, blocks });
const table = (columns, rows) => ({ kind: 'table', columns, rows });
// Documentation describes driver setup without reproducing provider-owned class names.
// Preserve those identifiers in runtime configuration: they are not MINA branding.
const documentedDefault = field => ['connectionFactoryClass', 'jndiContextFactory'].includes(field.key.split('.').at(-1)) && field.defaultValue
 ? '[Provider-specific class supplied by the runtime; use the exact class from your driver documentation when overriding.]'
 : JSON.stringify(field.defaultValue);
const fields = values => table(['Field / key', 'Type / required', 'Details'], values.map(f => [
 `${f.label || f.key}\n${f.key}`,
 `${f.type || (f.password ? 'password' : f.options ? 'select' : 'text')}\n${f.required ? 'Required' : 'Not marked required by editor'}`,
 [f.help, f.options?.length ? `Choices: ${f.options.join(', ')}` : '', f.defaultValue !== undefined ? `Default: ${documentedDefault(f)}` : '', f.when ? `Conditional field: ${String(f.when)}` : '', f.resourceType ? `Connection type: ${f.resourceType}` : '', f.resourceTypes ? `Connection types: ${f.resourceTypes.join(', ')}` : '', f.placeholder ? `Editor hint: ${f.placeholder}` : '', f.readOnly ? 'Read-only' : ''].filter(Boolean).join('\n') || 'No additional field description is supplied by the editor. Requiredness can also depend on operation, selected schema, provider and runtime validation.',
 ]));
const errorPolicy = [p('On error: propagate (default), continue with an error document, or ignore and continue. Error output variable selects where the fault is exposed; Include activity input in fault is enabled by default. Including payloads in faults or logs may expose sensitive data. An empty declared-fault list does not guarantee that execution cannot fail.')];
const pages = [];
function add(id, title, category, sections, extra = {}) { pages.push({ id, title, category, sections, ...extra }); }
add('overview', 'MINA documentation', 'Getting started', [section('Overview', [p('Mediation, Integration and Automation. This installed reference covers Studio, activities, tasks, groups, mapping functions, shared connections, runtime, deployment and Control Plane. It is available offline and contains no project data or credentials.'), p('Activity fields are extracted from the Studio editor contracts. A shared field marked optional may still be needed for a selected mode or provider. Dynamic schemas are project-specific; the guide explains how Studio derives them rather than inventing their fields.'), p('Use the tree or search to choose a topic. Activity pages have Configuration, Input, Output, Advanced and Errors tabs. Download the complete PDF for the same reference in a portable format.'), p('Scope: this is a product reference, not a claim of provider certification or production security readiness. Read the Security section before shared or production deployment.')])]);
add('tasks', 'Tasks, sub-tasks and event starters', 'Studio', [
 section('Configuration', [p('A project contains Starter Tasks and callable Sub Tasks. Give each task a unique name. Start and End define task boundaries; an event receiver replaces manual Start for event-driven tasks. Call Sub Task selects a target and may resolve a dynamic override at runtime. Keep an explicit fallback when packaging must discover a called task.'), p('Create activities on the canvas and connect transitions. Conditions use input, environment properties and earlier activity output. Validate Task and Validate Project before Run or Debug. Nested calls are shown in the debug process/activity tree.')]),
 section('Input', [p('Declare the task input using an inline schema or a project schema. Call Sub Task maps into that interface. Event starters receive data from their configured system; they do not require mapping an inbound event from a preceding activity. Real providers still require valid connection and listener configuration.')]),
 section('Output', [p('Map the End activity to the task output interface. A waiting Call Sub Task publishes the called result. Spawn without waiting does not provide the synchronous business result. Project-selected schemas determine actual child fields.')]),
 section('Advanced', [p('Run and ordinary Debug keep continuous starters ready for events until stopped. Activity Testing opens a paused session without starting event listeners. Debug stepping and breakpoints affect the active job; test-bench Run once executes only the selected activity, not a complete process.')]),
 section('Errors', [p('Connect specific error paths or use Catch and Rethrow. Unhandled sub-task errors propagate to the caller. Missing task references, broken mappings, unavailable providers and malformed group graphs require correction before reliable execution.')]),
]);
add('mapping', 'Input mapping, schemas and expressions', 'Studio', [section('Mapping workflow', [p('Select an activity and open Input. Drag Data fields, Functions or Constants onto a target, or type an expression. The expanded input editor provides more space and applies edits only after Apply mappings. For typed suggestions enter a dot in a data expression, or press Ctrl+Space; Enter or Tab accepts a suggestion.'), code('${input.customer.id}\n${properties.routing.destination}\n${Previous-Activity.result}\n${vars.currentElement}'), p('Use the Data tree for the actual saved reference names. A constant string is different from an expression; keep datatype conversion and quoting appropriate for the target. Structural schema nodes are populated through child fields; supported union/scalar targets accept whole values.'), p('Repeating targets support For Each and For Each Group. Conditional mappings support If, When/Otherwise and Choose. Project functions use named parameters in expressions; built-in function pages list signatures and insertion templates, not guaranteed outputs for every input datatype.'), p('JDBC named parameters such as :orderId create Input parameters.orderId after SQL analysis. Set the parameter datatype before mapping. SAP IDoc fields derive from fetched metadata; XML/JSON/flat data fields derive from the chosen schema. Call Sub Task fields derive from the selected task interface. Refresh metadata and validate after changing contracts.')])]);
add('ai-development', 'AI-assisted task and project development', 'Studio', [section('Workflow', [p('AI Build accepts a requirement for the current Task or Complete Project. Review the design preview and generated definition before Apply. Generation alone does not deploy or run the application. Without a configured model key, the local blueprint builder is used.'), p('Do not enter credentials or confidential payloads into AI prompts. The current prompt instruction to exclude credentials is not an enforced redaction boundary. Validate and test generated designs, and review the security report before enabling shared access.')])]);
add('workspace', 'Workspace, projects and samples', 'Studio', [section('Workspace', [p('Use the project tree to manage Tasks, schemas, resources and environment properties. The palette and searchable activity picker add activities to the canvas. Select and move activities, edit their display names, and configure transition conditions. Use Window for the XML/JSON viewers and comparison workspace.'), p('Project export/import preserves editable design artifacts. Deployment export packages an executable application; these are different workflows. Installed samples open as editable project copies. Samples marked connection setup need your own provider configuration and credentials.'), p('Themes include Plain Classic and Plain Studio with light/dark variants. Layout panes can be shown or hidden from menus. The status/footer area exposes background work and execution state.')])]);
const dynamicNote = type => ({sap:'SAP IDoc listener/parser schemas change with selected IDoc metadata and JSON/XML output mode. Repeating segment fields follow the fetched schema. No live ECC schema is embedded in this generic guide.',jdbc:'Prepared SQL parameters and fetched output column metadata add typed fields to these base contracts. Dynamic SQL needs matching parameter names and values at runtime.',snowflake:'Entity/table metadata adds actual input record and result row columns.',xml:'The selected XSD or inline schema determines actual parse output or render input.',json:'The selected JSON schema determines actual parse output or render input.',flat:'The record schema determines child fields under records.',start:'The Task input schema replaces the generic payload boundary when configured.',end:'The Task output schema determines the result mapping.',call_task:'The selected Sub Task Start and End schemas replace generic payload/result fields.',mapper:'The selected target schema and mapping rules determine actual output fields.',transform:'The selected schema and transformation mapping determine the actual fields.'}[type] || 'The table is the base editor contract. Runtime values depend on mapped inputs, selected operation and provider response.');
let activityCount = 0;
for (const pack of defs.packs) for (const entry of pack.items) {
 const node = { type: entry.type, config: { operation: entry.operation || '' } };
 let contract = defs.activityContract(node);
 if (!contract || !Array.isArray(contract.configuration)) throw new Error(`Missing activity contract: ${entry.type}/${entry.operation}`);
 const doc = defs.activityDocumentation[entry.type];
 const advanced = defs.advancedDefaults(entry.type, entry.operation);
 const detail = connectorDetails(entry.type, entry.operation, contract);
 if (['kafka','sap','ems'].includes(entry.type) && !detail) throw new Error(`Missing detailed activity guide: ${entry.type}/${entry.operation}`);
 if (detail) contract={...contract,configuration:detail.configuration,input:detail.input,output:detail.output};
 const mappedInputs=defs.runtimeMappableInputs(node,contract).map(f=>detail?{...f,help:connectorFieldHelp(f)}:f);
 add(`activity-${slug(entry.type)}-${slug(entry.operation || 'default')}`, entry.label, `Activities / ${pack.name}`, [
  section('Overview', [p(doc?.summary || `Runs ${entry.label} on the task execution path.`), ...(doc ? [p(doc.behavior)] : []), p(`Activity type: ${entry.type}; operation: ${entry.operation || 'default'}.`)]),
  section('Configuration', [p('Display name identifies this activity and its data references. Configuration supplies operation settings and shared-resource selection. The table lists the editor contract; additional connection requirements are documented under Shared connections.'), fields(contract.configuration)]),
  section('Input', [p('Map fields using the Data tree, functions, constants or environment properties. The table includes configuration values exposed as runtime mapping targets by Studio.'), p(dynamicNote(entry.type)), fields(mappedInputs)]),
  section('Output', [p(dynamicNote(entry.type)), fields(contract.output)]),
  section('Advanced', [fields(Object.entries(advanced).map(([key, defaultValue]) => ({key, label:key, type:key==='logPayload'||key==='retryEnabled'?'boolean expression':'number expression', defaultValue, help:key==='logPayload'?'Controls automatic payload logging; browse to choose another environment property. Avoid logging sensitive data.':'Outbound retry policy resolved from the active environment. Retries may repeat external side effects; design for idempotency.'}))), p(defs.supportsOutboundRetry(entry.type,entry.operation) ? 'Outbound retry is available for this operation. Coordinate it with any Repeat-on-Error group to avoid multiplying attempts.' : 'This operation does not expose outbound retry in the common Advanced settings.')]),
  section('Errors', [table(['Fault', 'Description'], contract.errors.map(e=>[e.type,e.description])), ...errorPolicy]),
 ], {type:entry.type,operation:entry.operation || 'default',source:'frontend/src/ActivityEditor.tsx'});
 if(detail){
  const page=pages.at(-1);
  page.detailLevel='operational';
  page.source='frontend/src/ActivityEditor.tsx; backend/app/runtime.py; backend/app/sap.py; backend/app/java_bridge.py; frontend/scripts/connector-documentation.mjs';
  for(const section of page.sections) section.blocks=[...detail.sections[section.title],...section.blocks];
 }
 activityCount++;
}
const groupDefs = [
 ['if','If','Evaluates condition before entry; false skips the group.',['condition']],
 ['while','While True','Evaluates condition before each iteration, including the first.',['condition','maxIterations','indexVariable']],
 ['for_each','For Each','Resolves the collection at entry and runs once per item. Range mode uses inclusive start/end with a nonzero increment.',['iterationMode','source','start','end','increment','currentElementName','itemVariable','indexVariable','maxIterations','accumulateOutput','accumulatorVariable']],
 ['iterate','Iterate','Resolves source once at entry and iterates its elements.',['source','currentElementName','itemVariable','indexVariable','maxIterations','accumulateOutput','accumulatorVariable']],
 ['repeat','Repeat Until True','Runs once, checks condition at exit and repeats until true.',['condition','maxIterations','indexVariable']],
 ['repeat_on_error','Repeat on Error Until True','Retries the whole group after an unhandled fault while stopCondition is false. A true stop condition or exhausted retry count propagates the fault.',['stopCondition','retryCount','retryIntervalSeconds','indexVariable']],
 ['scope','Scope','Runs the enclosed graph once. Nested groups retain their own semantics.',[]],
 ['none','None','Runs the enclosed graph once; this is an execution boundary, not a separate transaction.',[]],
 ['critical_section','Critical Section','Holds a runtime-local named lock until completion, failure or cancellation. This is not a distributed lock across machines or separate runtime processes.',['lockName']],
 ['transaction_jdbc','JDBC Transaction','Uses one database connection for matching JDBC operations, commits on successful exit and rolls back on an escaping fault or cancellation. External non-JDBC side effects are not rolled back.',['resourceId']],
 ['pick_first','Pick First','Chooses the first eligible transition in graph order. This is first-match routing, not concurrent event racing or fastest-response selection.',[]],
];
for (const [type,title,behavior,keys] of groupDefs) add(`group-${slug(type)}`,title,'Groups',[
 section('Configuration',[p(behavior),p('Set Group name, Parent group and direct activity membership. A member has one direct owner; use parent_group_id for nesting. Normal groups require a connected single-entry, single-exit graph. Pick First has specialized branch selection.'),fields(keys.map(key=>({key,label:key,type:'expression / setting',defaultValue:defs.groupConfigDefaults(type)[key],help:'See the group behavior and Data-driven values below. Only fields applicable to the selected mode are displayed.'})))]),
 section('Input',[p('Conditions, collections, limits and retry intervals accept mapped earlier output, initial task input, properties, functions or constants. While/Repeat can inspect prior-iteration output. An initial condition cannot depend on output that has never executed.'),code(type==='repeat_on_error'?'${context.error}\n${properties.advanced.retryCount}\n${properties.advanced.retryIntervalSeconds}':type==='for_each'||type==='iterate'?'${input.records}\n${vars.currentElement}\n${vars.currentIndex}':'${input.enabled} == true')]),
 section('Output',[p(['for_each','iterate'].includes(type)?'The configured current element and one-based index are visible inside the group. Optional accumulation records each successful group-exit result under accumulatorVariable.':'Member activities publish their normal outputs. Groups do not have a separate universal output schema.')]),
 section('Advanced',[p('Iteration limits and retry counts provide runaway protection. Enclosing retry policies can repeat external writes. Debug uses the group scheduler and exposes group iteration context; task archives preserve membership and nesting.')]),
 section('Errors',[p('Missing members, cyclic parents, invalid expressions and invalid boundaries fail validation. Starter/event, End and Catch are task boundaries, not ordinary direct members. Parallel fan-out in non-Pick-First groups remains explicitly restricted. Escaping exceptions unwind group resources before propagating to task or caller handlers.')]),
],{source:'backend/app/runtime.py; frontend/src/main.tsx'});
for(const fn of mapperFunctionCatalog) add(`function-${slug(fn.name)}`,fn.name,`Functions / ${fn.category}`,[section('Overview',[p(fn.description)]),section('Signature',[code(fn.signature)]),section('Input / example',[p('Insertion template: replace $value and other placeholders with data expressions or typed constants for your mapping context.'),code(fn.template)]),section('Output',[p(fn.description)]),section('Errors and usage',[p('Use Map & Test with representative values. Invalid types, missing arguments or malformed patterns can fail evaluation. Optional arguments use the function implementation defaults; the signature is the authoritative editor insertion guide.')])],{source:'frontend/src/mapper-functions.ts'});
for(const [type, values] of Object.entries(defs.connectionFieldSets)) {
 const defaults = defs.connectionDefaults(type);
 add(`connection-${slug(type)}`,`${type.toUpperCase()} shared connection`,'Shared connections',[section('Configuration',[p('Create a shared resource in the project Resources tree, select it on activities, and use Test connection after resolving the active environment properties. Generated IDs are managed by Studio. Conditional fields below are shown only when their mode applies.'), fields(values.map(f=>({...f,defaultValue:defaults[f.key]})))]),section('Properties and credentials',[p('Browse an environment property to bind a field; inspect the resolved value in Studio. Provide real credentials locally or through deployment secrets; never put secrets in documentation, source control or AI prompts. A password-style field is a UI indication, not a guarantee that all exports are redacted.')]),section('Testing and prerequisites',[p('A connection test checks connectivity, not full application behavior, permissions for every operation, throughput or failover. Java-based connectors require their licensed driver JARs and bridge; SAP also requires a matching platform-native library. See Vendor Drivers and the connector guides.'),p(type==='ems'||type==='jms'?'Direct connections use JMS URL, username and password. JNDI settings become required only when JNDI is enabled. Optional connection IDs are generated by the implementation.':type==='pubsub'?'Service Account JSON supplies Google authentication. Verify project/topic/subscription access and IAM permissions on the target environment.':'Authentication and mandatory fields depend on the selected provider/mode; validate in Studio and on the target runtime.')])],{source:'frontend/src/main.tsx'});
}
add('environment-properties','Environment property defaults','Shared connections',[section('Defaults',[p('These are checked-in Studio defaults, not values read from any user project. Override per environment. Password properties need secure deployment handling.'),fields(defs.defaultProperties.map(x=>({key:x.key,label:x.key,type:x.data_type,defaultValue:x.data_type==='password'?'[supply securely]':x.value,help:x.description||''})))])]);
// Restricted Markdown-to-block parser; raw HTML stays plain text (no scripts).
function markdown(text) {
 const lines=text.split(/\r?\n/), blocks=[]; let pending=[];
 const flush=()=>{if(pending.length) blocks.push(p(pending.join(' ')));pending=[];};
 for(let i=0;i<lines.length;i++){
  const line=lines[i];
  if(line.startsWith('```')){flush();let content=[];while(++i<lines.length&&!lines[i].startsWith('```'))content.push(lines[i]);blocks.push(code(content.join('\n')));}
  else if(/^#{1,6} /.test(line)){flush();blocks.push({kind:'heading',text:line.replace(/^#+ /,'')});}
  else if(/^\s*[-*] |^\d+\. /.test(line)){flush();blocks.push({kind:'list',text:line.replace(/^\s*(?:[-*]|\d+\.) /,'')});}
  else if(line.trim().startsWith('|')){flush();const rows=[];while(i<lines.length&&lines[i].trim().startsWith('|')){const cells=lines[i].trim().replace(/^\||\|$/g,'').split('|').map(v=>v.trim());if(!cells.every(v=>/^:?-+:?$/.test(v)))rows.push(cells);i++;}i--;if(rows.length)blocks.push(table(rows[0],rows.slice(1)));}
  else if(!line.trim()){flush();}else pending.push(line.trim());
 }
 flush(); return blocks;
}
for(const [category,file] of guides){const text=sources.get(`docs/${file}`);add(`guide-${slug(file.replace(/\.md$/,''))}`,text.match(/^# (.+)$/m)?.[1]||file,category,[section('Guide',markdown(text))],{source:`docs/${file}`});}
const unique=new Set();for(const page of pages){if(unique.has(page.id))throw new Error(`Duplicate documentation ID: ${page.id}`);unique.add(page.id);}
const version=JSON.parse(sources.get('frontend/package.json')).version;
const model={version,fingerprint,counts:{activities:activityCount,groups:groupDefs.length,functions:mapperFunctionCatalog.length,connections:Object.keys(defs.connectionFieldSets).length,pages:pages.length},pages};
await fs.mkdir(out,{recursive:true});
await fs.writeFile(path.join(out,'documentation-data.json'),JSON.stringify(model,null,2)+'\n');
await fs.writeFile(path.join(out,'documentation-data.js'),`window.MINA_DOCUMENTATION=${JSON.stringify(model).replace(/</g,'\\u003c')};\n`);
const python=process.env.MINA_DOCS_PYTHON || 'python';
const result=spawnSync(python,[path.join(root,'scripts/build-documentation-pdf.py'),path.join(out,'documentation-data.json'),path.join(out,'MINA-Documentation.pdf')],{stdio:'inherit'});
if(result.error||result.status!==0)throw new Error('PDF generation failed. Set MINA_DOCS_PYTHON to a Python environment with scripts/documentation-requirements.txt installed. '+(result.error||''));
const files={};for(const file of ['documentation-data.json','documentation-data.js','MINA-Documentation.pdf']) files[file]=sha(await fs.readFile(path.join(out,file)));
await fs.writeFile(path.join(out,'documentation-build.json'),JSON.stringify({fingerprint,files,counts:model.counts},null,2)+'\n');
console.log(JSON.stringify(model.counts));
