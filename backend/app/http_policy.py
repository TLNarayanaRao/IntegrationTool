"""HTTP resilience, JWT rotation and optional distributed request policies."""
from __future__ import annotations
import hashlib, ipaddress, json, math, random, re, secrets, threading, time, urllib.parse
from collections import OrderedDict
from contextvars import ContextVar
from email.utils import parsedate_to_datetime

_LOCK=threading.RLock();_CIRCUITS={};_RATES={};_JWKS={};_REDIS={}
trace_context = ContextVar('mina_http_trace', default=None)
_HTTP_CACHE = OrderedDict()
_HTTP_CACHE_GENERATION = {}


def _cache_directives(value):
    return {key.strip().lower(): argument.strip().strip('"')
            for item in value.split(',') for key, _, argument in [item.partition('=')] if key.strip()}


def shared_cache_request(cfg, request):
    """Cache only explicitly public, unconditional GETs. No stale serving."""
    from .http_transport import boolean
    if not boolean(cfg.get('sharedHttpCache')) or boolean(cfg.get('enableCookies')):
        return None
    if str(cfg.get('authentication') or 'none').lower() != 'none' or boolean(cfg.get('followRedirects')):
        return None
    prohibited = ('authorization', 'cookie', 'range', 'if-match', 'if-none-match',
                  'if-modified-since', 'if-unmodified-since', 'if-range')
    directives = _cache_directives(request.headers.get('cache-control', ''))
    if (request.method != 'GET' or cfg.get('responseFile') or request.headers.get('content-length', '0') != '0'
            or any(name in request.headers for name in prohibited)
            or 'no-store' in directives or 'no-cache' in directives or 'max-age' in directives
            or 'min-fresh' in directives or request.headers.get('pragma')):
        return None
    scope = _http_cache_scope(cfg, request)
    with _LOCK:
        generation = _HTTP_CACHE_GENERATION.get(scope, '')
    headers = sorted((key, value) for key, value in request.headers.multi_items() if key != 'cache-control')
    fingerprint = json.dumps([scope, str(generation), str(request.url), cfg.get('httpVersion'), headers])
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def _http_cache_scope(cfg, request):
    return hashlib.sha256(json.dumps([cfg.get('_httpScope'), request.url.scheme, request.url.host,
                                      request.url.port], default=str).encode()).hexdigest()


def invalidate_shared_cache(cfg, request):
    from .http_transport import boolean
    if not boolean(cfg.get('sharedHttpCache')):
        return
    scope = _http_cache_scope(cfg, request)
    generation = secrets.token_hex(16)
    with _LOCK:
        if len(_HTTP_CACHE_GENERATION) >= 256 and scope not in _HTTP_CACHE_GENERATION:
            _HTTP_CACHE.clear()
            _HTTP_CACHE_GENERATION.clear()
        _HTTP_CACHE_GENERATION[scope] = generation


def cached_http_response(cache, request):
    import httpx
    if cache is None:
        return None
    with _LOCK:
        record = _HTTP_CACHE.get(cache)
    if not record or time.time() >= record['expires']:
        return None
    headers = [(name, value) for name, value in record['headers'] if name != 'age']
    headers.append(('age', str(max(0, int(time.time() - record['created'])))))
    return httpx.Response(200, headers=headers, content=record['content'],
                          request=request, extensions={'http_version':record['version'].encode()})


