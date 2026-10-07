"""Payload-free timing records for execution reports."""
from math import isfinite

def activity_timings(logs):
    timings = []
    for entry in logs:
        identifier = entry.get('runtimeActivityId') or entry.get('activityId')
        duration = entry.get('durationMs')
        if entry.get('kind') != 'activity' or not identifier or not isinstance(duration, (int, float)) or isinstance(duration, bool) or not isfinite(duration) or duration < 0:
            continue
        timings.append({
            'activityId': identifier, 'taskId': entry.get('taskId', ''),
            'name': entry.get('activityName') or identifier,
            'type': entry.get('activityType', ''), 'operation': entry.get('operation', ''),
            'durationMs': duration, 'endedAt': entry.get('time', ''),
            'status': 'failed' if entry.get('level') == 'ERROR' else 'completed',
        })
    return timings
