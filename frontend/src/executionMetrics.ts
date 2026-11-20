type TimingScope = 'idoc_intake' | 'event_handoff' | 'call_setup';
const publishPhases = {
  queueMs: 'Send queue', bridgeMs: 'Java bridge', sessionWaitMs: 'JMS session wait',
  providerSendMs: 'Broker send', enqueueMs: 'Publisher enqueue', confirmationMs: 'Confirmation wait',
} as const;
type PublishPhase = keyof typeof publishPhases;
export type Timing = {activityId:string;taskId:string;name:string;type:string;durationMs:number;endedAt:string;status:string;timingScope?:TimingScope;publishTiming?:Partial<Record<PublishPhase | 'totalMs', number>>};
export function timingRecords(logs: any[]): Timing[] {
  const records:Timing[] = [];
  for (const entry of logs) {
    const activityId = entry.runtimeActivityId || entry.activityId;
    const scope = entry.timingScope;
    const isTiming = entry.kind === 'activity' || (entry.kind === 'event' && (scope === 'idoc_intake' || scope === 'event_handoff'));
    const duration = entry.durationMs;
    if (!isTiming || !activityId || typeof duration !== 'number' || !Number.isFinite(duration) || duration < 0) continue;
    const publishTiming = Object.fromEntries([...Object.keys(publishPhases), 'totalMs']
      .map(key => [key, entry.publishTiming?.[key]])
      .filter(([, value]) => typeof value === 'number' && Number.isFinite(value) && value >= 0));
    records.push({
      activityId, taskId:entry.taskId || '', name:entry.activityName || activityId, type:entry.activityType || '',
      durationMs:duration, endedAt:entry.time || '', status:entry.level === 'ERROR' ? 'failed' : 'completed',
      ...(Object.keys(publishTiming).length ? {publishTiming} : {}),
      ...(scope === 'idoc_intake' || scope === 'event_handoff' || scope === 'call_setup' ? {timingScope:scope} : {}),
    });
  }
  return records;
}
export function publisherTimingSummary(records: Timing[]) {
  const groups = new Map<string, {taskId:string;name:string;phase:string;calls:number;total:number}>();
  for (const record of records) {
    if (!record.publishTiming) continue;
    for (const [key, phase] of Object.entries(publishPhases)) {
      const value = record.publishTiming[key as PublishPhase];
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) continue;
      const id = JSON.stringify([record.taskId, record.activityId, key]);
      const group = groups.get(id) ?? {taskId:record.taskId, name:record.name, phase, calls:0, total:0};
      group.calls++;
      group.total += value;
      groups.set(id, group);
    }
  }
  return Array.from(groups, ([id, group]) => ({id, ...group, mean:group.total / group.calls}));
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
