"""Bounded record readers and atomic, file-backed transformation writers."""
import csv
import json
import os
from pathlib import Path
import tempfile
import time
import math


def invalid_constant(value):
    raise ValueError('Non-finite values are not valid streamed JSON: ' + value)


def json_array_records(source, maximum):
    decoder = json.JSONDecoder(parse_constant=invalid_constant)
    buffer = ''; ended = False
    def fill():
        nonlocal buffer, ended
        chunk = source.read(min(65536, maximum + 1))
        if not chunk: ended = True
        buffer += chunk
    def whitespace():
        nonlocal buffer
        buffer = buffer.lstrip()
        while not buffer and not ended:
            fill(); buffer = buffer.lstrip()
    whitespace()
    if not buffer.startswith('['): raise ValueError('Streaming JSON input must be a top-level array')
    buffer = buffer[1:]; first = True
    while True:
        whitespace()
        if buffer.startswith(']'):
            buffer = buffer[1:]
            whitespace()
            if buffer: raise ValueError('Trailing data after streamed JSON array')
            return
        if not first:
            if not buffer.startswith(','): raise ValueError('Expected comma in streamed JSON array')
            buffer = buffer[1:]; whitespace()
            if buffer.startswith(']'): raise ValueError('Trailing comma in streamed JSON array')
        while True:
            try: value, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if ended: raise ValueError('Invalid or incomplete streamed JSON record') from None
                if len(buffer.encode()) > maximum: raise ValueError('JSON record exceeds stream record limit')
                fill(); continue
            if end == len(buffer) and not ended:
                fill(); continue
            if end < len(buffer) and not (buffer[end].isspace() or buffer[end] in ',]'):
                if not ended:
                    if len(buffer.encode()) > maximum: raise ValueError('JSON record exceeds stream record limit')
                    fill(); continue
                raise ValueError('Invalid streamed JSON record separator')
            if len(buffer[:end].encode()) > maximum: raise ValueError('JSON record exceeds stream record limit')
            buffer = buffer[end:]
            yield value
            first = False
            break


def records(path, format, maximum):
    with Path(path).open('r', encoding='utf-8-sig', newline='') as source:
        if format == 'csv':
            # csv permits quoted multiline fields; bound each logical record as well as each field.
            class Lines:
                def __init__(self): self.size = 0
                def __iter__(self): return self
                def __next__(self):
                    line = source.readline(maximum + 1)
                    if not line: raise StopIteration
                    self.size += len(line.encode('utf-8'))
                    if self.size > maximum: raise ValueError('CSV record exceeds stream record limit')
                    return line
            lines = Lines()
            reader = csv.DictReader(lines)
            reader.fieldnames
            if reader.fieldnames and len(set(reader.fieldnames)) != len(reader.fieldnames): raise ValueError('Duplicate CSV input headers')
            lines.size = 0
            for item in reader:
                lines.size = 0
                yield item
        elif format == 'jsonl':
            while True:
                line = source.readline(maximum + 1)
                if not line: break
                if len(line.encode('utf-8')) > maximum: raise ValueError('JSONL record exceeds stream record limit')
                if line.strip(): yield json.loads(line, parse_constant=invalid_constant)
        elif format == 'json':
            yield from json_array_records(source, maximum)
        else: raise ValueError('Streaming input supports json, jsonl or csv')


def execute_file(config, transform, cancelled=None):
    """Consume and write one record at a time; failed output never replaces the target."""
    source = Path(str(config.get('streamInputFile') or '')).resolve()
    target = Path(str(config.get('streamOutputFile') or '')).resolve()
    if not config.get('streamInputFile') or not config.get('streamOutputFile'): raise ValueError('Streaming input and output paths are required')
    if source == target: raise ValueError('Streaming input and output must be different files')
    maximum = int(config.get('streamMaxRecordBytes', 1048576))
    if not 256 <= maximum <= 8388608: raise ValueError('Stream record limit must be between 256 bytes and 8 MiB')
    input_format = config.get('streamInputFormat') or 'jsonl'
    output_format = config.get('streamOutputFormat') or 'jsonl'
    if output_format not in ('jsonl', 'json', 'csv'): raise ValueError('Streaming output supports jsonl, json or csv')
    count = 0
    started = time.monotonic()
    timeout = float(config.get('streamTimeoutSeconds', 600))
    record_limit = int(config.get('streamMaxRecords', 1000000))
    if not math.isfinite(timeout) or timeout <= 0 or record_limit <= 0: raise ValueError('Positive finite streaming timeout and record limit are required')
    def check():
        if cancelled and cancelled(): raise ValueError('Streaming transformation cancelled')
        if time.monotonic() - started > timeout: raise ValueError('Streaming transformation deadline exceeded')
    descriptor, temporary = tempfile.mkstemp(prefix='.mina-transform-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as sink:
            writer = None
            if output_format == 'json': sink.write('[')
            for item in records(source, input_format, maximum):
                check()
                if count >= record_limit: raise ValueError('Streaming record count limit exceeded')
                value = transform(item)
                rendered = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                if len(rendered.encode()) > maximum: raise ValueError('Output record exceeds stream record limit')
                if output_format == 'csv':
                    if not isinstance(value, dict): raise ValueError('CSV streaming output requires object records')
                    if writer is None:
                        writer = csv.DictWriter(sink, fieldnames=list(value), lineterminator='\n')
                        writer.writeheader()
                    writer.writerow(value)
                else:
                    if output_format == 'json' and count: sink.write(',')
                    sink.write(rendered)
                    if output_format == 'jsonl': sink.write('\n')
                count += 1
            if output_format == 'json': sink.write(']')
            sink.flush(); os.fsync(sink.fileno())
        check()
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return {'streamed': True, 'recordsWritten': count, 'outputFile': str(target), 'outputFormat': output_format}
