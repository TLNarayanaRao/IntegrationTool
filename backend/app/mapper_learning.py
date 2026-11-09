"""Explicitly shared, schema-scoped Smart Mapper path preferences."""
import hashlib
import json
import sqlite3
from contextlib import closing

from .mapper import flatten_schema
from .store import DATA_DIR


def _schema_paths(schema):
    paths = {item['path']: (item['type'], bool(item.get('repeating')), bool(item.get('required')),
                           item.get('repeatPath', '')) for item in flatten_schema(schema)}
    fingerprint = hashlib.sha256(json.dumps(paths, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return paths, fingerprint


def shared_paths(source_schema, target_schema, mappings=None):
    database = DATA_DIR / 'mapper-learning.sqlite3'
    if mappings is None and not database.exists():
        return {}
    sources, source_key = _schema_paths(source_schema)
    targets, target_key = _schema_paths(target_schema)
    rows = {}
    if mappings is not None:
        if not isinstance(mappings, list) or len(mappings) > 10000:
            raise ValueError('Supply up to 10000 reviewed mappings')
        for rule in mappings:
            if not isinstance(rule, dict) or rule.get('pending') or rule.get('enabled') is False:
                continue
            if any(rule.get(key) for key in ('operator', 'condition', 'select', 'functions', 'whens', 'otherwise')) or 'constant' in rule:
                continue
            source, target = rule.get('source'), rule.get('target')
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            if source.startswith('${') and source.endswith('}'):
                source = source[2:-1]
            if (source in sources and target in targets and sources[source][:2] == targets[target][:2]
                    and sources[source][0] not in ('object', 'complex', 'array', 'any')):
                rows[target] = source
        if not rows:
            return 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS shared_paths (
            source_schema TEXT, target_schema TEXT, target TEXT, source TEXT,
            PRIMARY KEY (source_schema, target_schema, target)
        )''')
        if mappings is None:
            return dict(connection.execute('SELECT target, source FROM shared_paths WHERE source_schema=? AND target_schema=?',
                                           (source_key, target_key)))
        connection.executemany('''INSERT INTO shared_paths VALUES (?, ?, ?, ?)
            ON CONFLICT(source_schema, target_schema, target) DO UPDATE SET source=excluded.source''',
                               ((source_key, target_key, target, source) for target, source in rows.items()))
        return len(rows)
