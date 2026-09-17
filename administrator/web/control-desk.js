// Operator workspace layered on the existing, API-backed Control Plane actions.
const desk = {query:'', state:'ALL', plane:'ALL', section:'deployments', selected:null, tab:'overview', serial:0};
const deskId = value => encodeURIComponent(value);
const deskValue = value => value == null || value === '' ? '—' : String(value);
const deskTime = value => value ? fmt(value) : 'No report yet';
const deskEmpty = (title, detail) => `<div class="desk-empty"><span>◇</span><b>${esc(title)}</b><p>${esc(detail)}</p></div>`;
const deskIcon = stateName => ({RUNNING:'●', FAILED:'!', STOPPED:'■', DEPLOYED:'◌', UNDEPLOYED:'—'})[stateName] || '◌';

function deskNavigate(view) {
  const target = q(`#nav [data-view="${view}"]`);
  if (target) target.click();
}

function renderControlDeskHome() {
  const active = state.deployments.filter(item => item.state !== 'UNDEPLOYED');
  const running = active.filter(item => item.state === 'RUNNING');
  const failed = active.filter(item => item.state === 'FAILED' || item.health?.status === 'UNHEALTHY');
  const online = state.dataPlanes.filter(item => item.status === 'ONLINE');
  setStats([
    metric(`${running.length}/${active.length}`, 'APPLICATIONS RUNNING', `${failed.length} need attention`),
    metric(`${online.length}/${state.dataPlanes.length}`, 'DATA PLANES ONLINE'),
    metric(state.capabilities.filter(item => item.health === 'RUNNING').length, 'HEALTHY CAPABILITIES'),
    metric(`${state.observability.summary?.errorRate ?? 0}%`, 'CONTROL PLANE ERROR RATE'),
  ]);
  q('#pageActions').innerHTML = '<button data-desk-nav="applications" class="primary">Open application workspace</button>';
  q('#pageActions [data-desk-nav]').onclick = () => deskNavigate('applications');
  const attention = [...failed, ...active.filter(item => item.state === 'STOPPED')].slice(0, 8);
  const fleet = state.dataPlanes.map(item => {
    const system = item.telemetry?.system || item;
    return `<button class="desk-fleet-item" data-desk-plane="${esc(item.id)}"><span class="desk-status-dot ${esc((item.status||'unknown').toLowerCase())}"></span><span><b>${esc(item.name)}</b><small>${esc(item.type)} · ${esc(item.region||'local')}</small></span>${status(item.status)}<em>CPU ${esc(deskValue(system.cpuPercent))}% · RAM ${esc(deskValue(system.memoryPercent))}%</em></button>`;
  }).join('') || deskEmpty('No data planes', 'Register a data plane to connect the first runtime.');
  const issues = attention.map(item => `<button class="desk-issue" data-desk-deployment="${esc(item.id)}"><span class="desk-status-dot ${esc(item.state.toLowerCase())}"></span><span><b>${esc(item.application)}</b><small>${esc(item.environment)} · ${esc(planeName(item.dataPlaneId||item.machine))}</small></span>${status(item.health?.status === 'UNHEALTHY' ? 'UNHEALTHY' : item.state)}</button>`).join('') || '<div class="desk-positive">All visible applications are free of failed or stopped states.</div>';
  const recent = (state.overview?.recentActivity || []).slice(0, 8).map(item => `<div class="desk-event"><i></i><span><b>${esc(item.action)}</b><small>${esc(item.target)} · ${esc(item.detail||'')}</small></span><time>${deskTime(item.time)}</time></div>`).join('') || deskEmpty('No recent operations', 'Provisioning and lifecycle actions will appear here.');
  q('#content').innerHTML = `<div class="desk-home-banner"><div><small>OPERATIONS CENTER</small><h2>Run your integration estate from one place.</h2><p>Live status from the Control Plane and its data-plane agents. Select an application to inspect, configure, or operate it.</p></div><div class="desk-home-actions"><button class="primary" data-desk-nav="applications">Manage applications →</button><button data-desk-nav="observability">Explore telemetry</button></div></div><div class="desk-home-grid"><section class="desk-surface"><div class="desk-surface-head"><div><small>FLEET</small><h3>Connected data planes</h3></div><button data-desk-nav="dataPlanes">View all →</button></div>${fleet}</section><section class="desk-surface"><div class="desk-surface-head"><div><small>PRIORITY</small><h3>Needs attention</h3></div><button data-desk-nav="applications">Applications →</button></div>${issues}</section><section class="desk-surface desk-span"><div class="desk-surface-head"><div><small>ACTIVITY</small><h3>Recent operations</h3></div><button data-desk-nav="audit">Audit trail →</button></div>${recent}</section></div>`;
}

