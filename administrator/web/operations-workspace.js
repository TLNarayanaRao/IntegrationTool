// Presentation preferences are local to this server/browser. Operations use the
// existing authenticated APIs; no credentials or telemetry are stored here.
function opsPreference(key, fallback) { try { return localStorage.getItem(`mina.ops.${key}`) || fallback; } catch { return fallback; } }
function opsSave(key, value) { try { localStorage.setItem(`mina.ops.${key}`,value); } catch { /* Private storage is optional. */ } }
function opsSavedStars() { try { const values=JSON.parse(opsPreference('stars','[]')); return new Set(Array.isArray(values)?values.filter(x=>typeof x==='string'):[]); } catch { return new Set(); } }
const ops={layout:opsPreference('layout','cards'),environment:'',team:'',attention:false,favorites:false,stars:opsSavedStars(),selected:new Set(),busy:false};
function opsCanManage(item) {
  const user=state.session?.identity || state.session || {};
  return user.teamId==='technology-team' || ((user.roles||[]).includes('Application Manager') && user.teamId===item.teamId);
}
function opsEligible(item, action) {
  return opsCanManage(item) && ({start:['DEPLOYED','STOPPED','FAILED'],stop:['RUNNING','DEPLOYED'],restart:['RUNNING']}[action]||[]).includes(item.state);
}
function opsItems() {
  return deskFilter(desk.section==='packages'?state.applications:state.deployments).filter(item=>
    (!ops.environment || (desk.section==='packages'?(item.environments||[]).includes(ops.environment):item.environment===ops.environment)) &&
    (!ops.team || item.teamId===ops.team) &&
    (!ops.attention || item.state==='FAILED' || ['UNHEALTHY','DEGRADED'].includes(item.health?.status)) &&
    (!ops.favorites || ops.stars.has(item.id)));
}
function opsCard(item) {
  const running=(item.instances||[]).filter(x=>x.state==='RUNNING').length;
  const checked=ops.selected.has(item.id), starred=ops.stars.has(item.id);
  return `<article class="ops-app-card ${desk.selected===item.id?'is-selected':''}"><div class="ops-card-top"><label><input type="checkbox" data-ops-select="${esc(item.id)}" ${checked?'checked':''} ${!opsCanManage(item)||ops.busy?'disabled':''} aria-label="Select ${esc(item.application)} for bulk actions"> Select</label><button data-ops-star="${esc(item.id)}" aria-pressed="${starred}" aria-label="Favorite ${esc(item.application)}">${starred?'★':'☆'}</button>${status(item.state)}</div><button class="ops-card-open" data-desk-deployment="${esc(item.id)}"><span class="ops-avatar">${esc((item.application||'A').slice(0,2).toUpperCase())}</span><strong>${esc(item.application)}</strong><small>${esc(item.packageId)}</small><span>${esc(item.environment)} · ${esc(teamName(item.teamId))}</span><small>${esc(planeName(item.dataPlaneId||item.machine))} / ${esc(item.namespace||'default')}</small></button><div class="ops-card-bottom"><span>${running}/${esc(item.desiredInstances||1)} running</span>${status(item.health?.status||'UNKNOWN')}<button data-desk-deployment="${esc(item.id)}" title="Configuration, starters, logs and history">Manage →</button></div></article>`;
}
function opsRenderList() {
  const list=q('.desk-list');if(!list)return;
  const active=document.activeElement;
  const focusSelect=active?.dataset?.opsSelect,focusStar=active?.dataset?.opsStar;
  const items=opsItems();
  // Never retain a bulk target hidden by a changed filter or removed deployment.
  const visible=new Set(items.map(x=>x.id));ops.selected=new Set([...ops.selected].filter(id=>visible.has(id)));
  const count=q('.desk-filters > span');if(count)count.textContent=`${items.length} shown`;
  list.className=`desk-list ops-layout-${desk.section==='packages'?'packages':ops.layout}`;
  if(desk.section==='packages')list.innerHTML=items.map(deskPackageRow).join('')||deskEmpty('No packages match','Change your search or filters.');
  else if(ops.layout==='board') {
    const groups=['RUNNING','DEPLOYED','STOPPED','FAILED','UNDEPLOYED'];
    const extra=[...new Set(items.map(x=>x.state))].filter(x=>!groups.includes(x));
    list.innerHTML=[...groups,...extra].map(name=>{const rows=items.filter(x=>x.state===name);return `<section class="ops-board-column"><h3>${esc(name)} <span>${rows.length}</span></h3>${rows.map(opsCard).join('')||'<p class="ops-empty-column">No applications</p>'}</section>`;}).join('');
  } else list.innerHTML=items.map(opsCard).join('')||deskEmpty('No applications match','Clear a filter or upload a package to get started.');
  const selected=q('#opsSelected');if(selected)selected.textContent=`${ops.selected.size} selected`;
  document.querySelectorAll('[data-ops-bulk]').forEach(button=>{button.disabled=ops.busy||!items.some(x=>ops.selected.has(x.id)&&opsEligible(x,button.dataset.opsBulk));});
  if(focusSelect||focusStar)Array.from(list.querySelectorAll('[data-ops-select],[data-ops-star]')).find(element=>focusSelect?element.dataset.opsSelect===focusSelect:element.dataset.opsStar===focusStar)?.focus({preventScroll:true});
}
function opsControls() {
  const packages=desk.section==='packages';
  const environments=[...new Set(state.deployments.map(x=>x.environment).concat(state.applications.flatMap(x=>x.environments||[])).filter(Boolean))].sort();
  return `<div class="ops-controls"><div class="ops-view-switch" role="group" aria-label="Application view">${['cards','list','board'].map(view=>`<button data-ops-layout="${view}" aria-pressed="${ops.layout===view}" ${packages?'disabled':''}>${view==='board'?'Status board':view==='cards'?'Cards':'Compact'}</button>`).join('')}</div><label>Environment<select id="opsEnvironment"><option value="">All environments</option>${environments.map(x=>`<option ${ops.environment===x?'selected':''}>${esc(x)}</option>`).join('')}</select></label><label>Team<select id="opsTeam"><option value="">All visible teams</option>${state.teams.map(x=>`<option value="${esc(x.id)}" ${ops.team===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label><label class="ops-check"><input id="opsAttention" type="checkbox" ${ops.attention?'checked':''} ${packages?'disabled':''}>Needs attention</label><label class="ops-check"><input id="opsFavorites" type="checkbox" ${ops.favorites?'checked':''} ${packages?'disabled':''}>Favorites</label><button data-ops-clear>Clear filters</button></div>${packages?'':`<div class="ops-bulk-bar"><button data-ops-select-visible>Select visible</button><button data-ops-clear-selection>Clear selection</button><b id="opsSelected">0 selected</b><button data-ops-bulk="start">▶ Start</button><button data-ops-bulk="stop">■ Stop</button><button data-ops-bulk="restart">↻ Restart</button><small>Actions require confirmation; server permissions apply.</small></div>`}`;
}
function opsConfirm(action, targets) {
  return new Promise(resolve=>{
    const modal=document.createElement('dialog');modal.className='ops-confirm';modal.setAttribute('aria-label','Confirm application operation');
    modal.innerHTML=`<form method="dialog"><h2>Confirm ${esc(action)}</h2><p>This changes ${targets.length} application deployment(s). ${action==='stop'||action==='restart'?'Processing may be interrupted.':''}</p><ul>${targets.map(x=>`<li><b>${esc(x.application)}</b> · ${esc(x.environment)} · ${esc(teamName(x.teamId))}<small>${esc(x.id)}</small></li>`).join('')}</ul><p>Only selected applications eligible for this action are included. Each deployment is checked again before execution.</p><div class="modal-actions"><button value="cancel" autofocus>Cancel</button><button class="primary" value="confirm">Confirm ${esc(action)}</button></div></form>`;
    modal.addEventListener('close',()=>{const accepted=modal.returnValue==='confirm';modal.remove();resolve(accepted);},{once:true});document.body.append(modal);modal.showModal();
  });
}
async function opsBulk(action) {
  if(ops.busy || !['start','stop','restart'].includes(action))return;
  const targets=opsItems().filter(x=>ops.selected.has(x.id)&&opsEligible(x,action));if(!targets.length)return;
  ops.busy=true;opsRenderList();
  try {
    if(!await opsConfirm(action,targets))return;
    const modal=document.createElement('dialog');modal.className='ops-results';modal.setAttribute('aria-label','Operation results');
    modal.innerHTML='<form method="dialog"><h2>Operation results</h2><p role="status" id="opsProgress">Working…</p><div id="opsResults"></div><p>Closing this window does not cancel requests already sent.</p><button>Close</button></form>';
    modal.addEventListener('close',()=>modal.remove(),{once:true});document.body.append(modal);modal.showModal();
    const rows=modal.querySelector('#opsResults'),progress=modal.querySelector('#opsProgress');let complete=0;
    for(const item of targets) {
      let message,ok=false;
      try {
        const latest=await api(`/api/deployments/${encodeURIComponent(item.id)}`);
        if(!opsEligible(latest,action))message='Skipped: state or permissions changed.';
        else {await api(`/api/deployments/${encodeURIComponent(item.id)}/${action}`,{method:'POST'});message='Request accepted. Verify status/health in the inspector.';ok=true;ops.selected.delete(item.id);}
      } catch(error) {message=`Failed: ${error.message}`;}
      const row=document.createElement('p');row.className=ok?'ops-success':'ops-warning';row.textContent=`${item.application} (${item.environment}): ${message}`;rows.append(row);progress.textContent=`${++complete} of ${targets.length} processed`;
    }
    await load();
  } finally {ops.busy=false;opsRenderList();}
}
function opsTheme(value) {
  if(!['ocean','slate','light','system'].includes(value))value='ocean';
  opsSave('theme',value);const effective=value==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'slate':'light'):value;
  document.documentElement.dataset.cpTheme=effective;
}
if(typeof document!=='undefined') {
  if(!['cards','list','board'].includes(ops.layout))ops.layout='cards';
  opsTheme(opsPreference('theme','ocean'));
  const themes=document.createElement('label');themes.className='ops-theme';themes.innerHTML='<span>Theme</span><select aria-label="Control Plane theme"><option value="ocean">Ocean dark</option><option value="slate">Slate dark</option><option value="light">Light</option><option value="system">System</option></select>';
  const select=themes.querySelector('select');select.value=opsPreference('theme','ocean');select.onchange=()=>opsTheme(select.value);document.querySelector('body>header').append(themes);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(opsPreference('theme','ocean')==='system')opsTheme('system');});
  const previousApps=renderApplications;
  renderApplications=function(){
    if(desk.section==='packages'){ops.attention=false;ops.favorites=false;ops.selected.clear();}
    previousApps();q('.desk-filters').insertAdjacentHTML('afterend',opsControls());
    for(const [id,key] of [['opsEnvironment','environment'],['opsTeam','team'],['opsAttention','attention'],['opsFavorites','favorites']])q('#'+id).onchange=event=>{ops[key]=event.target.type==='checkbox'?event.target.checked:event.target.value;opsRenderList();};
    opsRenderList();
  };
  // The existing Packages/Deployments toggle calls this global directly.
  renderControlDeskApps=renderApplications;deskRenderList=opsRenderList;
  q('#content').addEventListener('change',event=>{const id=event.target.dataset.opsSelect;if(id){event.target.checked?ops.selected.add(id):ops.selected.delete(id);opsRenderList();}});
  q('#content').addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.opsLayout){ops.layout=button.dataset.opsLayout;opsSave('layout',ops.layout);renderApplications();}
    if(button.dataset.opsStar){const id=button.dataset.opsStar;ops.stars.has(id)?ops.stars.delete(id):ops.stars.add(id);opsSave('stars',JSON.stringify([...ops.stars]));opsRenderList();}
    if(button.hasAttribute('data-ops-select-visible')){opsItems().filter(opsCanManage).forEach(x=>ops.selected.add(x.id));opsRenderList();}
    if(button.hasAttribute('data-ops-clear-selection')){ops.selected.clear();opsRenderList();}
    if(button.hasAttribute('data-ops-clear')){ops.environment='';ops.team='';ops.attention=false;ops.favorites=false;desk.query='';desk.state='ALL';desk.plane='ALL';renderApplications();}
    if(button.dataset.opsBulk)opsBulk(button.dataset.opsBulk).catch(error=>toast(error.message,true));
  });
  document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'&&!document.querySelector('dialog[open]')){event.preventDefault();deskNavigate('applications');q('#deskSearch')?.focus();}});
}
