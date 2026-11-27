"""Bounded X12 and UN/EDIFACT envelope validation and rendering."""
from collections import Counter
import re

MAX_BYTES = 8 * 1024 * 1024
MAX_SEGMENTS = 50000
_X12_WIDTHS = (2, 10, 2, 10, 2, 15, 2, 15, 6, 4, 1, 5, 9, 1, 1, 1)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _delimiters(*values):
    _need(all(isinstance(value, str) and len(value) == 1 and 32 < ord(value) < 127
              and not value.isalnum() for value in values) and len(set(values)) == len(values),
          'EDI separators must be distinct ASCII punctuation')


def _split(text, separator, release='', maximum=4096):
    if not release:
        parts = text.split(separator, maximum)
        _need(len(parts) <= maximum, 'EDI delimiter count exceeds the limit')
        return parts
    parts, start, index = [], 0, 0
    while index < len(text):
        char = text[index]
        if char == release:
            _need(index + 1 < len(text), 'EDI release character has no following character')
            index += 2
            continue
        if char == separator:
            parts.append(text[start:index])
            _need(len(parts) < maximum, 'EDI delimiter count exceeds the limit')
            start = index + 1
        index += 1
    return [*parts, text[start:]]


def _count(expected, actual, label):
    _need(re.fullmatch(r'[0-9]{1,10}', expected) and int(expected) == actual,
          f'{label} segment count does not match its envelope')


def _match(expected, actual, label):
    _need(expected.strip() and expected == actual, f'{label} control reference does not match')


def _validate_segment_fields(segments, kind, rules):
    rule = rules.get(kind)
    if rule is None:
        return
    _need(isinstance(rule, dict), 'A transaction rule must be an object')
    required = rule.get('requiredSegments', [])
    _need(isinstance(required, list) and all(isinstance(tag, str) for tag in required),
          'requiredSegments must be an array of segment tags')
    counts = Counter(segment['tag'] for segment in segments)
    missing = [tag for tag in required if not counts[tag]]
    _need(not missing, f'{kind} missing required segments: {", ".join(missing)}')
    required_elements = rule.get('requiredElements', {})
    _need(isinstance(required_elements, dict), 'requiredElements must be an object keyed by segment tag')
    for tag, values in required_elements.items():
        _need(isinstance(values, list) and all(type(index) is int and 1 <= index <= 99 for index in values),
              f'{tag} element positions must be integers from 1 to 99')
        for segment in segments:
            if segment['tag'] == tag:
                _need(all(len(segment['elements']) >= index and segment['elements'][index - 1].strip()
                          for index in values), f'{kind} {tag} is missing a required element')


