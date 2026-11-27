"""Generate and read X12 functional acknowledgements and EDIFACT CONTRL."""
from datetime import datetime, timezone
import re

from .edi import parse, render


def _required(ok, message):
    if not ok:
        raise ValueError(message)


def _validated(payload):
    return render(payload) if isinstance(payload, dict) else parse(payload)


def _segment(tag, *values):
    return {'tag': tag, 'elements': list(values)}


def _source_groups(document):
    x12 = document['format'] == 'x12'
    group_tag, begin_tag = ('GS', 'ST') if x12 else ('UNG', 'UNH')
    groups, group = [], {'header': None, 'messages': []}
    for segment in document['segments']:
        if segment['tag'] == group_tag:
            group = {'header': segment['elements'], 'messages': []}
            groups.append(group)
        elif segment['tag'] == begin_tag:
            group['messages'].append(segment['elements'])
    return groups or [group]


def _decisions(values):
    if values is None:
        return {}
    _required(isinstance(values, list) and len(values) <= 50000, 'Acknowledgement decisions must be an array')
    result = {}
    for value in values:
        _required(isinstance(value, dict) and isinstance(value.get('controlNumber'), str)
                  and type(value.get('accepted')) is bool, 'Decision requires a control number and boolean acceptance')
        key = (str(value.get('groupControlNumber') or ''), value['controlNumber'])
        _required(key not in result, 'Duplicate acknowledgement decision')
        result[key] = value
    return result


def _decision(decisions, group, control):
    return decisions.pop((group, control), {'accepted': True})


def _timestamp(config):
    raw = config.get('ackTimestamp')
    if not raw:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    _required(value.tzinfo is not None, 'Acknowledgement timestamp requires a time zone')
    return value.astimezone(timezone.utc)


def _x12(document, kind, config, decisions, timestamp):
    control = str(config.get('ackInterchangeControl') or '')
    group_start = str(config.get('ackGroupControl') or '')
    _required(re.fullmatch(r'[0-9]{9}', control), 'The X12 acknowledgement ISA control number requires nine digits')
    _required(re.fullmatch(r'[0-9]{1,9}', group_start) and int(group_start) > 0,
              'The X12 acknowledgement needs a new numeric GS control number')
    original = document['segments'][0]['elements']
    isa = original.copy()
    isa[4:8] = original[6:8] + original[4:6]
    isa[0:4] = ['00', ' ' * 10, '00', ' ' * 10]
    isa[8:10] = [timestamp.strftime('%y%m%d'), timestamp.strftime('%H%M')]
    isa[12:14] = [control, '0']
    implementation = str(config.get('ackImplementationVersion') or ('004010' if kind == '997' else '005010X231A1'))
    if kind == '999':
        _required(re.fullmatch(r'005010[A-Z0-9]{0,9}', implementation), 'The 999 implementation version must begin with 005010')
        isa[10:12] = [next(mark for mark in '^|!;%' if mark not in document['separators'].values()), '00501']
    else:
        _required(re.fullmatch(r'004010[A-Z0-9]{0,9}', implementation), 'The 997 implementation version must begin with 004010')
        isa[10:12] = ['U', '00401']
    rows = [_segment('ISA', *isa)]
    groups = _source_groups(document)
    for index, group in enumerate(groups):
        source = group['header']
        _required(source and len(source) >= 8, 'The source X12 GS header is incomplete')
        _required(int(group_start) + index <= 999999999, 'Acknowledgement group control exceeds nine digits')
        reference = str(int(group_start) + index).zfill(len(group_start))
        rows.append(_segment('GS', 'FA', source[2], source[1], timestamp.strftime('%Y%m%d'),
                             timestamp.strftime('%H%M'), reference, 'X', implementation))
        transaction = [_segment('ST', kind, '0001', implementation) if kind == '999' else _segment('ST', kind, '0001')]
        transaction.append(_segment('AK1', source[0], source[5], source[7]) if kind == '999'
                           else _segment('AK1', source[0], source[5]))
        accepted = 0
        for message in group['messages']:
            decision = _decision(decisions, source[5], message[1])
            response = 'A' if decision['accepted'] else 'R'
            accepted += int(decision['accepted'])
            transaction.append(_segment('AK2', *message[:3 if kind == '999' else 2]))
            transaction.append(_segment('IK5' if kind == '999' else 'AK5', response))
        size = len(group['messages'])
        outcome = 'A' if accepted == size else 'R' if accepted == 0 else 'P'
        transaction.append(_segment('AK9', outcome, str(size), str(size), str(accepted)))
        transaction.append(_segment('SE', str(len(transaction) + 1), '0001'))
        rows.extend(transaction)
        rows.append(_segment('GE', '1', reference))
    rows.append(_segment('IEA', str(len(groups)), control))
    return rows