function deskFilter(items) {
  const query = desk.query.toLowerCase();
  return items.filter(item => {
    if (desk.section === 'deployments' && desk.state !== 'ALL' && item.state !== desk.state) return false;
    if (desk.section === 'deployments' && desk.plane !== 'ALL' && (item.dataPlaneId || item.machine) !== desk.plane) return false;
    return !query || [item.application, item.applicationName, item.packageId, item.environment, item.namespace, item.target, item.state, teamName(item.teamId), planeName(item.dataPlaneId||item.machine)].join(' ').toLowerCase().includes(query);
  });
}

function deskDeploymentRow(item) {
  const selected = item.id === desk.selected;
  const count = (item.instances||[]).filter(instance => instance.state === 'RUNNING').length;
  return `<button class="desk-deployment ${selected?'selected':''}" data-desk-deployment="${esc(item.id)}" aria-selected="${selected}"><span class="desk-app-avatar">${esc((item.application||'A').slice(0, 2).toUpperCase())}</span><span class="desk-app-name"><b>${esc(item.application)}</b><small>${esc(item.packageId)} · ${esc(teamName(item.teamId))}</small></span><span class="desk-app-location"><b>${esc(item.environment||'—')}</b><small>${esc(planeName(item.dataPlaneId||item.machine))} / ${esc(item.namespace||'default')}</small></span><span class="desk-app-runtime"><b>${count}/${esc(item.desiredInstances||1)}</b><small>instances</small></span><span class="desk-app-state">${status(item.state)}<small>${esc(item.health?.status||'Awaiting health')}</small></span><span class="desk-row-arrow">→</span></button>`;
}

function deskPackageRow(item) {
  return `<div class="desk-package"><span class="desk-package-icon">▣</span><span><b>${esc(item.applicationName)}</b><small>${esc(item.packageId)} · ${esc(item.target)} · ${esc(teamName(item.teamId))}</small></span><span>${status(item.status)}</span><span class="desk-package-env">${(item.environments||[]).map(env=>`<em>${esc(env)}</em>`).join('')}</span><span class="desk-package-actions"><button data-desk-package="inspect" data-package="${esc(item.packageId)}" data-team="${esc(item.teamId)}">Inspect</button><button class="primary" data-desk-package="deploy" data-package="${esc(item.packageId)}" data-team="${esc(item.teamId)}">Deploy</button></span></div>`;
}