def parse(payload, expected_format='', rules=None, allowed_types=None):
    if isinstance(payload, bytes):
        payload = payload.decode('latin-1')
    _need(isinstance(payload, str) and 0 < len(payload) <= MAX_BYTES and
          all(ord(c) <= 255 and (ord(c) >= 32 or c in '\r\n') for c in payload),
          'EDI requires a nonempty interchange of up to 8 MiB using single-byte text')
    _need(rules is None or isinstance(rules, dict), 'Transaction rules must be a JSON object')
    rules = rules or {}
    if isinstance(allowed_types, str):
        allowed_types = [value.strip() for value in allowed_types.split(',') if value.strip()]
    _need(allowed_types is None or isinstance(allowed_types, list) and all(isinstance(t, str) for t in allowed_types),
          'Allowed transaction types must be a list or comma-separated text')
    text = payload.lstrip('\r\n')
    release, advice = '', ''
    if text.startswith('ISA'):
        kind = 'x12'
        _need(len(text) >= 106, 'X12 ISA header must be 106 bytes including its terminator')
        element, component, segment = text[3], text[104], text[105]
        _delimiters(element, component, segment)
        values = text[:105].split(element)[1:]
        _need(tuple(map(len, values)) == _X12_WIDTHS, 'X12 ISA element widths are invalid')
    else:
        kind = 'edifact'
        if text.startswith('UNA'):
            _need(len(text) >= 9, 'EDIFACT UNA must contain six service characters')
            advice, text = text[:9], text[9:].lstrip('\r\n')
            component, element, decimal, release, repeat, segment = advice[3:]
            _delimiters(component, element, release, segment, decimal, *([repeat] if repeat != ' ' else []))
        else:
            component, element, segment, release = ':', '+', "'", '?'
        _need(text.startswith('UNB' + element), 'Expected an X12 ISA or EDIFACT UNB interchange')
    _need(not expected_format or expected_format.lower() == kind, 'EDI format does not match the partner profile')
    raw = _split(text.rstrip('\r\n'), segment, release, MAX_SEGMENTS + 1)
    _need(raw[-1] == '' and 2 <= len(raw) <= MAX_SEGMENTS + 1, 'EDI terminator is missing or segment limit exceeded')
    segments = []
    for line in raw[:-1]:
        tag, *values = _split(line.lstrip('\r\n'), element, release)
        _need(re.fullmatch(r'[A-Z][A-Z0-9]{1,2}', tag), 'Invalid EDI segment tag')
        segments.append({'tag': tag, 'elements': values})
    interchange, interchange_end, group, group_end, txn, txn_end = (
        ('ISA', 'IEA', 'GS', 'GE', 'ST', 'SE') if kind == 'x12' else ('UNB', 'UNZ', 'UNG', 'UNE', 'UNH', 'UNT')
    )
    _need(segments[0]['tag'] == interchange and segments[-1]['tag'] == interchange_end, 'Expected one enclosed EDI interchange')
    header = segments[0]['elements']
    tail = segments[-1]['elements']
    _need(len(header) >= (16 if kind == 'x12' else 5) and len(tail) >= 2, 'Incomplete EDI interchange control segment')
    control = header[12 if kind == 'x12' else 4]
    _match(control, tail[1], interchange_end)
    group_id, start, group_count, group_txns = None, None, 0, 0
    transactions = []
    grouped = None
    controls = set()
    for index, row in enumerate(segments[1:-1], start=1):
        tag, values = row['tag'], row['elements']
        if tag == group:
            _need(grouped is not False and group_id is None and start is None and len(values) >= (6 if kind == 'x12' else 5),
                  'Invalid EDI functional group header')
            grouped, group_id, group_txns = True, values[5 if kind == 'x12' else 4], 0
        elif tag == group_end:
            _need(group_id is not None and start is None and len(values) >= 2 and group_txns > 0,
                  'Unexpected or empty EDI functional group trailer')
            _match(group_id, values[1], group_end)
            _count(values[0], group_txns, group_end)
            group_id, group_count = None, group_count + 1
        elif tag == txn:
            _need(start is None and len(values) >= 2 and
                  (group_id is not None or kind == 'edifact' and grouped is not True),
                  'Unexpected EDI transaction header')
            if grouped is None:
                grouped = False
            start = index
        elif tag == txn_end:
            _need(start is not None and len(values) >= 2, 'Unexpected EDI transaction trailer')
            transaction = segments[start:index + 1]
            beginning = transaction[0]['elements']
            ref = beginning[1 if kind == 'x12' else 0]
            transaction_type = beginning[0] if kind == 'x12' else _split(beginning[1], component, release)[0]
            _need(transaction_type.strip(), 'EDI transaction type is missing')
            _match(ref, values[1], txn_end)
            _count(values[0], len(transaction), txn_end)
            _need((group_count, ref) not in controls, 'Duplicate EDI transaction control reference')
            controls.add((group_count, ref))
            _need(not allowed_types or transaction_type in allowed_types, f'EDI transaction type {transaction_type} is not allowed')
            _validate_segment_fields(transaction, transaction_type, rules)
            transactions.append({'type': transaction_type, 'controlNumber': ref, 'groupControlNumber': group_id,
                                 'segmentCount': len(transaction)})
            start, group_txns = None, group_txns + 1
        else:
            _need(tag not in {interchange, interchange_end, 'UNA'} and start is not None,
                  f'Unexpected {tag} outside an EDI transaction')
    _need(group_id is None and start is None and transactions, 'Unclosed or empty EDI interchange')
    _count(tail[0], group_count if grouped else len(transactions), interchange_end)
    return {'format': kind, 'controlNumber': control, 'sender': header[5 if kind == 'x12' else 1].strip(),
            'receiver': header[7 if kind == 'x12' else 2].strip(), 'transactions': transactions, 'segments': segments,
            'separators': {'element': element, 'component': component, 'segment': segment, 'release': release},
            **({'serviceAdvice': advice} if advice else {})}


def render(document, rules=None, allowed_types=None):
    _need(isinstance(document, dict) and isinstance(document.get('segments'), list), 'Supply a parsed EDI segment structure')
    separators = document.get('separators') or {}
    element, segment = separators.get('element'), separators.get('segment')
    _delimiters(element, segment)
    release = separators.get('release', '')
    if release:
        _delimiters(element, segment, release)
    _need(0 < len(document['segments']) <= MAX_SEGMENTS, 'EDI segment limit exceeded')
    output = []
    length = 0
    for row in document['segments']:
        _need(isinstance(row, dict) and isinstance(row.get('tag'), str) and isinstance(row.get('elements'), list),
              'Each EDI segment requires a tag and an array of elements')
        for value in row['elements']:
            _need(isinstance(value, str) and len(_split(value, segment, release)) == 1
                  and len(_split(value, element, release)) == 1, 'EDI element contains an unescaped delimiter')
        line = element.join([row['tag'], *row['elements']]) + segment
        length += len(line)
        _need(length <= MAX_BYTES, 'Rendered interchange exceeds 8 MiB')
        output.append(line)
    text = (document.get('serviceAdvice') or '') + ''.join(output)
    control = parse(text, document.get('format', ''), rules, allowed_types)
    return {'text': text, **control}
