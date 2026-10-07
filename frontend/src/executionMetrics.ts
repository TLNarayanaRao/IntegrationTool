export type Timing = {activityId:string;taskId:string;name:string;type:string;durationMs:number;endedAt:string;status:string};
export function timingRecords(logs: any[]): Timing[] {
  return logs.filter(e => e.kind === 'activity' && (e.runtimeActivityId || e.activityId) && typeof e.durationMs === 'number' && Number.isFinite(e.durationMs) && e.durationMs >= 0).map(e => ({activityId:e.runtimeActivityId || e.activityId,taskId:e.taskId || '',name:e.activityName || e.runtimeActivityId || e.activityId,type:e.activityType || '',durationMs:e.durationMs,endedAt:e.time || '',status:e.level === 'ERROR' ? 'failed' : 'completed'}));
}
export function timingSummary(records: Timing[]) {
  const groups = new Map<string, Timing[]>();
  records.forEach(record => { const key = `${record.taskId}:${record.activityId}`; const values = groups.get(key) || []; values.push(record); groups.set(key, values); });
  return Array.from(groups.values()).map(values => {
    const durations = values.map(v => v.durationMs).sort((a,b) => a-b), total = durations.reduce((a,b) => a+b,0);
    return {...values[0],count:values.length,failures:values.filter(v => v.status === 'failed').length,total,mean:total/values.length,min:durations[0],max:durations[durations.length-1],p95:durations[Math.ceil(durations.length*.95)-1]};
  }).sort((a,b) => b.total-a.total);
}
export function analyticsCsv(rows: ReturnType<typeof timingSummary>) {
  const cell = (value: string | number) => `"${String(value).replace(/^\s*[=+@-]/, "'$&").replaceAll('"','""')}"`;
  return [['Task','Activity ID','Activity','Type','Invocations','Failures','Total ms','Mean ms','Min ms','Max ms','P95 ms'],...rows.map(row => [row.taskId,row.activityId,row.name,row.type,row.count,row.failures,row.total,row.mean,row.min,row.max,row.p95])].map(row => row.map(cell).join(',')).join('\r\n');
}
export function escapeReport(value: unknown) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!)); }