function renderControlDeskApps() {
  const deployments = deskFilter(state.deployments);
  const packages = deskFilter(state.applications);
  const active = state.deployments.filter(item => item.state !== 'UNDEPLOYED');
  setStats([
    metric(state.applications.length, 'ARCHIVES'),
    metric(active.length, 'ACTIVE DEPLOYMENTS'),
    metric(active.filter(item=>item.state==='RUNNING').length, 'RUNNING'),
    metric(active.filter(item=>item.state==='FAILED').length, 'FAILED'),
  ]);
  q('#pageActions').innerHTML = '<button id="deskRefresh">Refresh</button><button class="primary" id="deskUpload">Upload package</button>';
  q('#deskRefresh').onclick = () => load();
  q('#deskUpload').onclick = () => q('#packageFile').click();
  q('#content').innerHTML = `<div class="desk-workspace"><div class="desk-workspace-main"><div class="desk-toolbar"><div class="desk-switch"><button data-desk-section="deployments" class="${desk.section==='deployments'?'active':''}">Deployments <span>${state.deployments.length}</span></button><button data-desk-section="packages" class="${desk.section==='packages'?'active':''}">Packages <span>${state.applications.length}</span></button></div><span class="desk-live"><i></i> Control Plane connected</span></div><div class="desk-filters"><label class="desk-search">⌕ <input id="deskSearch" type="search" placeholder="Search name, environment, team, package…" value="${esc(desk.query)}" autocomplete="off"></label><select id="deskState" aria-label="Filter by status"><option value="ALL">All states</option>${['RUNNING','DEPLOYED','STOPPED','FAILED','UNDEPLOYED'].map(value=>`<option value="${value}" ${desk.state===value?'selected':''}>${value}</option>`).join('')}</select><select id="deskPlane" aria-label="Filter by data plane"><option value="ALL">All data planes</option>${state.dataPlanes.map(value=>`<option value="${esc(value.id)}" ${desk.plane===value.id?'selected':''}>${esc(value.name)}</option>`).join('')}</select><span>${desk.section==='deployments'?deployments.length:packages.length} shown</span></div><div class="desk-list">${desk.section==='deployments'?(deployments.map(deskDeploymentRow).join('')||deskEmpty('No deployments match', 'Change the filters, or deploy an uploaded package.')):(packages.map(deskPackageRow).join('')||deskEmpty('No packages match', 'Upload an application archive to start a deployment.'))}</div></div><div id="deskInspector" class="desk-inspector">${desk.selected&&desk.section==='deployments'?'<div class="desk-loading">Loading application…</div>':deskEmpty('Select an application', 'Its configuration, starters, logs, revisions, and health will appear here.')}</div></div>`;
  q('#deskSearch').oninput = event => {desk.query=event.target.value;deskRenderList()};
  q('#deskState').disabled = desk.section === 'packages';
  q('#deskPlane').disabled = desk.section === 'packages';
  q('#deskState').onchange = event => {desk.state=event.target.value;deskRenderList()};
  q('#deskPlane').onchange = event => {desk.plane=event.target.value;deskRenderList()};
  if (desk.selected && desk.section === 'deployments') deskInspect(desk.selected);
}

function deskRenderList() {
  const items = deskFilter(desk.section === 'deployments' ? state.deployments : state.applications);
  q('.desk-filters > span').textContent = `${items.length} shown`;
  q('.desk-list').innerHTML = items.map(desk.section === 'deployments' ? deskDeploymentRow : deskPackageRow).join('') || deskEmpty('No matches', 'Try a different search or filter.');
}