def store_http_response(cache, response, content):
    if cache is None or response.status_code != 200 or len(content) > 1024**2:
        return
    directives = _cache_directives(response.headers.get('cache-control', ''))
    vary = {name.strip().lower() for name in response.headers.get('vary', '').split(',')}
    if (('public' not in directives and 's-maxage' not in directives)
            or {'private', 'no-cache', 'no-store'} & directives.keys()
            or {'*', 'cache-control'} & vary or 'set-cookie' in response.headers):
        return
    now = time.time()
    try:
        age = max(0, int(response.headers.get('age', '0')))
        if response.headers.get('date'):
            age = max(age, int(now - parsedate_to_datetime(response.headers['date']).timestamp()))
        lifetime = min(3600, int(directives.get('s-maxage', directives.get('max-age', '0')))) - age
    except (ValueError, TypeError, OverflowError):
        return
    if lifetime <= 0:
        return
    record = {'created':now - age, 'expires':now + lifetime, 'content':content,
              'version':response.http_version, 'headers':[(name, value) for name, value in response.headers.multi_items()
                  if name not in ('content-encoding', 'transfer-encoding', 'content-length')]}
    with _LOCK:
        _HTTP_CACHE[cache] = record
        _HTTP_CACHE.move_to_end(cache)
        if len(_HTTP_CACHE) > 128:
            _HTTP_CACHE.popitem(last=False)


def trace_headers(headers):
    parent = headers.get('traceparent')
    valid = isinstance(parent, str) and re.fullmatch(r'00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}', parent)
    if valid and int(parent[3:35], 16) and int(parent[36:52], 16):
        return (parent[3:35], parent[53:], headers.get('tracestate'))
    return (secrets.token_hex(16), '00', None)


def outbound_trace(headers):
    trace_id, flags, state = trace_context.get() or trace_headers({})
    headers['traceparent'] = f'00-{trace_id}-{secrets.token_hex(8)}-{flags}'
    if isinstance(state, str) and len(state) <= 512 and state.isascii():
        headers.setdefault('tracestate', state)


def proxy_networks(cfg):
    return tuple(ipaddress.ip_network(item) for item in str(cfg.get('trustedProxyCidrs') or '').replace(',', ' ').split())


def client_address(cfg, peer, headers):
    networks = cfg.get('_trustedProxyNetworks') or ()
    forwarded = headers.get('x-forwarded-for')
    if not networks or not forwarded or not peer:
        return peer
    try:
        address = ipaddress.ip_address(peer)
        if not any(address in network for network in networks):
            return peer
        if isinstance(forwarded, list):
            forwarded = ','.join(forwarded)
        chain = [ipaddress.ip_address(item.strip()) for item in forwarded.split(',')]
    except ValueError:
        raise fault('Invalid forwarded client address', 'HTTP_BAD_REQUEST', 400) from None
    for address in reversed(chain):
        if not any(address in network for network in networks):
            break
    return str(address)


