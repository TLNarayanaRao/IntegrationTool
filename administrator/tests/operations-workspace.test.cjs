const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function context(){
  const state={session:{teamId:'delivery',roles:['Application Manager']},applications:[],deployments:[],teams:[]};
  const storage=new Map();
  const c=vm.createContext({state,desk:{section:'deployments'},deskFilter:x=>x,
    localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    esc:x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    teamName:x=>x,planeName:x=>x,status:x=>x});
  vm.runInContext(fs.readFileSync(__dirname+'/../web/operations-workspace.js','utf8'),c);return c;
}
test('bulk eligibility respects team, role and lifecycle state',()=>{
  const c=context();c.item={id:'a',teamId:'delivery',state:'STOPPED'};
  assert.equal(vm.runInContext("opsEligible(item,'start')",c),true);
  assert.equal(vm.runInContext("opsEligible(item,'stop')",c),false);
  c.item.teamId='other';assert.equal(vm.runInContext("opsEligible(item,'start')",c),false);
  c.state.session={teamId:'delivery',roles:['Viewer']};c.item.teamId='delivery';
  assert.equal(vm.runInContext('opsCanManage(item)',c),false);
  c.state.session={teamId:'technology-team',roles:[]};assert.equal(vm.runInContext('opsCanManage(item)',c),true);
});
test('environment, team, attention and favorite filters compose',()=>{
  const c=context();c.state.deployments=[{id:'a',teamId:'delivery',environment:'qa',state:'FAILED'},{id:'b',teamId:'other',environment:'prod',state:'RUNNING'}];
  vm.runInContext("ops.environment='qa';ops.team='delivery';ops.attention=true;ops.favorites=true;ops.stars.add('a')",c);
  assert.equal(vm.runInContext('opsItems().map(x=>x.id).join()',c),'a');
  vm.runInContext("ops.environment='prod'",c);assert.equal(vm.runInContext('opsItems().length',c),0);
});
test('package filters use environment profiles',()=>{
  const c=context();c.desk.section='packages';c.state.applications=[{id:'p',environments:['qa','prod']}];
  vm.runInContext("ops.environment='prod'",c);assert.equal(vm.runInContext('opsItems().length',c),1);
});
test('application card escapes untrusted names and identifiers',()=>{
  const c=context();c.item={id:'" onclick="bad',application:'<script>bad</script>',teamId:'other',state:'STOPPED'};
  const html=vm.runInContext('opsCard(item)',c);
  assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('disabled'));assert.ok(html.includes('&quot; onclick=&quot;bad'));
});
test('invalid or unavailable preferences are safe',()=>{
  const c=context();vm.runInContext("opsSave('stars','broken')",c);assert.equal(vm.runInContext('opsSavedStars().size',c),0);
  c.localStorage.getItem=()=>{throw Error('denied')};assert.equal(vm.runInContext("opsPreference('theme','ocean')",c),'ocean');
});
test('bulk cancel sends no requests and releases busy state',async()=>{
  const c=context();c.state.deployments=[{id:'a',teamId:'delivery',state:'STOPPED'}];
  vm.runInContext("ops.selected.add('a');opsRenderList=()=>{};opsConfirm=async()=>false",c);
  c.api=()=>{throw Error('Unexpected request')};
  await vm.runInContext("opsBulk('start')",c);assert.equal(vm.runInContext('ops.busy',c),false);
});
test('bulk checks fresh state, continues after errors, reports each target',async()=>{
  const c=context(),rows=[],calls=[];
  c.state.deployments=['a','b','c'].map(id=>({id,application:id,environment:'qa',teamId:'delivery',state:'STOPPED'}));
  vm.runInContext("ops.selected=new Set(['a','b','c']);opsRenderList=()=>{};opsConfirm=async()=>true",c);
  c.document={body:{append(){}},createElement:()=>({setAttribute(){},addEventListener(){},showModal(){},querySelector:s=>s==='#opsResults'?{append:r=>rows.push(r.textContent)}:{textContent:''}})};
  c.api=async(url,options)=>{calls.push(url);const id=url.split('/')[3];if(options&&id==='a')throw Error('unavailable');return {id,teamId:'delivery',state:id==='b'?'RUNNING':'STOPPED'};};
  c.load=async()=>{};
  await vm.runInContext("opsBulk('start')",c);
  assert.equal(calls.length,5);assert.match(rows[0],/Failed/);assert.match(rows[1],/Skipped/);assert.match(rows[2],/Request accepted/);
  assert.equal(vm.runInContext("ops.selected.has('c')",c),false);assert.equal(vm.runInContext('ops.busy',c),false);
});