function deskInspectorBody(item, extra) {
  const tabs = [['overview','Overview'],['configuration','Configuration'],['starters','Starter tasks'],['logs','Logs'],['revisions','History']];
  const pkg = state.applications.find(value => value.packageId === item.packageId && value.teamId === item.teamId);
  const starters = pkg?.starterTaskIds || [];
  let body = '';
  if (desk.tab === 'overview') {
    const health = extra.health || item.health || {};
    body = `<div class="desk-health-banner"><span class="desk-health-symbol ${esc((health.status||'unknown').toLowerCase())}">${deskIcon(item.state)}</span><span><small>APPLICATION HEALTH</small><b>${esc(health.status||'Awaiting report')}</b><em>${esc(health.message||item.message||'No health report yet')}</em></span></div><div class="desk-detail-grid"><div><small>Environment</small><b>${esc(item.environment)}</b></div><div><small>Data plane</small><b>${esc(planeName(item.dataPlaneId||item.machine))}</b></div><div><small>Namespace</small><b>${esc(item.namespace||'default')}</b></div><div><small>Instances</small><b>${(item.instances||[]).length} / ${esc(item.desiredInstances||1)}</b></div><div><small>Package</small><b>${esc(item.packageId)}</b></div><div><small>Last change</small><b>${deskTime(item.updatedAt)}</b></div></div><h4>Runtime instances</h4>${(item.instances||[]).map(instance=>`<div class="desk-instance"><span class="desk-status-dot ${esc((instance.state||'unknown').toLowerCase())}"></span><b>${esc(instance.id)}</b>${status(instance.state)}<small>${esc(instance.pid||'Remote')}</small></div>`).join('')||deskEmpty('No instances reported', 'Start the deployment or wait for the data-plane agent.')}${item.lastError?`<div class="desk-alert">${esc(item.lastError)}</div>`:''}`;
    body += '<h4>Administration tools</h4><div class="desk-tool-grid"><button data-desk-tool="compare">Compare configuration</button><button data-desk-tool="backup">Download backup</button><button data-desk-tool="restore">Restore backup</button><button data-desk-tool="actions">More actions</button></div>';
  } else if (desk.tab === 'configuration') {
    const choices = pkg?.environments || [item.environment];
    body = `<p class="desk-help">Changes are validated by the Control Plane. Secret values are write-only.</p><label>Environment<select id="deskConfigEnvironment">${choices.map(env=>`<option value="${esc(env)}" ${item.environment===env?'selected':''}>${esc(env)}</option>`).join('')}</select></label><label>Desired instances<input id="deskConfigInstances" type="number" min="1" max="100" value="${esc(item.desiredInstances||1)}"></label><label class="desk-check"><input id="deskConfigHealth" type="checkbox" ${item.healthCheckEnabled!==false?'checked':''}> Enable health checks</label><label>Update secrets (JSON object; leave empty to keep current values)<textarea id="deskConfigSecrets" rows="4" placeholder='{"KEY":"new value"}'></textarea></label><div class="desk-secret-list"><small>REQUIRED SECRETS</small>${(item.secrets||[]).map(secret=>`<span>${esc(secret.name)} ${status(secret.configured?'CONFIGURED':'MISSING')}</span>`).join('')||'<em>No required secrets</em>'}</div><div class="desk-form-actions"><button data-desk-config="save">Save</button><button class="primary" data-desk-config="redeploy">Save & redeploy</button></div>`;
  } else if (desk.tab === 'starters') {
    body = `<p class="desk-help">Start or stop an event source independently while the application remains deployed.</p>${starters.map(id=>{const task=(pkg?.taskInventory||[]).find(value=>value.id===id);const running=(item.starterStates||{})[id]!=='STOPPED';return `<div class="desk-starter"><span><b>${esc(task?.name||id)}</b><small>${esc(id)}</small></span>${status(running?'STARTED':'STOPPED')}<button data-desk-starter="${running?'stop':'start'}" data-task="${esc(id)}">${running?'Stop':'Start'}</button></div>`}).join('')||deskEmpty('No starters listed', 'The uploaded package did not include starter-task metadata.')}`;
  } else if (desk.tab === 'logs') {
    body = `<div class="desk-inline-tools"><span>Recent runtime output</span><button data-desk-refresh-tab>Refresh logs</button></div>${(extra.logs||[]).map(log=>`<section class="desk-log"><b>${esc(log.instanceId||'runtime')}</b><pre>${esc((log.lines||[]).join('\n')||'No log lines reported.')}</pre></section>`).join('')||deskEmpty('No runtime logs reported', 'Local logs appear after an instance starts. Remote agents must report logs to the Control Plane.')}`;
  } else {
    body = `<p class="desk-help">Configuration and lifecycle changes recorded by the Control Plane.</p>${(extra.revisions||[]).map(revision=>`<div class="desk-revision"><span><b>Revision ${esc(revision.revision)}</b><small>${esc(revision.action)} · ${deskTime(revision.time)}</small></span><button data-desk-revert="${esc(revision.revision)}">Revert</button></div>`).join('')||deskEmpty('No revisions yet', 'Changes will be recorded here.')}`;
  }
  return `<div class="desk-inspector-head"><small>APPLICATION / ${esc(item.environment||'')}</small><button class="desk-close" data-desk-close aria-label="Close inspector">×</button><h2>${esc(item.application)}</h2><p>${esc(item.packageId)} · ${esc(teamName(item.teamId))}</p><div class="desk-inspector-status">${status(item.state)} ${status(item.health?.status||'PENDING')}</div></div><div class="desk-command-bar">${item.state==='RUNNING'?'<button data-desk-action="stop">■ Stop</button>':item.state==='UNDEPLOYED'?'':'<button class="primary" data-desk-action="start">▶ Start</button>'}${item.state==='RUNNING'?'<button data-desk-action="restart">↻ Restart</button>':''}${item.state!=='UNDEPLOYED'?'<button class="danger" data-desk-action="undeploy">Undeploy</button>':'<button class="danger" data-desk-delete>Delete record</button>'}</div><div class="desk-inspector-tabs">${tabs.map(([id,title])=>`<button data-desk-tab="${id}" class="${desk.tab===id?'active':''}">${title}</button>`).join('')}</div><div class="desk-inspector-content">${body}</div>`;
}

