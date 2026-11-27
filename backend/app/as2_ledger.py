"""AS2 reconciliation with local SQLite or shared PostgreSQL state."""
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


def _connect():
    default = Path(os.environ.get('MINA_DATA_DIR') or Path.home() / '.mina') / 'as2-ledger.sqlite3'
    path = Path(os.environ.get('MINA_AS2_LEDGER_FILE') or default)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, timeout=5)


def _tables(execute):
    execute('CREATE TABLE IF NOT EXISTS exchange (profile TEXT, direction TEXT, id TEXT, status TEXT, '
            'fingerprint TEXT, token TEXT, updated DOUBLE PRECISION, details TEXT, receipt TEXT, PRIMARY KEY(profile,direction,id))')
    execute('CREATE INDEX IF NOT EXISTS exchange_updated ON exchange(updated)')


@contextmanager
def _transaction(backend):
    if backend == 'sqlite':
        with closing(_connect()) as db, db:
            _tables(db.execute)
            db.execute('BEGIN IMMEDIATE')
            yield db.execute, time.time()
        return
    if backend != 'postgresql':
        raise ValueError('AS2 reconciliation backend must be sqlite or postgresql')
    dsn = os.environ.get('MINA_AS2_LEDGER_POSTGRES_DSN')
    if not dsn:
        raise ValueError('Set MINA_AS2_LEDGER_POSTGRES_DSN for shared AS2 reconciliation')
    try:
        import psycopg
    except ImportError as error:
        raise ValueError('Shared AS2 reconciliation requires psycopg[binary]') from error
    try:
        options = '-c search_path=mina_as2 -c statement_timeout=15000 -c lock_timeout=10000'
        with psycopg.connect(dsn, connect_timeout=5, options=options) as db:
            db.execute('SELECT pg_advisory_xact_lock(1296649793, 2)')
            db.execute('CREATE SCHEMA IF NOT EXISTS mina_as2')
            _tables(db.execute)
            def execute(query, values=()):
                return db.execute(query.replace('?', '%s'), values)
            now = db.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp())::double precision').fetchone()[0]
            yield execute, now
    except psycopg.Error:
        raise ValueError('Shared AS2 reconciliation database is unavailable or busy') from None


def record(profile, message_id, direction, action, *, backend='sqlite', entry=None, token='', receipt=None):
    """Atomically claim, settle, or reconcile an exchange or receipt delivery."""
    with _transaction(backend) as (execute, now):
        key = (profile, direction, message_id)
        execute('DELETE FROM exchange WHERE updated<?', (now - 90 * 86400,))
        row = execute('SELECT status,fingerprint,token,updated,details,receipt FROM exchange '
                      'WHERE profile=? AND direction=? AND id=?', key).fetchone()
        details = json.loads(row[4]) if row else {}
        stored_receipt = json.loads(row[5]) if row and row[5] else None
        where = 'WHERE profile=? AND direction=? AND id=?'
        if action == 'read':
            if row is None:
                return {'found': False, 'messageId': message_id, 'direction': direction}
            return {'found': True, 'messageId': message_id, 'direction': direction, 'status': row[0],
                    'updatedAt': row[3], 'controlNumber': details['controlNumber'], 'mic': details['mic'],
                    **{key: details[key] for key in ('receiptMode', 'callbackStatus', 'receiptMicVerified', 'errorCode') if key in details}}
        if action == 'claim':
            if row:
                if (direction == 'outbound' or row[1] != entry['fingerprint'] or
                        ('wireHeaders' in details and details['wireHeaders'] != entry.get('wireHeaders'))):
                    raise ValueError('AS2 Message-ID was already used for this partner and direction')
                if stored_receipt:
                    return {'duplicate': True, 'receipt': stored_receipt, 'receiptMode': details.get('receiptMode', 'synchronous'),
                            **({'status': 'rejected', 'errorCode': details['errorCode']} if details.get('errorCode') else {})}
                if now - row[3] < details.get('leaseSeconds', 300):
                    raise ValueError('AS2 delivery is already being processed')
            else:
                if execute('SELECT COUNT(*) FROM exchange').fetchone()[0] >= 100000:
                    raise ValueError('AS2 reconciliation ledger capacity exceeded')
            claim = uuid.uuid4().hex
            execute("INSERT INTO exchange VALUES (?,?,?,'processing',?,?,?,?,'') ON CONFLICT(profile,direction,id) "
                    "DO UPDATE SET token=excluded.token,updated=excluded.updated,details=excluded.details",
                    (*key, entry['fingerprint'], claim, now, json.dumps(entry)))
            return {'duplicate': False, 'claimToken': claim}
        if action == 'reconcile_mdn':
            if not row or direction != 'outbound' or details.get('receiptMode') != 'asynchronous':
                raise ValueError('No matching asynchronous outbound AS2 exchange')
            status = entry['status']
            if entry['mic'] != details['mic'] and (entry['mic'] is not None or status != 'rejected'):
                raise ValueError('AS2 MDN integrity check failed')
            if row[0] == status:
                return {'messageId': message_id, 'status': status, 'duplicate': True}
            if row[0] != 'awaiting_mdn':
                raise ValueError('AS2 receipt conflicts with the recorded disposition')
            details['receiptMicVerified'] = entry['mic'] is not None
            execute('UPDATE exchange SET status=?,updated=?,details=?,receipt=? ' + where,
                    (status, now, json.dumps(details), json.dumps(receipt), *key))
            return {'messageId': message_id, 'status': status, 'duplicate': False}
        if action in ('callback_claim', 'callback_sent', 'callback_pending'):
            if not row or direction != 'inbound' or details.get('receiptMode') != 'asynchronous' or not stored_receipt:
                raise ValueError('No signed asynchronous MDN is ready for delivery')
            if action == 'callback_claim':
                if details.get('callbackStatus') == 'sent':
                    return {'messageId': message_id, 'callbackStatus': 'sent', 'duplicate': True}
                if row[2] and now - row[3] < 300:
                    raise ValueError('AS2 MDN callback is already being delivered')
                claim, status = uuid.uuid4().hex, 'sending'
            else:
                if not token or token != row[2]:
                    raise ValueError('AS2 MDN delivery token is missing or stale')
                claim, status = '', action.removeprefix('callback_')
            details['callbackStatus'] = status
            execute('UPDATE exchange SET token=?,updated=?,details=? ' + where, (claim, now, json.dumps(details), *key))
            return {'messageId': message_id, 'callbackStatus': status, 'duplicate': False,
                    **({'claimToken': claim, 'receipt': stored_receipt, 'callbackUrl': details['callbackUrl']}
                       if action == 'callback_claim' else {})}
        if row is None or row[0] != 'processing' or not token or token != row[2] or (
                direction == 'inbound' and now - row[3] >= details.get('leaseSeconds', 300)):
            raise ValueError('AS2 receipt token is missing, stale, or expired')
        if action == 'details':
            return details
        if action not in {'processed', 'rejected', 'failed', 'awaiting_mdn'}:
            raise ValueError('Invalid AS2 receipt state')
        if receipt and direction == 'inbound' and details.get('receiptMode') == 'asynchronous':
            details['callbackStatus'] = 'pending'
        if receipt and direction == 'outbound' and entry and 'receiptMicVerified' in entry:
            details['receiptMicVerified'] = entry['receiptMicVerified']
        execute('UPDATE exchange SET status=?,token=?,updated=?,details=?,receipt=? ' + where,
                (action, '', now, json.dumps(details), json.dumps(receipt) if receipt else '', *key))
        return {'messageId': message_id, 'status': action}
