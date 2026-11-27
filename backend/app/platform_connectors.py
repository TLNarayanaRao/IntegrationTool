"""Cloud object/queue operations and leased PostgreSQL change events."""
import base64
import json
import os
import uuid
from contextlib import closing


def _required(config, key):
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} is required')
    return value


def _bounded(config, key, default, minimum, maximum):
    value = int(config.get(key, default))
    if not minimum <= value <= maximum:
        raise ValueError(f'{key} must be between {minimum} and {maximum}')
    return value


def _aws(service, config):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise ValueError('Install boto3 to use AWS activities') from exc
    return boto3.session.Session().client(service, region_name=config.get('region') or None, config=Config(
        connect_timeout=5, read_timeout=30, retries={'mode': 'standard', 'total_max_attempts': 2}))


def _s3(operation, config, payload):
    bucket = _required(config, 'bucket')
    with closing(_aws('s3', config)) as client:
        if operation == 's3_list':
            args = {'Bucket': bucket, 'Prefix': config.get('prefix') or '',
                    'MaxKeys': _bounded(config, 'limit', 100, 1, 1000)}
            if config.get('continuationToken'):
                args['ContinuationToken'] = config['continuationToken']
            result = client.list_objects_v2(**args)
            return {'objects': [{'key': item['Key'], 'size': item['Size'], 'etag': item.get('ETag')}
                                for item in result.get('Contents', [])],
                    'continuationToken': result.get('NextContinuationToken')}
        args = {'Bucket': bucket, 'Key': _required(config, 'objectKey')}
        limit = _bounded(config, 'maxBytes', 1048576, 1, 16777216)
        if operation == 's3_get':
            result = client.get_object(**args)
            with closing(result['Body']) as stream:
                content = stream.read(limit + 1)
            if len(content) > limit:
                raise ValueError('S3 object exceeds the configured byte limit')
            return {'key': args['Key'], 'contentBase64': base64.b64encode(content).decode('ascii'),
                    'contentType': result.get('ContentType'), 'size': len(content), 'etag': result.get('ETag')}
        if operation != 's3_put':
            raise ValueError('Unsupported S3 operation')
        if config.get('contentBase64') is not None:
            content = base64.b64decode(config['contentBase64'], validate=True)
        elif isinstance(payload, str):
            content = payload.encode()
        else:
            content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        if len(content) > limit:
            raise ValueError('S3 upload exceeds the configured byte limit')
        if config.get('contentType'):
            args['ContentType'] = config['contentType']
        if config.get('ifAbsent') is True:
            args['IfNoneMatch'] = '*'
        result = client.put_object(**args, Body=content)
        return {'key': args['Key'], 'etag': result.get('ETag'), 'versionId': result.get('VersionId')}


def _sqs(operation, config, payload):
    args = {'QueueUrl': _required(config, 'queueUrl')}
    with closing(_aws('sqs', config)) as client:
        if operation == 'sqs_send':
            body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if config.get('messageGroupId'):
                args['MessageGroupId'] = config['messageGroupId']
            if config.get('deduplicationId'):
                args['MessageDeduplicationId'] = config['deduplicationId']
            result = client.send_message(**args, MessageBody=body)
            return {'messageId': result['MessageId']}
        if operation == 'sqs_ack':
            client.delete_message(**args, ReceiptHandle=_required(config, 'receiptHandle'))
            return {'acknowledged': True}
        if operation not in {'sqs_receive', 's3_event'}:
            raise ValueError('Unsupported SQS operation')
        result = client.receive_message(**args, MaxNumberOfMessages=1,
            WaitTimeSeconds=_bounded(config, 'waitSeconds', 10, 0, 20),
            VisibilityTimeout=_bounded(config, 'visibilitySeconds', 120, 1, 43200))
        messages = result.get('Messages') or []
        if not messages:
            return {'received': False}
        message = messages[0]
        output = {'received': True, 'messageId': message['MessageId'],
                  'body': message['Body'], 'receiptHandle': message['ReceiptHandle']}
        if operation == 's3_event':
            event = json.loads(output['body'])
            if not isinstance(event, dict):
                raise ValueError('Expected an S3 bucket notification')
            if event.get('Event') == 's3:TestEvent':
                output['records'] = []
            else:
                from urllib.parse import unquote_plus
                records = event.get('Records')
                if not isinstance(records, list) or not records:
                    raise ValueError('Expected S3 bucket notification records')
                output['records'] = [{'eventName': record['eventName'], 'bucket': record['s3']['bucket']['name'],
                                      'key': unquote_plus(record['s3']['object']['key']),
                                      'versionId': record['s3']['object'].get('versionId')}
                                     for record in records if record.get('eventSource') == 'aws:s3']
                if len(output['records']) != len(records):
                    raise ValueError('Only direct S3 notifications are supported')
        return output


def _cdc(operation, config):
    dsn = os.environ.get('MINA_POSTGRES_CDC_DSN')
    if not dsn:
        raise ValueError('Set MINA_POSTGRES_CDC_DSN to use PostgreSQL change capture')
    import psycopg
    channel = _required(config, 'channel')
    try:
        with psycopg.connect(dsn, connect_timeout=5, options='-c statement_timeout=10000') as db:
            if operation == 'cdc_ack':
                changed = db.execute(
                    "DELETE FROM mina_cdc.changes WHERE channel=%s AND id=%s AND lease_token=%s AND lease_until>clock_timestamp()",
                    (channel, int(config['changeId']), _required(config, 'leaseToken'))).rowcount
                if not changed:
                    raise ValueError('Change receipt expired or was already acknowledged')
                return {'acknowledged': True}
            if operation != 'cdc_receive':
                raise ValueError('Unsupported PostgreSQL change capture operation')
            token = str(uuid.uuid4())
            row = db.execute("""
                WITH candidate AS (
                    SELECT id FROM mina_cdc.changes WHERE channel=%s AND lease_until<=clock_timestamp()
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE mina_cdc.changes AS change SET lease_token=%s,
                    lease_until=clock_timestamp()+make_interval(secs => %s)
                FROM candidate WHERE change.id=candidate.id
                RETURNING change.id,change.operation,change.source_table,change.old_row,change.new_row
                """, (channel, token, _bounded(config, 'visibilitySeconds', 120, 1, 86400))).fetchone()
            if row is None:
                return {'received': False}
            return {'received': True, 'changeId': row[0], 'operation': row[1], 'table': row[2],
                    'before': row[3], 'after': row[4], 'leaseToken': token}
    except psycopg.Error:
        raise ValueError('PostgreSQL change capture is unavailable. Check the connection and mina_cdc schema.') from None


def execute(operation, config, payload):
    if operation == 's3_event' or operation.startswith('sqs_'):
        return _sqs(operation, config, payload)
    if operation.startswith('s3_'):
        return _s3(operation, config, payload)
    return _cdc(operation, config)