async function deskInspect(id) {
  desk.selected = id;
  const serial = ++desk.serial;
  const target = q('#deskInspector');
  if (!target) return;
  target.innerHTML = '<div class="desk-loading">Loading application…</div>';
  try {
    const item = await api(`/api/deployments/${deskId(id)}`);
    const extra = {};
    if (desk.tab === 'overview') extra.health = await api(`/api/deployments/${deskId(id)}/health`);
    if (desk.tab === 'logs') extra.logs = await api(`/api/deployments/${deskId(id)}/logs?lines=400`);
    if (desk.tab === 'revisions') extra.revisions = await api(`/api/revisions/deployment/${deskId(id)}`);
    if (serial !== desk.serial || desk.selected !== id || state.view !== 'applications') return;
    target.innerHTML = deskInspectorBody(item, extra);
    deskRenderList();
  } catch (error) {
    if (serial === desk.serial) target.innerHTML = `<div class="desk-alert">${esc(error.message)}</div>`;
  }
}

async function deskSaveConfig(redeploy) {
  const id = desk.selected;
  try {
    const raw = q('#deskConfigSecrets').value.trim();
    const secrets = raw ? JSON.parse(raw) : {};
    if (!secrets || Array.isArray(secrets) || typeof secrets !== 'object') throw Error('Secrets must be a JSON object');
    await api(`/api/deployments/${deskId(id)}/configuration`, {method:'PUT', headers:{'content-type':'application/json'}, body:JSON.stringify({environment:q('#deskConfigEnvironment').value,instances:Number(q('#deskConfigInstances').value),healthCheckEnabled:q('#deskConfigHealth').checked,secrets,redeploy})});
    toast(redeploy?'Configuration saved and redeploy requested':'Configuration saved');
    await load();
  } catch (error) {toast(error.message,true)}
}

async function deskStarter(action, task) {
  try {
    await api(`/api/deployments/${deskId(desk.selected)}/starters/${deskId(task)}/${action}`, {method:'POST'});
    toast(`Starter ${action} requested`);
    await load();
  } catch (error) {toast(error.message,true)}
}

async function deskDelete() {
  if (!desk.selected || !confirm('Permanently delete this undeployed application record?')) return;
  try {
    await api(`/api/deployments/${deskId(desk.selected)}`, {method:'DELETE'});
    desk.selected = null;
    toast('Deployment record deleted');
    await load();
  } catch (error) {toast(error.message,true)}
}

function deskSparkline(samples, field) {
  const values = samples.map(sample=>sample[field]).filter(value=>Number.isFinite(Number(value)));
  if (!values.length) return '<span class="desk-no-history">Awaiting samples</span>';
  const points = values.map((value,index)=>`${Math.round(index*100/Math.max(values.length-1,1))},${Math.round(35-Number(value)*.3)}`).join(' ');
  return `<svg viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label="${esc(field)} trend"><polyline points="${points}"/></svg>`;
}

