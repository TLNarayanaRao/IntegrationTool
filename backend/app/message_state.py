"""Transactional SQLite or shared PostgreSQL state for mediation operations.

Claims use fencing tokens. This does not make external side effects exactly-once:
complete a claim only after downstream work and acknowledge the broker last.
"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def _encode(value):
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(body.encode()) > 1024 * 1024: raise ValueError('Durable message payload exceeds 1 MB')
    return body


_TABLES = (
    'CREATE TABLE IF NOT EXISTS messages (namespace TEXT, key TEXT, status TEXT, token TEXT, expires DOUBLE PRECISION, payload TEXT, error TEXT, updated DOUBLE PRECISION, PRIMARY KEY(namespace,key))',
    'CREATE TABLE IF NOT EXISTS aggregates (namespace TEXT, key TEXT, status TEXT, deadline DOUBLE PRECISION, expected INTEGER, max_items INTEGER, PRIMARY KEY(namespace,key))',
    'CREATE TABLE IF NOT EXISTS aggregate_items (namespace TEXT, key TEXT, message_id TEXT, payload TEXT, position INTEGER, PRIMARY KEY(namespace,key,message_id))',
    'CREATE INDEX IF NOT EXISTS message_status ON messages(namespace,status,updated)',
    'CREATE INDEX IF NOT EXISTS aggregate_order ON aggregate_items(namespace,key,position)',
)


class _PostgresState:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql.replace('?', '%s'), params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def _connection(config):
    backend = config.get('stateBackend') or 'sqlite'
    if backend == 'postgresql':
        dsn = os.environ.get('MINA_MESSAGE_STATE_POSTGRES_DSN')
        if not dsn:
            raise ValueError('Set MINA_MESSAGE_STATE_POSTGRES_DSN for shared message state')
        try:
            import psycopg
        except ImportError as exc:
            raise ValueError('Install psycopg[binary] to use shared message state') from exc
        return _PostgresState(psycopg.connect(dsn, connect_timeout=5, options='-c search_path=mina_message_state -c lock_timeout=10000 -c statement_timeout=15000')), True
    if backend != 'sqlite':
        raise ValueError('Message state backend must be sqlite or postgresql')
    default = Path(os.environ.get('MINA_DATA_DIR') or Path.home() / '.mina') / 'message-state.sqlite3'
    path = Path(config.get('stateFile') or os.environ.get('MINA_MESSAGE_STATE_FILE') or default).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute('PRAGMA busy_timeout=10000')
        for statement in _TABLES:
            db.execute(statement)
        db.commit()
    except BaseException:
        db.close()
        raise
    return db, False


class MessageStateException(ValueError):
    fault_type = 'MessageStateException'


def operate(operation, config, payload):
    try: return _operate(operation, config, payload)
    except (ValueError, sqlite3.Error, OSError) as cause:
        error = MessageStateException(str(cause))
        if operation == 'split_records': error.fault_type = 'InvalidInputException'
        raise error from cause
    except Exception as cause:
        if config.get('stateBackend') != 'postgresql' or cause.__class__.__module__.split('.')[0] != 'psycopg':
            raise
        raise MessageStateException('Shared message state is unavailable or busy') from None


def _operate(operation, config, payload):
    namespace = str(config.get('namespace') or 'default').strip()
    if not namespace or len(namespace) > 200: raise ValueError('A namespace of at most 200 characters is required')
    if operation == 'split_records':
        if not isinstance(payload, list): raise ValueError('Split Records requires an array')
        size = int(config.get('batchSize') or 100)
        if not 1 <= size <= 10000: raise ValueError('Batch size must be between 1 and 10000')
        return {'batches': [payload[index:index + size] for index in range(0, len(payload), size)], 'count': len(payload)}
    key = str(config.get('messageKey') or config.get('correlationKey') or '').strip()
    if operation != 'replay_messages' and (not key or len(key) > 512): raise ValueError('A message/correlation key of at most 512 characters is required')
    db, shared = _connection(config)
    try:
        if shared:
            # Serialize the state transition and capacity check across replicas.
            db.execute('SELECT pg_advisory_xact_lock(1296649793, 1)')
            db.execute('CREATE SCHEMA IF NOT EXISTS mina_message_state')
            for statement in _TABLES:
                db.execute(statement)
            now = db.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp())::double precision').fetchone()[0]
        else:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
        def capacity(body):
            maximum = int(config.get('maxStateSizeMb') or 256) * 1024 * 1024
            if shared:
                used = db.execute("SELECT (SELECT COALESCE(SUM(octet_length(payload) + octet_length(error) + 256),0) FROM messages) + (SELECT COALESCE(SUM(octet_length(payload) + 256),0) FROM aggregate_items) + (SELECT COUNT(*) * 256 FROM aggregates)").fetchone()[0]
            else:
                used = (db.execute('PRAGMA page_count').fetchone()[0] - db.execute('PRAGMA freelist_count').fetchone()[0]) * db.execute('PRAGMA page_size').fetchone()[0]
            if maximum < 1024 * 1024 or used + len(body.encode()) > maximum: raise ValueError('Durable message state capacity exceeded; purge expired completed records or increase the limit')
        if operation == 'deduplicate':
            lease = float(config.get('leaseSeconds') or 300)
            if not 1 <= lease <= 86400: raise ValueError('Lease must be between 1 and 86400 seconds')
            existing = db.execute('SELECT status,expires FROM messages WHERE namespace=? AND key=?', (namespace, key)).fetchone()
            # Failed claims require deliberate replay; completed keys stay fenced
            # until their configured retention expires.
            if existing and (existing[0] == 'failed' or existing[0] != 'ready' and existing[1] > now):
                result = {'accepted': False, 'duplicate': True, 'messageKey': key, 'status': existing[0]}
            else:
                token = str(uuid.uuid4())
                body = _encode(payload); capacity(body)
                db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET status=excluded.status,token=excluded.token,expires=excluded.expires,payload=excluded.payload,error=excluded.error,updated=excluded.updated', (namespace, key, 'processing', token, now + lease, body, '', now))
                result = {'accepted': True, 'duplicate': False, 'messageKey': key, 'claimToken': token, 'status': 'processing', 'payload': payload}
        elif operation == 'message_receipt':
            token = str(config.get('claimToken') or '')
            action = str(config.get('action') or 'complete')
            if action not in ('complete', 'fail'): raise ValueError('Receipt action must be complete or fail')
            existing = db.execute('SELECT token,status,expires FROM messages WHERE namespace=? AND key=?', (namespace, key)).fetchone()
            if not existing or not token or existing[0] != token or existing[1] != 'processing' or existing[2] <= now: raise ValueError('Claim token is missing, stale or expired')
            retention = float(config.get('retentionSeconds') or 604800)
            if retention < 1 or retention > 31536000: raise ValueError('Retention must be between 1 second and one year')
            status = 'completed' if action == 'complete' else 'failed'
            error = str(config.get('error') or '')[:4000]
            db.execute('UPDATE messages SET status=?,expires=?,error=?,updated=? WHERE namespace=? AND key=?', (status, now + retention, error, now, namespace, key))
            result = {'messageKey': key, 'status': status}
        elif operation == 'replay_messages':
            action = str(config.get('action') or 'list')
            if action not in ('list', 'requeue', 'requeue_one', 'purge'): raise ValueError('Replay action must be list, requeue or purge')
            purged = 0
            if action == 'purge':
                retention = float(config.get('retentionSeconds') or 604800)
                if retention < 1: raise ValueError('Retention must be positive')
                purged = db.execute("DELETE FROM messages WHERE namespace=? AND status='completed' AND expires<=?", (namespace, now)).rowcount
                expired = db.execute("SELECT key FROM aggregates WHERE namespace=? AND status='completed' AND deadline<=?", (namespace, now - retention)).fetchall()
                for (group_key,) in expired:
                    db.execute('DELETE FROM aggregate_items WHERE namespace=? AND key=?', (namespace, group_key))
                    db.execute('DELETE FROM aggregates WHERE namespace=? AND key=?', (namespace, group_key))
                purged += len(expired)
            if action in ('requeue', 'requeue_one'):
                if not key: raise ValueError('Requeue requires a message key')
                changed = db.execute("UPDATE messages SET status='ready',token='',expires=0,updated=? WHERE namespace=? AND key=? AND (status='failed' OR status='processing' AND expires<=?)", (now, namespace, key, now)).rowcount
                if not changed: raise ValueError('Only failed or expired processing messages can be requeued')
            limit = int(config.get('limit') or 100)
            if not 1 <= limit <= 500: raise ValueError('Replay limit must be between 1 and 500')
            metadata_only = config.get('metadataOnly') is True
            columns = 'key,status,NULL,NULL' if metadata_only else 'key,status,payload,error'
            if action == 'requeue_one':
                rows = db.execute(f"SELECT {columns} FROM messages WHERE namespace=? AND key=?", (namespace, key)).fetchall()
            else:
                rows = db.execute(f"SELECT {columns} FROM messages WHERE namespace=? AND (status IN ('failed','ready') OR status='processing' AND expires<=?) ORDER BY updated,key LIMIT ?", (namespace, now, limit)).fetchall()
            result = {'messages': [{'messageKey': row[0], 'status': row[1], **(
                {} if metadata_only else {'payload': json.loads(row[2]), 'error': row[3]}
            )} for row in rows], 'count': len(rows), 'purged': purged}
        elif operation == 'aggregate_messages':
            action = str(config.get('action') or 'append')
            if action not in ('append', 'flush'): raise ValueError('Aggregate action must be append or flush')
            expected = int(config.get('expectedCount') or 1)
            maximum = int(config.get('maxGroupItems') or 1000)
            timeout = float(config.get('timeoutSeconds') or 300)
            if not 1 <= expected <= maximum <= 10000 or not 1 <= timeout <= 86400: raise ValueError('Invalid aggregate count, capacity or timeout')
            group = db.execute('SELECT status,deadline,expected,max_items FROM aggregates WHERE namespace=? AND key=?', (namespace, key)).fetchone()
            if group is None:
                if action == 'flush': raise ValueError('No aggregate exists for this correlation key')
                capacity('{}')
                db.execute('INSERT INTO aggregates VALUES (?,?,?,?,?,?)', (namespace, key, 'pending', now + timeout, expected, maximum))
                group = ('pending', now + timeout, expected, maximum)
            status, deadline, stored_expected, stored_maximum = group
            timed_out = now >= deadline
            if expected != stored_expected or maximum != stored_maximum: raise ValueError('Aggregate completion settings changed within the same group')
            duplicate = False
            if action == 'append' and status == 'pending' and not timed_out:
                message_id = str(config.get('messageId') or '').strip()
                if not message_id or len(message_id) > 512: raise ValueError('Aggregate requires a stable message ID of at most 512 characters')
                count = db.execute('SELECT COUNT(*) FROM aggregate_items WHERE namespace=? AND key=?', (namespace, key)).fetchone()[0]
                duplicate = db.execute('SELECT 1 FROM aggregate_items WHERE namespace=? AND key=? AND message_id=?', (namespace, key, message_id)).fetchone() is not None
                if not duplicate:
                    if count >= stored_maximum: raise ValueError('Aggregate group capacity exceeded')
                    body = _encode(payload); capacity(body)
                    byte_length = 'octet_length(payload)' if shared else 'length(CAST(payload AS BLOB))'
                    group_bytes = db.execute(f'SELECT COALESCE(SUM({byte_length}),0) FROM aggregate_items WHERE namespace=? AND key=?', (namespace, key)).fetchone()[0]
                    if group_bytes + len(body.encode()) > 64 * 1024 * 1024: raise ValueError('Aggregate group exceeds 64 MB')
                    db.execute('INSERT INTO aggregate_items VALUES (?,?,?,?,?)', (namespace, key, message_id, body, count))
            count = db.execute('SELECT COUNT(*) FROM aggregate_items WHERE namespace=? AND key=?', (namespace, key)).fetchone()[0]
            ready = status == 'pending' and (count >= stored_expected or action == 'flush' and timed_out)
            # Partial timeout delivery is explicit; later duplicates do not emit again.
            records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM aggregate_items WHERE namespace=? AND key=? ORDER BY position', (namespace, key))] if ready else []
            if ready: db.execute("UPDATE aggregates SET status='completed' WHERE namespace=? AND key=?", (namespace, key))
            result = {'correlationKey': key, 'ready': ready, 'duplicate': duplicate, 'timedOut': timed_out, 'count': count, 'records': records, 'status': 'completed' if ready or status == 'completed' else 'timed_out' if timed_out else 'pending'}
        else: raise ValueError(f'Unsupported mediation operation {operation}')
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally: db.close()