def _contrl(document, config, decisions, timestamp):
    control = str(config.get('ackInterchangeControl') or '')
    reference = str(config.get('ackMessageControl') or '1')
    _required(re.fullmatch(r'[A-Za-z0-9]{1,14}', control) and re.fullmatch(r'[A-Za-z0-9]{1,14}', reference),
              'CONTRL interchange and message references require 1–14 letters or digits')
    original = document['segments'][0]['elements']
    component = document['separators']['component']
    syntax = original[0].split(component)[1:2]
    _required(syntax in (['3'], ['4']), 'CONTRL requires UN/EDIFACT syntax version 3 or 4')
    version = ['D', '3'] if syntax == ['3'] else ['4', '1']
    date = timestamp.strftime('%y%m%d' if syntax == ['3'] else '%Y%m%d')
    time = timestamp.strftime('%H%M')
    rows = [
        _segment('UNB', original[0], original[2], original[1], component.join([date, time]), control),
        _segment('UNH', reference, component.join(['CONTRL', *version, 'UN'])),
        _segment('UCI', original[4], original[1], original[2], '7'),
    ]
    for group in _source_groups(document):
        source = group['header']
        if source:
            rows.append(_segment('UCF', source[4], source[1], source[2], '7'))
        for message in group['messages']:
            decision = _decision(decisions, source[4] if source else '', message[0])
            if decision['accepted']:
                rows.append(_segment('UCM', message[0], message[1], '7'))
            else:
                code = str(decision.get('errorCode') or '')
                _required(re.fullmatch(r'[0-9]{1,3}', code), 'A rejected CONTRL message requires an EDIFACT syntax error code')
                rows.append(_segment('UCM', message[0], message[1], '4', code))
    rows.extend([_segment('UNT', str(len(rows)), reference), _segment('UNZ', '1', control)])
    return rows


def generate(payload, config):
    document = _validated(payload)
    _required(not any(item['type'] in ('997', '999', 'CONTRL') for item in document['transactions']),
              'An EDI acknowledgement cannot itself be functionally acknowledged')
    kind = str(config.get('ackType') or ('997' if document['format'] == 'x12' else 'CONTRL')).upper()
    _required((document['format'] == 'x12' and kind in ('997', '999')) or
              (document['format'] == 'edifact' and kind == 'CONTRL'), 'Acknowledgement type does not match the source interchange')
    decisions = _decisions(config.get('ackDecisions'))
    timestamp = _timestamp(config)
    rows = _contrl(document, config, decisions, timestamp) if kind == 'CONTRL' else _x12(document, kind, config, decisions, timestamp)
    _required(not decisions, 'Acknowledgement decisions refer to a transaction absent from the interchange')
    return {'ackType': kind, **render({**document, 'segments': rows})}


def read(payload):
    document = _validated(payload)
    kinds = {item['type'] for item in document['transactions']}
    _required(len(kinds) == 1 and kinds <= {'997', '999', 'CONTRL'}, 'Expected a 997, 999, or CONTRL interchange')
    kind = kinds.pop()
    groups, transactions, interchanges = [], [], []
    current_group, current_message = '', None
    for segment in document['segments']:
        tag, values = segment['tag'], segment['elements']
        _required(not (kind == 'CONTRL' and tag in ('AK1', 'AK2', 'AK5', 'IK5', 'AK9')
                       or kind != 'CONTRL' and tag in ('UCI', 'UCF', 'UCM')
                       or kind == '997' and tag == 'IK5' or kind == '999' and tag == 'AK5'),
                  'Acknowledgement segment does not match the declared transaction type')
        if tag in ('ST', 'UNH'):
            current_group, current_message = '', None
        elif tag in ('AK1', 'UCF'):
            index = 1 if tag == 'AK1' else 0
            _required(len(values) >= (2 if tag == 'AK1' else 4), f'Incomplete acknowledgement {tag}')
            current_group, current_message = values[index], None
            if tag == 'UCF':
                groups.append({'controlNumber': current_group, 'status': values[3]})
        elif tag == 'AK9':
            _required(current_group and current_message is None and len(values) >= 4
                      and all(re.fullmatch(r'[0-9]{1,9}', count) for count in values[1:4]),
                      'Invalid acknowledgement group counts')
            included, received, accepted = map(int, values[1:4])
            _required(accepted <= received and accepted <= included, 'Acknowledgement accepted count exceeds the group total')
            groups.append({'controlNumber': current_group, 'status': values[0], 'included': included,
                           'received': received, 'accepted': accepted})
            current_group = ''
        elif tag == 'AK2':
            _required(current_group and current_message is None and len(values) >= 2, 'Invalid acknowledgement transaction reference')
            current_message = values[1]
        elif tag in ('AK5', 'IK5', 'UCM'):
            _required(len(values) >= (3 if tag == 'UCM' else 1) and (tag == 'UCM' or current_message),
                      'Invalid acknowledgement transaction result')
            transactions.append({'controlNumber': values[0] if tag == 'UCM' else current_message,
                                 'groupControlNumber': current_group or None, 'status': values[2] if tag == 'UCM' else values[0]})
            current_message = None
        elif tag == 'UCI':
            _required(len(values) >= 4, 'Invalid CONTRL interchange reference')
            interchanges.append({'controlNumber': values[0], 'status': values[3]})
    _required((kind == 'CONTRL' and len(interchanges) == len(document['transactions'])) or
              (kind != 'CONTRL' and len(groups) == len(document['transactions'])), 'Expected a result for each acknowledgement transaction')
    return {'ackType': kind, 'controlNumber': document['controlNumber'], 'interchanges': interchanges,
            'groups': groups, 'transactions': transactions}