async function deskCreateAlert() {
  try {
    const type = q('#deskAlertType').value;
    const payload = {name:q('#deskAlertName').value.trim()||type, type, threshold:Number(q('#deskAlertThreshold').value), metric:q('#deskAlertMetric').value, dataPlaneId:q('#deskAlertPlane').value};
    await api('/api/alerts', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
    toast('Alert rule created');
    renderControlDeskTelemetry();
  } catch (error) {toast(error.message,true)}
}

async function deskDeleteAlert(id) {
  if (!confirm('Delete this alert rule?')) return;
  try {await api(`/api/alerts/${deskId(id)}`, {method:'DELETE'});toast('Alert rule deleted');renderControlDeskTelemetry()}
  catch (error) {toast(error.message,true)}
}

async function renderControlDeskTelemetry() {
  const token = ++desk.serial;
  const o = state.observability || {}, summary = o.summary || {};
  setStats([metric(summary.runningInstances||0,'RUNNING INSTANCES'),metric(summary.deployments||0,'DEPLOYMENTS'),metric(summary.requestCount||0,'API REQUESTS'),metric(`${summary.errorRate||0}%`,'REQUEST ERROR RATE')]);
  q('#pageActions').innerHTML = '<button id="deskTelemetryRefresh">Refresh telemetry</button>';
  q('#deskTelemetryRefresh').onclick = () => load();
  q('#content').innerHTML = '<div class="desk-loading">Loading agent telemetry…</div>';
  try {
    const [history, metrics, alerts] = await Promise.all([api('/api/operator/telemetry-history?limit=120'), api('/api/operator/metrics'), api('/api/alerts')]);
    if (token !== desk.serial || state.view !== 'observability') return;
    const hosts = (o.dataPlanes||[]).map(plane=>{
      const system = plane.telemetry?.system || plane, samples = history[plane.id] || [];
      return `<article class="desk-host"><div class="desk-host-title"><span><small>DATA PLANE</small><b>${esc(plane.name)}</b></span>${status(plane.status)}</div><p>${esc(plane.id)} · heartbeat ${deskTime(plane.lastHeartbeat)}</p><div class="desk-host-metrics">${[['cpuPercent','CPU'],['memoryPercent','Memory'],['diskPercent','Disk']].map(([field,label])=>`<div><small>${label}</small><b>${esc(deskValue(system[field]))}${system[field]==null?'':'%'}</b>${deskSparkline(samples,field)}</div>`).join('')}</div><button data-desk-plane="${esc(plane.id)}">Inspect data plane →</button></article>`;
    }).join('') || deskEmpty('No agent telemetry', 'Connect a data-plane agent to populate host metrics.');
    const taskRows = (metrics.tasks||[]).map(item=>`<div class="desk-exec-row"><span><b>${esc(item.name)}</b><small>${esc(item.total)} executions</small></span><div class="desk-mini-bar"><i style="width:${item.total?Math.round(Number(item.completed||0)/Number(item.total)*100):0}%"></i></div><em>${esc(item.failed||0)} failed</em></div>`).join('') || deskEmpty('No execution events', 'Task telemetry appears after agents report execution outcomes.');
    const errors = (o.requests?.recentErrors||[]).slice().reverse().slice(0,12).map(error=>`<div class="desk-event"><i class="error"></i><span><b>${esc(error.method)} ${esc(error.path)}</b><small>HTTP ${esc(error.status)}</small></span><time>${deskTime(error.time)}</time></div>`).join('') || '<div class="desk-positive">No failed Control Plane requests in this process.</div>';
    const rules = alerts.map(alert=>`<div class="desk-alert-rule"><span><b>${esc(alert.name)}</b><small>${esc(alert.type)}${alert.metric?` · ${esc(alert.metric)}`:''}${alert.dataPlaneId?` · ${esc(planeName(alert.dataPlaneId))}`:''}</small></span><span>${status(alert.state)}<small>${alert.value==null?'No data':`${esc(alert.value)} / ${esc(alert.threshold)}`}</small></span><button data-desk-delete-alert="${esc(alert.id)}" aria-label="Delete ${esc(alert.name)}">×</button></div>`).join('') || deskEmpty('No alert rules', 'Add a rule to watch deployments or host resources.');
    q('#content').innerHTML = `<div class="desk-telemetry-head"><div><small>LIVE SIGNALS</small><h2>Runtime and platform telemetry</h2><p>Agent-reported host metrics, task execution counts, and Control Plane request failures. Missing signals are shown as unavailable.</p></div><span>Updated ${deskTime(o.time)}</span></div><div class="desk-host-grid">${hosts}</div><div class="desk-home-grid"><section class="desk-surface"><div class="desk-surface-head"><div><small>EXECUTION</small><h3>Task outcomes</h3></div></div>${taskRows}</section><section class="desk-surface"><div class="desk-surface-head"><div><small>REQUESTS</small><h3>Recent errors</h3></div></div>${errors}</section><section class="desk-surface desk-span"><div class="desk-surface-head"><div><small>ALERTING</small><h3>Operational alert rules</h3></div></div><div class="desk-alert-grid"><div>${rules}</div><div class="desk-alert-form"><h4>Create alert rule</h4><input id="deskAlertName" placeholder="Rule name" aria-label="Alert rule name"><select id="deskAlertType" aria-label="Alert type"><option value="failed-deployment">Failed deployments</option><option value="offline-data-plane">Offline data planes</option><option value="unhealthy-application">Unhealthy applications</option><option value="resource-threshold">Host resource threshold</option></select><select id="deskAlertMetric" aria-label="Resource metric"><option value="cpuPercent">CPU %</option><option value="memoryPercent">Memory %</option><option value="diskPercent">Disk %</option></select><select id="deskAlertPlane" aria-label="Data plane"><option value="">All data planes</option>${state.dataPlanes.map(plane=>`<option value="${esc(plane.id)}">${esc(plane.name)}</option>`).join('')}</select><input id="deskAlertThreshold" type="number" min="1" max="100" value="1" aria-label="Alert threshold"><button class="primary" data-desk-create-alert>Create rule</button><p>Resource rules evaluate the highest reported value; missing telemetry remains NO DATA.</p></div></div></section></div>`;
  } catch (error) {q('#content').innerHTML = `<div class="desk-alert">${esc(error.message)}</div>`}
}

q('#content').addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.deskNav) return deskNavigate(button.dataset.deskNav);
  if (button.dataset.deskPlane) return dataPlaneDetails(button.dataset.deskPlane);
  if (button.dataset.deskSection) {desk.section=button.dataset.deskSection;return renderControlDeskApps()}
  if (button.dataset.deskDeployment) {desk.tab='overview';return deskInspect(button.dataset.deskDeployment)}
  if (button.dataset.deskPackage) return button.dataset.deskPackage==='deploy'?openDeploy(button.dataset.package,button.dataset.team):packageDetails(button.dataset.package,button.dataset.team);
  if (button.hasAttribute('data-desk-close')) {desk.selected=null;desk.serial++;q('#deskInspector').innerHTML=deskEmpty('Select an application','Inspect and operate a deployment here.');return deskRenderList()}
  if (button.dataset.deskTab) {desk.tab=button.dataset.deskTab;return deskInspect(desk.selected)}
  if (button.dataset.deskAction) return lifecycle(desk.selected,button.dataset.deskAction);
  if (button.dataset.deskConfig) return deskSaveConfig(button.dataset.deskConfig==='redeploy');
  if (button.dataset.deskStarter) return deskStarter(button.dataset.deskStarter,button.dataset.task);
  if (button.hasAttribute('data-desk-refresh-tab')) return deskInspect(desk.selected);
  if (button.hasAttribute('data-desk-delete')) return deskDelete();
  if (button.dataset.deskTool) {
    if (button.dataset.deskTool === 'compare') return compareDeployment(desk.selected);
    if (button.dataset.deskTool === 'backup') return downloadBackup(desk.selected);
    if (button.dataset.deskTool === 'restore') return restoreBackup(desk.selected);
    return applicationActions(desk.selected);
  }
  if (button.dataset.deskRevert) return revertDeployment(desk.selected,button.dataset.deskRevert);
  if (button.hasAttribute('data-desk-create-alert')) return deskCreateAlert();
  if (button.dataset.deskDeleteAlert) return deskDeleteAlert(button.dataset.deskDeleteAlert);
});

renderHome = renderControlDeskHome;
renderApplications = renderControlDeskApps;
renderObservability = renderControlDeskTelemetry;
