"""Partner-scoped AS2 exchange, detached CMS signatures and signed MDNs."""
import base64
from datetime import datetime, timezone
from email import policy
from email.parser import BytesHeaderParser
from email.utils import formatdate
import hashlib
import hmac
import ipaddress
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlsplit
import uuid
import zlib

from .edi import MAX_BYTES as MAX_EDI_BYTES, parse as parse_edi, render as render_edi
from .edi_ack import generate as generate_ack, read as read_ack
from .as2_ledger import record


MAX_WIRE = 2 * MAX_EDI_BYTES + 65536
EDI_TYPES = {'x12': 'application/edi-x12', 'edifact': 'application/edifact'}
SIGNATURE_TYPES = {'application/pkcs7-signature', 'application/x-pkcs7-signature'}
ENVELOPED_TYPES = {'application/pkcs7-mime', 'application/x-pkcs7-mime'}
COMPRESSED_TYPE = 'application/pkcs7-mime; smime-type=compressed-data; name=smime.p7z'
REPLAY_HEADERS = ('date', 'content-transfer-encoding', 'disposition-notification-to', 'disposition-notification-options')


class TradingPartnerError(ValueError):
    fault_type = 'TradingPartnerException'


class _DecompressionError(ValueError):
    pass


def _string(value, label, maximum=255):
    if not isinstance(value, str) or not re.fullmatch(r'[ -~]+', value) or len(value) > maximum:
        raise ValueError(f'{label} is missing or invalid')
    return value


def _as2_id(value, *, wire=False):
    value = _string(value, 'AS2 ID', 258)
    if value.startswith('"') and value.endswith('"'):
        quoted = value[1:-1]
        if not re.fullmatch(r'(?:[^"\\]|\\["\\])+', quoted):
            raise ValueError('Invalid AS2 ID quoting')
        value = re.sub(r'\\(["\\])', r'\1', quoted)
    elif wire and any(character in value for character in ' "\\'):
        raise ValueError('Invalid AS2 ID quoting')
    if not value or len(value) > 128:
        raise ValueError('Invalid AS2 ID')
    return value


def _wire_id(value):
    if re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", value):
        return value
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def _message_id(value):
    value = _string(value, 'AS2 Message-ID', 998)
    if value.startswith('<') and value.endswith('>'):
        value = value[1:-1]
    if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+', value):
        raise ValueError('Invalid AS2 Message-ID')
    return value


def _flag(profile, key, default):
    value = profile.get(key)
    if value is None or value == '':
        return default
    setting = str(value).strip().lower()
    if setting in ('true', 'yes', '1'):
        return True
    if setting in ('false', 'no', '0'):
        return False
    raise ValueError(f'AS2 {key} must be a boolean')


def _pem(profile, key):
    path = Path(_string(profile.get(key), key, 2048)).expanduser()
    with path.open('rb') as source:
        data = source.read(65537)
    if not data or len(data) > 65536:
        raise ValueError(f'{key} must point to a PEM file of up to 64 KiB')
    return data


def _cert(profile, key):
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    cert = x509.load_pem_x509_certificate(_pem(profile, key))
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
        raise ValueError(f'{key} is outside its certificate validity period')
    public_key = cert.public_key()
    if not ((isinstance(public_key, rsa.RSAPublicKey) and public_key.key_size >= 2048) or
            (isinstance(public_key, ec.EllipticCurvePublicKey) and public_key.key_size >= 256)):
        raise ValueError(f'{key} requires an RSA key of at least 2048 bits or an EC key of at least 256 bits')
    return cert


def _key(profile, key):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    password = profile.get('localKeyPassword')
    return load_pem_private_key(_pem(profile, key), password=str(password).encode('utf-8') if password else None)


def _unbase64(value, limit=MAX_WIRE):
    if not isinstance(value, (str, bytes)) or len(value) > (limit * 2):
        raise ValueError('AS2 content exceeds the allowed size')
    compact = re.sub(rb'[ \t\r\n]', b'', value.encode('ascii') if isinstance(value, str) else value)
    raw = base64.b64decode(compact, validate=True)
    if len(raw) > limit:
        raise ValueError('AS2 content exceeds the allowed size')
    return raw


def _base64(value):
    return base64.b64encode(value).decode('ascii')


def _mic(value):
    return _base64(hashlib.sha256(value).digest())


def _safe_header(headers, name, fallback=None):
    values = [value for key, value in headers.items() if str(key).lower() == name.lower()]
    if not values:
        return fallback
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError(f'Invalid or repeated AS2 header {name}')
    return _string(values[0].strip(), name, 8192)


