"""Bounded execution telemetry for interactive debug sessions."""
from collections import deque
from datetime import datetime, timezone
from threading import get_native_id
from time import perf_counter


class DebugTrace:
    terminal_threads = frozenset(('completed', 'failed', 'stopped', 'skipped'))

    def __init__(self, limit: int, capture: bool):
        self.capture = capture
        self.events = deque(maxlen=limit)
        self.recent_edges = deque(maxlen=200)
        self.threads = {}
        self.open_threads = set()
        self.closed_threads = {}
        self.thread_limit = min(limit, 500)
        self.thread_count = self.sequence = self.job = 0
        self.stats = {}
        self.stats_limit = 1000
        self.omitted_samples = 0
        self.jobs = dict(started=0, completed=0, failed=0, stopped=0)
        self.counts = dict(completed=0, failed=0, mocked=0, received=0)
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.origin = perf_counter()
        self.active_since = None
        self.active_seconds = 0.0
        self.job_started_at = 0.0
        self.first_job_at = self.last_job_finished_at = None
        self.last_job_ms = self.max_job_ms = 0.0
        self.activity_ms = 0.0

    def resume(self):
        if self.active_since is None:
            self.active_since = perf_counter()

    def suspend(self):
        if self.active_since is not None:
            self.active_seconds += perf_counter() - self.active_since
            self.active_since = None

    def open_job(self, frame, task):
        self.jobs['started'] += 1
        self.job = self.jobs['started']
        if self.first_job_at is None:
            self.first_job_at = perf_counter()
        self.job_started_at = self.active_seconds
        self.recent_edges.clear()
        frame['threadId'] = self.new_thread('job', task, frame['activityId'])

    def finish_job(self, status):
        self.suspend()
        if not self.job:
            return
        self.jobs[status] += 1
        self.last_job_finished_at = perf_counter()
        self.last_job_ms = (self.active_seconds - self.job_started_at) * 1000
        self.max_job_ms = max(self.max_job_ms, self.last_job_ms)
        self.close_threads(status)
        self.job = 0

    def new_thread(self, kind, task, entry, parent=None):
        if not self.capture:
            return None
        self.thread_count += 1
        ident = self.thread_count
        self.threads[ident] = {'id': ident, 'parentId': parent, 'job': self.job, 'kind': kind,
                               'taskId': task.id, 'taskName': task.name, 'entryActivityId': entry,
                               'status': 'queued', 'steps': 0}
        self.open_threads.add(ident)
        if len(self.threads) > self.thread_limit:
            oldest = next(iter(self.closed_threads or self.threads))
            del self.threads[oldest]
            self.open_threads.discard(oldest)
            self.closed_threads.pop(oldest, None)
        return ident

    def set_thread(self, ident, status):
        if ident in self.threads:
            self.threads[ident]['status'] = status
            if status in self.terminal_threads:
                self.open_threads.discard(ident)
                self.closed_threads[ident] = None

    def close_threads(self, status):
        for ident in sorted(self.open_threads):
            thread = self.threads[ident]
            self.set_thread(ident, 'skipped' if thread['status'] == 'queued' and status == 'failed' else status)

    def event(self, frame, kind, **details):
        if not self.capture:
            return
        self.sequence += 1
        event = {'sequence': self.sequence, 'job': self.job, 'threadId': frame.get('threadId'), 'taskId': frame['taskId'],
                 'kind': kind, 'elapsedMs': round((perf_counter() - self.origin) * 1000, 3),
                 'workerThreadId': get_native_id(), **details}
        groups = frame.get('context', {}).get('groupStack')
        if groups:
            event['groups'] = [{'id': group['id'], 'iteration': group.get('iteration', 0) + 1} for group in groups]
        self.events.append(event)

    def edge(self, frame, edge):
        if self.capture:
            self.recent_edges.append((frame['taskId'], edge.id))
        self.event(frame, 'transition', activityId=edge.source, targetActivityId=edge.target,
                   transitionId=edge.id, transitionType=edge.type, transitionLabel=edge.label or None)

    def activity(self, frame, activity, outcome, duration=0.0):
        self.counts[outcome] += 1
        self.activity_ms += duration
        identity = (frame['taskId'], activity.id)
        if identity not in self.stats and len(self.stats) >= self.stats_limit:
            self.omitted_samples += 1
        else:
            stats = self.stats.setdefault(identity, {'taskId': identity[0], 'activityId': identity[1],
                                                     'activityName': activity.name, 'count': 0, 'failures': 0,
                                                     'mocked': 0, 'received': 0, 'totalMs': 0.0, 'minMs': duration, 'maxMs': 0.0})
            stats['count'] += 1
            stats['failures'] += outcome == 'failed'
            stats['mocked'] += outcome == 'mocked'
            stats['received'] += outcome == 'received'
            stats['totalMs'] += duration
            stats['minMs'] = min(stats['minMs'], duration)
            stats['maxMs'] = max(stats['maxMs'], duration)
        thread = self.threads.get(frame.get('threadId'))
        if thread:
            thread['steps'] += 1
        self.event(frame, 'activity', activityId=activity.id, activityName=activity.name,
                   outcome=outcome, durationMs=round(duration, 3))

    def summary(self, detail=False):
        now = perf_counter()
        active = self.active_seconds + (now - self.active_since if self.active_since is not None else 0)
        window = ((now if self.job else self.last_job_finished_at) - self.first_job_at
                  if self.first_job_at is not None else 0)
        summary = {'startedAt': self.started_at, 'activeMs': round(active * 1000, 3),
                   'activityMs': round(self.activity_ms, 3), 'jobs': dict(self.jobs), 'activities': dict(self.counts),
                   'lastJobMs': round(self.last_job_ms, 3), 'maxJobMs': round(self.max_job_ms, 3),
                   'jobsPerSecond': round(self.jobs['completed'] / active, 3) if active > 0 else 0,
                   'wallWindowMs': round(window * 1000, 3),
                   'wallJobsPerSecond': round(self.jobs['completed'] / window, 3) if window > 0 else 0,
                   'activitiesPerSecond': round(sum(self.counts.values()) / active, 3) if active > 0 else 0,
                   'eventCount': self.sequence, 'capture': self.capture, 'threadCount': self.thread_count,
                   'droppedEvents': self.sequence - len(self.events), 'droppedThreads': self.thread_count - len(self.threads),
                   'omittedActivitySamples': self.omitted_samples}
        if detail:
            summary['byActivity'] = [
                {**stats, 'totalMs': round(stats['totalMs'], 3), 'minMs': round(stats['minMs'], 3), 'maxMs': round(stats['maxMs'], 3),
                 'avgMs': round(stats['totalMs'] / stats['count'], 3)}
                for stats in sorted(self.stats.values(), key=lambda item: item['totalMs'], reverse=True)]
        return summary

    def report(self, before=None, thread=None, limit=150, export=False):
        candidates = (event for event in reversed(self.events)
                      if (before is None or event['sequence'] < before)
                      and (thread is None or event['threadId'] == thread))
        events = list(self.events) if export else []
        older = None
        if not export:
            for event in candidates:
                if len(events) == limit:
                    older = events[-1]['sequence']
                    break
                events.append(event)
            events.reverse()
        return {'metrics': self.summary(detail=True), 'threads': list(reversed(self.threads.values())),
                'events': events, 'olderBefore': older}