def representation_unchanged(request_headers, response_headers):
    headers = {str(name).lower(): value for name, value in response_headers.items()}
    condition = request_headers.get('if-none-match')
    if condition is not None:
        condition = ','.join(condition) if isinstance(condition, list) else condition
        if condition.strip() == '*':
            return True
        tag = headers.get('etag')
        if not isinstance(tag, str):
            return False
        matches = re.findall(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"', condition)
        return tag.removeprefix('W/') in [value.removeprefix('W/') for value in matches]
    try:
        since = parsedate_to_datetime(request_headers.get('if-modified-since', ''))
        modified = parsedate_to_datetime(headers.get('last-modified', ''))
        return modified <= since
    except (ValueError, TypeError, OverflowError):
        return False


def write_precondition(cfg):
    from .http_transport import boolean, object_value
    headers = {str(name).lower(): value for name, value in object_value(cfg.get('headers'), 'Headers').items()}
    exists = boolean(cfg.get('representationExists'), True)
    tag = str(cfg.get('currentETag') or '')
    if_match = headers.get('if-match')
    none_match = headers.get('if-none-match')
    since = headers.get('if-unmodified-since')
    def tags(condition):
        text = ','.join(condition) if isinstance(condition, list) else str(condition)
        if text.strip() == '*':
            return ['*']
        tag_pattern = r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"'
        if not re.fullmatch(rf'\s*{tag_pattern}(?:\s*,\s*{tag_pattern})*\s*', text):
            return []
        return re.findall(tag_pattern, text)
    def result(status):
        return {'allowed': status == 200, 'statusCode': status}
    if all(value is None for value in (if_match, none_match, since)) and boolean(cfg.get('requireWritePrecondition')):
        return result(428)
    if if_match is not None:
        candidates = tags(if_match)
        if not exists or ('*' not in candidates and (not tag or tag.startswith('W/') or tag not in candidates)):
            return result(412)
    elif since is not None and exists:
        try:
            limit = parsedate_to_datetime(since)
        except (TypeError, ValueError, OverflowError):
            limit = None  # An invalid request date is ignored.
        if limit is not None:
            try:
                modified = parsedate_to_datetime(cfg.get('currentLastModified', ''))
                if modified > limit:
                    return result(412)
            except (TypeError, ValueError, OverflowError):
                return result(412)
    if none_match is not None and exists:
        candidates = tags(none_match)
        if not candidates or '*' in candidates or tag and tag.removeprefix('W/') in [value.removeprefix('W/') for value in candidates]:
            return result(412)
    return result(200)

def validate_listener_policy(cfg):
    from .http_transport import number, boolean
    if str(cfg.get('policyStore') or 'memory') not in ('memory','redis'):raise fault('Policy storage must be memory or redis')
    if str(cfg.get('requestBodyMode') or 'memory') not in ('memory','file'):raise fault('Request body storage must be memory or file')
    if str(cfg.get('httpErrorFormat') or 'json') not in ('json','problem'):
        raise fault('HTTP error format must be json or problem')
    try:
        cfg['_trustedProxyNetworks'] = proxy_networks(cfg)
    except ValueError:
        raise fault('Trusted proxy networks must be valid IP addresses or CIDRs') from None
    origins=str(cfg.get('corsAllowedOrigins') or '').replace(',',' ').split()
    if '*' in origins and boolean(cfg.get('corsAllowCredentials')):raise fault('Credentialed CORS requires explicit origins')
    for origin in origins:
        if origin=='*':continue
        parsed=urllib.parse.urlsplit(origin)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:raise fault('CORS origins must be exact HTTP/HTTPS origins')
    for key,default,minimum,maximum in [('rateLimitRequests',0,0,10000000),('rateLimitWindowSeconds',60,1,86400),('corsMaxAgeSeconds',600,0,86400)]:number(cfg,key,default,minimum,maximum)
    if cfg.get('policyStore')=='redis' and not str(cfg.get('policyRedisUrl') or '').startswith(('redis://','rediss://')):raise fault('Redis policy storage requires a Redis connection URL')

def fault(message,kind='HTTP_CONFIGURATION',status=400,headers=None):
    from .http_transport import HTTPFault
    error=HTTPFault(message,kind,status);error.headers=headers or {};return error

def key_for(cfg, suffix=''):
    identity=[cfg.get('_httpScope'),cfg.get('resourceId'),cfg.get('baseUrl'),cfg.get('host'),cfg.get('port'),cfg.get('path'),suffix]
    return hashlib.sha256(json.dumps(identity,default=str).encode()).hexdigest()

def redis_client(cfg):
    url=str(cfg.get('policyRedisUrl') or '')
    if not url.startswith(('redis://','rediss://')):raise fault('A Redis policy URL is required')
    from .http_transport import number
    try:
        with _LOCK:
            if url not in _REDIS:
                if len(_REDIS)>=32:raise fault('Redis policy connection limit reached')
                import redis
                _REDIS[url]=redis.Redis.from_url(url,socket_connect_timeout=number(cfg,'policyTimeoutSeconds',3,1,30),socket_timeout=number(cfg,'policyTimeoutSeconds',3,1,30),max_connections=32)
            return _REDIS[url]
    except Exception:raise fault('Distributed HTTP policy unavailable','HTTP_SECURITY',503) from None

def claim_nonce(cfg, nonce, ttl):
    identity='mina:http:nonce:'+hashlib.sha256((str(cfg.get('hmacSecret'))+nonce).encode()).hexdigest()
    try:return bool(redis_client(cfg).set(identity,'1',nx=True,ex=max(1,math.ceil(ttl))))
    except Exception:raise fault('Distributed replay protection unavailable','HTTP_SECURITY',503) from None

def rate_limit(cfg, remote):
    from .http_transport import number
    limit=int(number(cfg,'rateLimitRequests',0,0,10000000))
    if not limit:return
    window=number(cfg,'rateLimitWindowSeconds',60,1,86400)
    # Fixed windows have bounded state and work with atomic Redis INCR/EXPIRE.
    now=time.time();bucket=int(now//window);identity=key_for(cfg,str(remote))
    ttl=max(1,math.ceil((bucket+1)*window-now))
    if str(cfg.get('policyStore') or 'memory')=='redis':
        try:
            count=redis_client(cfg).eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",1,f'mina:http:rate:{identity}:{bucket}',ttl+1)
        except Exception:raise fault('Distributed throttling unavailable','HTTP_SECURITY',503) from None
    else:
        with _LOCK:
            for key,record in list(_RATES.items()):
                if record[1]<=now:del _RATES[key]
            key=(identity,bucket)
            if key not in _RATES and len(_RATES)>=100000:raise fault('Rate limiter capacity exceeded','HTTP_SECURITY',503)
            count,deadline=_RATES.get(key,(0,(bucket+1)*window));count+=1;_RATES[key]=(count,deadline)
    if count>limit:raise fault('HTTP request rate limit exceeded','HTTP_RATE_LIMIT',429,{'Retry-After':str(ttl)})

def circuit_enter(cfg, route):
    from .http_transport import number
    threshold=int(number(cfg,'circuitFailureThreshold',0,0,10000))
    if not threshold:return None
    key=key_for(cfg,route)
    with _LOCK:
        if key not in _CIRCUITS and len(_CIRCUITS)>=4096:raise fault('Circuit breaker capacity exceeded')
        state=_CIRCUITS.setdefault(key,{'failures':0,'until':0,'probe':False})
        now=time.monotonic()
        if state['until']>now or state['probe']:raise fault('HTTP circuit is open','HTTP_CIRCUIT_OPEN',503)
        if state['until']:state['probe']=True
    return key

def circuit_result(cfg,key,failed):
    if key is None:return
    from .http_transport import number
    with _LOCK:
        state=_CIRCUITS[key];state['probe']=False
        if not failed:state.update(failures=0,until=0);return
        state['failures']+=1
        if state['failures']>=number(cfg,'circuitFailureThreshold',5,1):state['until']=time.monotonic()+number(cfg,'circuitResetSeconds',30,1,86400)

def retry_delay(cfg,attempt,response=None):
    from .http_transport import number, boolean
    maximum=number(cfg,'maxRetryDelayMs',30000,0,300000)/1000
    delay=min(maximum,number(cfg,'retryDelayMs',100,0,300000)/1000*2**attempt)
    if response is not None and boolean(cfg.get('respectRetryAfter'),True):
        raw=response.headers.get('retry-after')
        if raw:
            try:wait=float(raw)
            except ValueError:
                try:wait=parsedate_to_datetime(raw).timestamp()-time.time()
                except (ValueError,TypeError,OverflowError):wait=0
            if math.isfinite(wait):return min(maximum,max(delay,wait,0))
    return random.uniform(delay/2,delay) if boolean(cfg.get('retryJitter'),True) else delay

def retryable(cfg,method,headers,status):
    from .http_transport import boolean
    safe=method in ('GET','HEAD','OPTIONS','PUT','DELETE') or bool(headers.get('idempotency-key')) or boolean(cfg.get('retryNonIdempotent'))
    statuses={int(s.strip()) for s in str(cfg.get('retryStatusCodes') or '').split(',') if s.strip().isdigit()}
    return safe and status in statuses

def jwks_key(cfg,token):
    import jwt
    from .http_transport import client_for, number, secure_url
    url=secure_url(str(cfg.get('jwtJwksUrl') or ''),{**cfg,'confidentiality':True})
    algorithm=str(cfg.get('jwtAlgorithm') or 'RS256')
    if algorithm.startswith('HS'):raise fault('JWKS verification requires an asymmetric algorithm')
    header=jwt.get_unverified_header(token);kid=header.get('kid')
    if header.get('alg')!=algorithm or not isinstance(kid,str) or len(kid)>256:raise fault('JWT key/algorithm not accepted','HTTP_SECURITY',401)
    key=key_for(cfg,url+algorithm);now=time.monotonic()
    with _LOCK:
        cached=_JWKS.get(key);fresh=cached and cached['until']>now
        keys=cached['keys'] if fresh else {}
        if kid in keys:return keys[kid]
        # Unknown key IDs can trigger one refresh per cooldown, not per attacker token.
        if cached and now-cached['fetched']<number(cfg,'jwtJwksRefreshSeconds',10,1,300):raise fault('JWT signing key not found','HTTP_SECURITY',401)
        if len(_JWKS)>=128 and key not in _JWKS:raise fault('JWT key cache capacity exceeded','HTTP_SECURITY',503)
        try:
            with client_for(cfg).stream('GET',url,timeout=number(cfg,'jwtJwksTimeoutSeconds',5,1,60),follow_redirects=False) as response:
                response.raise_for_status();chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>1024**2:raise ValueError()
                    chunks.append(chunk)
            document=json.loads(b''.join(chunks));keys={}
            if len(document.get('keys',[]))>128:raise ValueError()
            for definition in document.get('keys',[]):
                if definition.get('use','sig')!='sig' or definition.get('alg',algorithm)!=algorithm or definition.get('kty') not in ('RSA','EC'):continue
                if 'key_ops' in definition and 'verify' not in definition['key_ops']:continue
                if definition.get('kid') in keys:raise ValueError()
                keys[definition.get('kid')]=jwt.PyJWK.from_dict(definition,algorithm=algorithm).key
            _JWKS[key]={'keys':keys,'until':now+number(cfg,'jwtJwksCacheSeconds',300,1,86400),'fetched':now}
        except Exception:raise fault('JWT key discovery unavailable','HTTP_SECURITY',503) from None
        if kid not in keys:raise fault('JWT signing key not found','HTTP_SECURITY',401)
        return keys[kid]

def cors_headers(cfg,headers,methods,preflight=False):
    from .http_transport import boolean, number
    origins=str(cfg.get('corsAllowedOrigins') or '').replace(',',' ').split();origin=headers.get('origin')
    if isinstance(origin,list):raise fault('Multiple Origin headers are not accepted','HTTP_SECURITY',400)
    if not origin or not origins:return {}
    credentials=boolean(cfg.get('corsAllowCredentials'))
    if '*' in origins and credentials:raise fault('Credentialed CORS requires explicit origins')
    if origin not in origins and '*' not in origins:raise fault('CORS origin is not allowed','HTTP_SECURITY',403)
    result={'Access-Control-Allow-Origin':'*' if '*' in origins else origin,'Vary':'Origin'}
    if credentials:result['Access-Control-Allow-Credentials']='true'
    if preflight:
        requested=headers.get('access-control-request-method','').upper()
        if requested not in methods:raise fault('CORS method is not allowed','HTTP_SECURITY',403)
        allowed={s.lower() for s in str(cfg.get('corsAllowedHeaders') or 'content-type,authorization').replace(',',' ').split()}
        wanted={s.strip().lower() for s in headers.get('access-control-request-headers','').split(',') if s.strip()}
        if not wanted.issubset(allowed) and '*' not in allowed:raise fault('CORS headers are not allowed','HTTP_SECURITY',403)
        result.update({'Access-Control-Allow-Methods':', '.join(sorted(methods)),'Access-Control-Allow-Headers':', '.join(sorted(wanted)),'Access-Control-Max-Age':str(int(number(cfg,'corsMaxAgeSeconds',600,0,86400)))})
        result['Vary']='Origin, Access-Control-Request-Method, Access-Control-Request-Headers'
    elif cfg.get('corsExposeHeaders'):result['Access-Control-Expose-Headers']=str(cfg['corsExposeHeaders'])
    return result