def _entity(content_type, body, transfer='binary'):
    return f'Content-Type: {content_type}\r\nContent-Transfer-Encoding: {transfer}\r\n\r\n'.encode('ascii') + body


def _parse_entity(data):
    boundary = re.search(rb'\r?\n\r?\n', data[:16384])
    if boundary is None:
        raise ValueError('Invalid AS2 MIME entity headers')
    return BytesHeaderParser(policy=policy.default).parsebytes(data[:boundary.end()]), data[boundary.end():]


def _entity_type(headers):
    if len(headers.get_all('Content-Type', [])) != 1:
        raise ValueError('AS2 MIME entity requires exactly one Content-Type')
    return headers.get_content_type().lower()


def _decoded(headers, body):
    values = headers.get_all('Content-Transfer-Encoding', [])
    if len(values) > 1:
        raise ValueError('Repeated AS2 content transfer encoding')
    encoding = (values[0] if values else 'binary').strip().lower()
    if encoding == 'base64':
        return _unbase64(body)
    if encoding not in ('binary', '7bit', '8bit'):
        raise ValueError('Unsupported AS2 MIME transfer encoding')
    return body


def _multipart(subtype, options, parts):
    boundary = f'mina-{uuid.uuid4().hex}'
    marker = b'--' + boundary.encode()
    body = b''.join(marker + b'\r\n' + part + b'\r\n' for part in parts) + marker + b'--\r\n'
    return f'multipart/{subtype}; boundary="{boundary}"; {options}', body


def _parts(headers, body):
    boundary = headers.get_boundary()
    if not isinstance(boundary, str) or not re.fullmatch(r'[ -~]{1,70}', boundary):
        raise ValueError('Invalid AS2 MIME boundary')
    pattern = re.compile(rb'(?:\A|(?<=\n))--' + re.escape(boundary.encode('ascii')) + rb'(--)?[ \t]*(?:\r?\n|\Z)')
    matches = []
    for match in pattern.finditer(body):
        matches.append(match)
        if len(matches) > 4:
            raise ValueError('Unexpected number of AS2 MIME parts')
    if len(matches) < 2 or matches[-1].group(1) != b'--' or any(m.group(1) for m in matches[:-1]):
        raise ValueError('Incomplete AS2 MIME structure')
    return [body[left.end():right.start()].removesuffix(b'\r\n') if body[right.start()-2:right.start()] == b'\r\n'
            else body[left.end():right.start()].removesuffix(b'\n') for left, right in zip(matches, matches[1:])]


def _signed(entity, profile):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7
    signature = pkcs7.PKCS7SignatureBuilder().set_data(entity).add_signer(
        _cert(profile, 'localCertificateFile'), _key(profile, 'localPrivateKeyFile'), hashes.SHA256()
    ).sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature,
            pkcs7.PKCS7Options.Binary, pkcs7.PKCS7Options.NoCapabilities])
    encoded = base64.encodebytes(signature).replace(b'\n', b'\r\n').rstrip(b'\r\n')
    return _multipart('signed', 'protocol="application/pkcs7-signature"; micalg=sha-256',
                      [entity, _entity('application/pkcs7-signature; name=smime.p7s', encoded, 'base64')])


