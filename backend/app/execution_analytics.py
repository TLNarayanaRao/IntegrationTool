"""Payload-free timing records for execution reports."""
from math import isfinite

PUBLISH_PHASES = {
    'queueMs': 'send queue', 'bridgeMs': 'Java bridge', 'sessionWaitMs': 'JMS session wait',
    'providerSendMs': 'broker send', 'enqueueMs': 'publisher enqueue', 'confirmationMs': 'confirmation wait',
    'totalMs': 'publisher total',
}


def publish_phases(value):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in PUBLISH_PHASES
            if isinstance(value.get(key), (int, float)) and not isinstance(value[key], bool)
            and isfinite(value[key]) and value[key] >= 0}


def activity_timings(logs):
    timings = []
    for entry in logs:
        identifier = entry.get('runtimeActivityId') or entry.get('activityId')
        duration = entry.get('durationMs')
        scope = entry.get('timingScope')
        is_timing = entry.get('kind') == 'activity' or (entry.get('kind') == 'event' and scope in ('idoc_intake', 'event_handoff'))
        if not is_timing or not identifier or not isinstance(duration, (int, float)) or isinstance(duration, bool) or not isfinite(duration) or duration < 0:
            continue
        phases = publish_phases(entry.get('publishTiming'))
        timings.append({
            'activityId': identifier, 'taskId': entry.get('taskId', ''),
            'name': entry.get('activityName') or identifier,
            'type': entry.get('activityType', ''), 'operation': entry.get('operation', ''),
            'durationMs': duration, 'endedAt': entry.get('time', ''),
            'status': 'failed' if entry.get('level') == 'ERROR' else 'completed',
            **({'publishTiming': phases} if phases else {}),
            **({'timingScope': scope} if scope in ('idoc_intake', 'event_handoff', 'call_setup') else {}),
        })
    return timings