def _verify_signature(entity, signature, certificate):
    from asn1crypto import cms, x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    envelope = cms.ContentInfo.load(signature, strict=True)
    if envelope['content_type'].native != 'signed_data':
        raise ValueError('AS2 signature must contain CMS SignedData')
    content = envelope['content']
    signers = content['signer_infos']
    if len(signers) != 1 or content['encap_content_info']['content'].native is not None:
        raise ValueError('AS2 requires one detached CMS signer')
    signer = signers[0]
    sid = signer['sid']
    pinned = x509.Certificate.load(certificate.public_bytes(serialization.Encoding.DER))
    if sid.name == 'issuer_and_serial_number':
        identity = sid.chosen
        matched = (identity['serial_number'].native == pinned.serial_number and
                   identity['issuer'].dump() == pinned.issuer.dump())
    else:
        matched = pinned.key_identifier is not None and sid.chosen.native == pinned.key_identifier
    if not matched or signer['digest_algorithm']['algorithm'].native != 'sha256':
        raise ValueError('AS2 signer or digest does not match the partner profile')
    attributes = signer['signed_attrs']
    signed_attrs = {}
    for attr in attributes:
        name = attr['type'].native
        if name in signed_attrs or len(attr['values']) != 1:
            raise ValueError('Ambiguous AS2 signed attributes')
        signed_attrs[name] = attr['values'][0].native
    if signed_attrs.get('content_type') != 'data' or signed_attrs.get('message_digest') != hashlib.sha256(entity).digest():
        raise ValueError('AS2 signature digest does not match the message')
    algorithm = signer['signature_algorithm']['algorithm'].native
    public_key = certificate.public_key()
    encoded = attributes.untag().dump(force=True)
    try:
        if isinstance(public_key, rsa.RSAPublicKey) and algorithm in {'rsassa_pkcs1v15', 'sha256_rsa'}:
            public_key.verify(signer['signature'].native, encoded, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(public_key, ec.EllipticCurvePublicKey) and algorithm == 'sha256_ecdsa':
            public_key.verify(signer['signature'].native, encoded, ec.ECDSA(hashes.SHA256()))
        else:
            raise ValueError('Unsupported AS2 CMS signature algorithm')
    except InvalidSignature:
        raise ValueError('AS2 signature verification failed') from None


def _verified(content_type, body, profile):
    headers, multipart = _parse_entity(_entity(content_type, body))
    if _entity_type(headers) != 'multipart/signed' or str(headers.get_param('protocol')).lower() not in SIGNATURE_TYPES:
        raise ValueError('A signed AS2 MIME message is required')
    parts = _parts(headers, multipart)
    if len(parts) != 2:
        raise ValueError('AS2 signed MIME must contain data and one signature')
    header, signature = _parse_entity(parts[1])
    if _entity_type(header) not in SIGNATURE_TYPES:
        raise ValueError('AS2 signature part is missing')
    _verify_signature(parts[0], _decoded(header, signature), _cert(profile, 'partnerCertificateFile'))
    return parts[0]


def _encrypt(content_type, body, profile):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers import algorithms
    from cryptography.hazmat.primitives.serialization import pkcs7
    encrypted = pkcs7.PKCS7EnvelopeBuilder().set_data(_entity(content_type, body)).add_recipient(
        _cert(profile, 'partnerCertificateFile')
    ).set_content_encryption_algorithm(algorithms.AES256).encrypt(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    return 'application/pkcs7-mime; smime-type=enveloped-data', encrypted


def _compress(entity):
    from asn1crypto import cms

    return cms.ContentInfo({'content_type': 'compressed_data', 'content': {
        'version': 'v0', 'compression_algorithm': {'algorithm': 'zlib'},
        'encap_content_info': {'content_type': 'data', 'content': zlib.compress(entity)},
    }}).dump()


def _is_compressed(headers):
    return (_entity_type(headers) in ENVELOPED_TYPES and
            str(headers.get_param('smime-type')).lower() == 'compressed-data')


def _decompress(headers, body, limit):
    from asn1crypto import cms

    try:
        envelope = cms.ContentInfo.load(_decoded(headers, body), strict=True)
        if envelope['content_type'].native != 'compressed_data':
            raise ValueError('Expected CMS CompressedData')
        content = envelope['content']
        encapsulated = content['encap_content_info']
        if (content['version'].native != 'v0' or content['compression_algorithm']['algorithm'].native != 'zlib'
                or encapsulated['content_type'].native != 'data'):
            raise ValueError('Unsupported CMS compression format')
        decoder = zlib.decompressobj()
        expanded = decoder.decompress(encapsulated['content'].native, limit + 1)
        if len(expanded) > limit or not decoder.eof or decoder.unused_data:
            raise ValueError('Truncated or oversized compressed EDI content')
        return expanded
    except (ValueError, TypeError, zlib.error) as error:
        raise _DecompressionError('AS2 CMS decompression failed or exceeded the allowed size') from error


def _unpack(content_type, body, headers, profile):
    mime, _ = _parse_entity(_entity(content_type, b''))
    transfer = _safe_header(headers, 'content-transfer-encoding', 'binary').lower()
    if _entity_type(mime) in ENVELOPED_TYPES and not _is_compressed(mime):
        from cryptography.hazmat.primitives.serialization import pkcs7
        mime, _ = _parse_entity(_entity(content_type, b'', transfer))
        ciphertext = _decoded(mime, body)
        try:
            plaintext = pkcs7.pkcs7_decrypt_der(ciphertext, _cert(profile, 'localCertificateFile'),
                                              _key(profile, 'localPrivateKeyFile'), [])
        except ValueError:
            raise ValueError('AS2 envelope could not be decrypted') from None
        mime, body = _parse_entity(plaintext)
    elif _flag(profile, 'requireEncryption', True):
        raise ValueError('This partner requires encrypted AS2 messages')
    elif _is_compressed(mime):
        mime, _ = _parse_entity(_entity(content_type, b'', transfer))
    compressed = _is_compressed(mime)
    if compressed:
        mime, body = _parse_entity(_decompress(mime, body, MAX_WIRE))
    if _entity_type(mime) != 'multipart/signed':
        raise ValueError('A signed AS2 MIME message is required')
    signed_entity = _verified(mime['Content-Type'], body, profile)
    inner, _ = _parse_entity(signed_entity)
    if compressed and _is_compressed(inner):
        raise ValueError('AS2 supports one CMS compression layer per exchange')
    return signed_entity


def _rules(options):
    rules = options.get('transactionRules')
    if isinstance(rules, str):
        import json
        return json.loads(rules) if rules.strip() else None
    return rules


def _edi(payload, options):
    return parse_edi(payload, options.get('ediFormat') or '', _rules(options), options.get('allowedTransactionTypes'))


def _identities(profile):
    return _as2_id(profile.get('localAs2Id')), _as2_id(profile.get('partnerAs2Id'))


def _ids(headers, sender, recipient):
    if (_as2_id(_safe_header(headers, 'as2-from'), wire=True) != sender or
            _as2_id(_safe_header(headers, 'as2-to'), wire=True) != recipient):
        raise ValueError('AS2 sender or recipient does not match the partner profile')


def _edi_ids(interchange, profile, direction):
    local, partner = profile.get('localEdiId'), profile.get('partnerEdiId')
    sender, receiver = (partner, local) if direction == 'inbound' else (local, partner)
    separator = interchange['separators']['component']
    for name, expected in (('sender', sender), ('receiver', receiver)):
        actual = interchange[name]
        if interchange['format'] == 'edifact':
            actual = actual.split(separator, 1)[0]
        if expected and actual != str(expected).strip():
            raise ValueError(f'EDI interchange {name} does not match the partner profile')


def _partner_media_type(profile):
    value = profile.get('as2PayloadMediaType')
    if value is None or value == '':
        return None
    media = _string(value, 'AS2 payload media type', 127).strip().lower()
    if (not re.fullmatch(r"(?:application|text|audio|image|video|font|model)/[a-z0-9][a-z0-9!#$&^_.+-]*", media)
            or media in set(EDI_TYPES.values()) | ENVELOPED_TYPES | SIGNATURE_TYPES):
        raise ValueError('Enter a business payload media type without parameters, or leave it blank for validated X12 and EDIFACT')
    return media


def _send_retries(profile):
    value = str(profile.get('as2ResponseRetries') or '0').strip()
    if value not in ('0', '1', '2'):
        raise ValueError('AS2 response retries must be 0, 1 or 2')
    return int(value)


def _send_credentials(profile, url):
    username, password = profile.get('as2HttpUsername'), profile.get('as2HttpPassword')
    if username in (None, '') and password in (None, ''):
        return None
    if (not isinstance(username, str) or not username or ':' in username or not isinstance(password, str) or not password
            or any(ord(char) < 32 or ord(char) == 127 for char in username + password)):
        raise ValueError('AS2 HTTP Basic authentication requires a valid username and password')
    if urlsplit(url).scheme != 'https':
        raise ValueError('AS2 HTTP Basic authentication requires HTTPS')
    return username, password


def _receipt(profile, message_id, mic, rejected, error_code='unexpected-processing-error'):
    local, partner = _identities(profile)
    disposition = f'processed/error: {error_code}' if rejected else 'processed'
    entity = _entity('message/disposition-notification', (
        'Reporting-UA: MINA AS2\r\n'
        f'Final-Recipient: rfc822; {_wire_id(local)}\r\nOriginal-Message-ID: {message_id}\r\n'
        f'Disposition: automatic-action/MDN-sent-automatically; {disposition}\r\n'
        + (f'Received-content-MIC: {mic}, sha-256\r\n' if mic else '')
    ).encode('ascii'), '7bit')
    report_type, report = _multipart('report', 'report-type=disposition-notification', [
        _entity('text/plain; charset=us-ascii', b'AS2 interchange receipt', '7bit'), entity])
    content_type, body = _signed(_entity(report_type, report, '7bit'), profile)
    return {'statusCode': 200, 'headers': {'Content-Type': content_type, 'AS2-Version': '1.1',
            'AS2-From': _wire_id(local), 'AS2-To': _wire_id(partner),
            'Message-ID': f'<{uuid.uuid4().hex}@mina.invalid>'}, 'binaryContent': _base64(body)}


def _read_mdn(headers, body, profile):
    local, partner = _identities(profile)
    _ids(headers, partner, local)
    signed = _verified(_safe_header(headers, 'content-type', ''), body, profile)
    report, report_body = _parse_entity(signed)
    if _entity_type(report) != 'multipart/report' or report.get_param('report-type') != 'disposition-notification':
        raise ValueError('Expected an AS2 disposition-notification report')
    parts = _parts(report, report_body)
    if len(parts) not in (2, 3):
        raise ValueError('Unexpected AS2 MDN structure')
    fields, values = _parse_entity(parts[1])
    if _entity_type(fields) != 'message/disposition-notification':
        raise ValueError('AS2 MDN is missing its machine-readable report')
    mdn = BytesHeaderParser(policy=policy.default).parsebytes(_decoded(fields, values))
    if any(len(mdn.get_all(name, [])) != 1 for name in ('Original-Message-ID', 'Disposition')):
        raise ValueError('AS2 MDN is missing required singleton fields')
    message_id = _message_id(mdn['Original-Message-ID'])
    disposition = mdn['Disposition'].partition(';')[2].strip().lower()
    result = re.fullmatch(r'(processed|failed)(?:/(error|warning|failure)(?::[ -~]+)?)?', disposition)
    if not result:
        raise ValueError('Invalid AS2 MDN disposition')
    accepted = result[1] == 'processed' and result[2] in (None, 'warning')
    mics = mdn.get_all('Received-Content-MIC', [])
    if not mics and not accepted:
        return message_id, None, False
    if len(mics) != 1:
        raise ValueError('AS2 MDN integrity check failed')
    digest, _, method = mics[0].partition(',')
    digest = digest.strip()
    if method.strip().lower().replace('-', '') != 'sha256' or len(_unbase64(digest, 32)) != 32:
        raise ValueError('AS2 MDN integrity check failed')
    return message_id, digest, accepted


def _verify_mdn(headers, body, profile, message_id, mic):
    received_id, digest, accepted = _read_mdn(headers, body, profile)
    if received_id != message_id:
        raise ValueError('AS2 MDN refers to a different Message-ID')
    if digest is not None and not hmac.compare_digest(digest.encode(), mic.encode()):
        raise ValueError('AS2 MDN integrity check failed')
    return accepted, digest is not None


def _endpoint(profile, url=None):
    url = _string(profile.get('endpointUrl') if url is None else url, 'AS2 endpoint URL', 4096)
    endpoint = urlsplit(url)
    if (not endpoint.hostname or endpoint.username is not None or endpoint.password is not None or endpoint.fragment
            or any(char.isspace() or char == '\\' for char in url) or endpoint.port == 0):
        raise ValueError('Invalid partner endpoint URL')
    if endpoint.scheme != 'https':
        try:
            local = ipaddress.ip_address(endpoint.hostname).is_loopback
        except ValueError:
            local = False
        if endpoint.scheme != 'http' or not local or not _flag(profile, 'allowLoopbackHttp', False):
            raise ValueError('AS2 requires HTTPS except explicitly enabled loopback tests')
    return url


def validate_profile(profile):
    _identities(profile)
    _partner_media_type(profile)
    _send_retries(profile)
    for key, default in (('encryptOutbound', True), ('requireEncryption', True), ('compressOutbound', False),
                         ('rejectInvalidEdiWithMdn', False), ('allowLoopbackHttp', False)):
        _flag(profile, key, default)
    certificate = _cert(profile, 'localCertificateFile')
    _cert(profile, 'partnerCertificateFile')
    if certificate.public_key() != _key(profile, 'localPrivateKeyFile').public_key():
        raise ValueError('Local AS2 certificate and private key do not match')
    if profile.get('endpointUrl'):
        _send_credentials(profile, _endpoint(profile))
        _string(profile.get('receiptAddress'), 'Disposition notification address')
    mode = profile.get('receiptMode') or 'synchronous'
    if mode not in ('synchronous', 'asynchronous'):
        raise ValueError('AS2 receipt mode must be synchronous or asynchronous')
    if mode == 'asynchronous':
        _endpoint(profile, profile.get('localMdnUrl') or '')
    if profile.get('partnerMdnUrl'):
        _endpoint(profile, profile['partnerMdnUrl'])
    if any(profile.get(field) for field in ('tlsCaFile', 'as2TlsClientCertFile', 'as2TlsClientKeyFile', 'as2TlsClientKeyPassword')):
        _tls_context(profile)


def _tls_context(profile):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    cert, key = profile.get('as2TlsClientCertFile'), profile.get('as2TlsClientKeyFile')
    password = profile.get('as2TlsClientKeyPassword')
    if bool(cert) != bool(key) or (password and not cert):
        raise ValueError('AS2 mutual TLS requires both a client certificate and private key')
    try:
        if profile.get('tlsCaFile'):
            context.load_verify_locations(cafile=profile['tlsCaFile'])
        if cert:
            context.load_cert_chain(cert, key, password=str(password) if password else lambda: b'')
    except (OSError, ValueError):
        raise ValueError('AS2 TLS CA bundle or client certificate/key could not be loaded') from None
    return context


def _post(profile, headers, body, endpoint=None):
    import httpx
    url = _endpoint(profile, endpoint)
    if profile.get('as2TlsClientCertFile') and urlsplit(url).scheme != 'https':
        raise ValueError('AS2 mutual TLS requires HTTPS')
    context = _tls_context(profile)
    timeout = float(profile.get('timeoutSeconds') or 30)
    if not 1 <= timeout <= 120:
        raise ValueError('AS2 timeout must be between 1 and 120 seconds')
    retries = _send_retries(profile) if endpoint is None else 0
    credentials = _send_credentials(profile, url) if endpoint is None else None
    with httpx.Client(verify=context, timeout=timeout, follow_redirects=False, trust_env=False,
                      auth=httpx.BasicAuth(*credentials) if credentials else None) as client:
        for attempt in range(retries + 1):
            deadline = time.monotonic() + timeout
            try:
                with client.stream('POST', url, headers={**headers, 'Accept-Encoding': 'identity'}, content=body) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_raw():
                        if time.monotonic() >= deadline:
                            raise httpx.ReadTimeout('Timed out receiving the AS2 MDN')
                        data.extend(chunk)
                        if len(data) > 262144:
                            raise ValueError('AS2 MDN exceeds 256 KiB')
                    return dict(response.headers), bytes(data)
            except httpx.HTTPStatusError as error:
                raise ValueError(f'Partner returned HTTP {error.response.status_code}') from None
            except (httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError):
                if attempt == retries:
                    raise ValueError('AS2 HTTPS delivery failed or the receipt could not be read') from None
                time.sleep(0.25 * (2 ** attempt))
            except httpx.RequestError:
                raise ValueError('AS2 HTTPS delivery failed or the receipt could not be read') from None


def _transport_ack():
    return {'statusCode': 200, 'headers': {'Content-Type': 'text/plain'}, 'binaryContent': ''}


def _incoming_request(config, payload):
    request = config.get('request', payload)
    if not isinstance(request, dict) or not isinstance(request.get('headers'), dict):
        raise ValueError('Map the HTTP Listener output into the AS2 request')
    return request


def _exchange(operation, profile_id, profile, config, payload):
    backend = profile.get('reconciliationBackend') or 'sqlite'
    shared_key = profile.get('reconciliationKey')
    profile_id = str(shared_key or profile_id)
    if len(profile_id) > 255:
        raise ValueError('AS2 reconciliation key cannot exceed 255 characters')
    if backend == 'postgresql' or shared_key:
        local, partner = _identities(profile)
        profile_id = hashlib.sha256('\0'.join((profile_id, local, partner)).encode()).hexdigest()
    def exchange(message_id, direction, action, **kwargs):
        return record(profile_id, message_id, direction, action, backend=backend, **kwargs)
    if operation == 'as2_lookup':
        direction = config.get('direction') or 'inbound'
        if direction not in ('inbound', 'outbound'):
            raise ValueError('AS2 direction must be inbound or outbound')
        return exchange(_message_id(config.get('messageId')), direction, 'read')
    local, partner = _identities(profile)
    if operation == 'as2_receive':
        expected_media = _partner_media_type(profile)
        request = _incoming_request(config, payload)
        headers = request['headers']
        _ids(headers, partner, local)
        callback = _safe_header(headers, 'receipt-delivery-option')
        if callback and callback != _endpoint(profile, profile.get('partnerMdnUrl') or ''):
            raise ValueError('AS2 callback URL does not match the configured partner MDN endpoint')
        original_id = _safe_header(headers, 'message-id')
        message_id = _message_id(original_id)
        raw = _unbase64(request.get('binaryContent'))
        content_type = _safe_header(headers, 'content-type', '')
        entity = _unpack(content_type, raw, headers, profile)
        mic = _mic(entity)
        mime, body = _parse_entity(entity)
        error_code, interchange = None, None
        try:
            if _is_compressed(mime):
                mime, body = _parse_entity(_decompress(mime, body, MAX_WIRE))
            content = _decoded(mime, body)
            media = _entity_type(mime)
            if expected_media:
                if media != expected_media:
                    raise ValueError('AS2 MIME type does not match the partner payload media type')
                if not 0 < len(content) <= MAX_EDI_BYTES:
                    raise ValueError('AS2 payload must contain 1 byte to 8 MiB')
            else:
                interchange = _edi(content, profile)
                _edi_ids(interchange, profile, 'inbound')
                if media != EDI_TYPES[interchange['format']]:
                    raise ValueError('AS2 MIME type does not match the EDI interchange')
        except ValueError as error:
            if not (_flag(profile, 'rejectInvalidEdiWithMdn', False) and _safe_header(headers, 'disposition-notification-to')):
                raise
            error_code = 'decompression-failed' if isinstance(error, _DecompressionError) else 'unexpected-processing-error'
        mode = 'asynchronous' if callback else 'synchronous'
        lease = int(profile.get('reconciliationLeaseSeconds') or 300)
        if not 1 <= lease <= 86400:
            raise ValueError('AS2 reconciliation lease must be from 1 to 86400 seconds')
        fingerprint = content_type.encode('ascii') + b'\0' + raw
        if callback:
            fingerprint = callback.encode('ascii') + b'\0' + fingerprint
        state = exchange(message_id, 'inbound', 'claim', entry={
            'fingerprint': _mic(fingerprint), 'mic': mic, 'receiptMode': mode, 'leaseSeconds': lease,
            'controlNumber': interchange['controlNumber'] if interchange else '', 'originalId': original_id,
            'wireHeaders': {name: _safe_header(headers, name) for name in REPLAY_HEADERS},
            **({'errorCode': error_code} if error_code else {}),
            **({'callbackUrl': callback} if callback else {})})
        if state['duplicate']:
            if state['receiptMode'] == 'asynchronous':
                state['receipt'] = _transport_ack()
            return {'messageId': message_id, **state}
        if error_code:
            receipt = _receipt(profile, original_id, mic, True, error_code)
            exchange(message_id, 'inbound', 'rejected', token=state['claimToken'], receipt=receipt)
            return {'messageId': message_id, 'duplicate': False, 'status': 'rejected', 'errorCode': error_code,
                    'mic': mic, 'receiptMode': mode, 'receipt': _transport_ack() if callback else receipt,
                    **({'callbackStatus': 'pending'} if callback else {})}
        delivery = ({'contentType': media, 'binaryContent': _base64(content)} if expected_media else
                    {'interchange': interchange, 'text': content.decode('latin-1')})
        return {'messageId': message_id, **state, **delivery, 'mic': mic, 'receiptMode': mode,
                **({'receipt': _transport_ack()} if callback else {})}
    if operation == 'as2_receipt':
        message_id = _message_id(config.get('messageId'))
        token = config.get('claimToken') or ''
        action = config.get('disposition') or 'processed'
        if action not in ('processed', 'rejected'):
            raise ValueError('AS2 receipt disposition must be processed or rejected')
        data = exchange(message_id, 'inbound', 'details', token=token)
        receipt = _receipt(profile, data['originalId'], data['mic'], action == 'rejected')
        result = exchange(message_id, 'inbound', action, token=token, receipt=receipt)
        if data.get('receiptMode') == 'asynchronous':
            return {**result, 'receipt': _transport_ack(), 'receiptMode': 'asynchronous', 'callbackStatus': 'pending'}
        return {**result, 'receipt': receipt}
    if operation == 'as2_mdn_receive':
        request = _incoming_request(config, payload)
        headers = request['headers']
        body = _unbase64(request.get('binaryContent'), 262144)
        message_id, digest, accepted = _read_mdn(headers, body, profile)
        status = 'processed' if accepted else 'rejected'
        result = exchange(message_id, 'outbound', 'reconcile_mdn', entry={'mic': digest, 'status': status},
                          receipt={'headers': {'Content-Type': _safe_header(headers, 'content-type')}, 'binaryContent': _base64(body)})
        return {**result, 'accepted': accepted, 'receiptMicVerified': digest is not None, 'receipt': _transport_ack()}
    if operation == 'as2_mdn_deliver':
        message_id = _message_id(config.get('messageId'))
        delivery = exchange(message_id, 'inbound', 'callback_claim')
        if delivery['duplicate']:
            return delivery
        token = delivery['claimToken']
        try:
            endpoint = _endpoint(profile, profile.get('partnerMdnUrl') or '')
            if delivery['callbackUrl'] != endpoint:
                raise ValueError('Stored AS2 callback differs from the current partner endpoint')
            receipt = delivery['receipt']
            _post(profile, receipt['headers'], _unbase64(receipt['binaryContent'], 262144), endpoint)
        except Exception:
            exchange(message_id, 'inbound', 'callback_pending', token=token)
            raise
        return exchange(message_id, 'inbound', 'callback_sent', token=token)
    if operation != 'as2_send':
        raise ValueError('Unknown trading-partner operation')
    media = _partner_media_type(profile)
    content = _unbase64(config['contentBase64'], MAX_EDI_BYTES) if config.get('contentBase64') is not None else (
        payload.encode('utf-8' if media else 'latin-1') if isinstance(payload, str) else payload)
    control_number = ''
    if media:
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_EDI_BYTES:
            raise ValueError('AS2 payload must contain 1 byte to 8 MiB; map text or original bytes as Base64')
    else:
        interchange = _edi(content, profile)
        _edi_ids(interchange, profile, 'outbound')
        media, control_number = EDI_TYPES[interchange['format']], interchange['controlNumber']
    entity = _entity(media, content)
    if _flag(profile, 'compressOutbound', False):
        entity = _entity(COMPRESSED_TYPE, _compress(entity))
    mic = _mic(entity)
    message_id = _message_id(config.get('messageId') or f'{uuid.uuid4().hex}@mina.invalid')
    if len(message_id) > 996:
        raise ValueError('AS2 outbound Message-ID including brackets exceeds 998 characters')
    content_type, body = _signed(entity, profile)
    if _flag(profile, 'encryptOutbound', True):
        content_type, body = _encrypt(content_type, body, profile)
    address = _string(profile.get('receiptAddress'), 'Disposition notification address')
    headers = {'Content-Type': content_type, 'AS2-Version': '1.1', 'AS2-From': _wire_id(local),
               'AS2-To': _wire_id(partner), 'Message-ID': f'<{message_id}>', 'Date': formatdate(usegmt=True),
               'Disposition-Notification-To': address, 'Disposition-Notification-Options':
               'signed-receipt-protocol=required, pkcs7-signature; signed-receipt-micalg=required, sha-256'}
    mode = profile.get('receiptMode') or 'synchronous'
    if mode not in ('synchronous', 'asynchronous'):
        raise ValueError('AS2 receipt mode must be synchronous or asynchronous')
    if mode == 'asynchronous':
        headers['Receipt-Delivery-Option'] = _endpoint(profile, profile.get('localMdnUrl') or '')
    claim = exchange(message_id, 'outbound', 'claim', entry={
        'fingerprint': _mic(body), 'mic': mic, 'controlNumber': control_number, 'receiptMode': mode})
    token = claim['claimToken']
    if mode == 'asynchronous':
        exchange(message_id, 'outbound', 'awaiting_mdn', token=token)
        _post(profile, headers, body)
        current = exchange(message_id, 'outbound', 'read')
        return {'messageId': message_id, 'status': current['status'], 'receiptMode': mode,
                'mic': mic, 'controlNumber': control_number,
                **({'receiptMicVerified': current['receiptMicVerified']} if 'receiptMicVerified' in current else {})}
    try:
        response, data = _post(profile, headers, body)
        accepted, mic_verified = _verify_mdn(response, data, profile, message_id, mic)
    except Exception:
        exchange(message_id, 'outbound', 'failed', token=token)
        raise
    result = exchange(message_id, 'outbound', 'processed' if accepted else 'rejected', token=token,
                      entry={'receiptMicVerified': mic_verified},
                    receipt={'headers': response, 'binaryContent': _base64(data)})
    return {**result, 'mic': mic, 'controlNumber': control_number, 'accepted': accepted,
            'receiptMicVerified': mic_verified}


def execute(operation, config, payload, profile_id='', profile=None):
    try:
        if operation == 'edi_parse':
            content = _unbase64(config['contentBase64'], MAX_EDI_BYTES) if config.get('contentBase64') is not None else payload
            return _edi(content, config)
        if operation == 'edi_render':
            return render_edi(payload, _rules(config), config.get('allowedTransactionTypes'))
        if operation == 'edi_ack_create':
            return generate_ack(payload, config)
        if operation == 'edi_ack_read':
            return read_ack(payload)
        if not profile_id or profile is None:
            raise ValueError('Select a shared Trading Partner connection')
        return _exchange(operation, profile_id, profile, config, payload)
    except (ValueError, OSError, TypeError, KeyError) as error:
        raise TradingPartnerError(str(error)) from None
