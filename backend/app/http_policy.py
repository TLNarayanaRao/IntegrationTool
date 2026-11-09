"""HTTP resilience, JWT rotation and optional distributed request policies."""
from __future__ import annotations
import hashlib, json, math, random, threading, time, urllib.parse
from email.utils import parsedate_to_datetime

_LOCK=threading.RLock();_CIRCUITS={};_RATES={};_JWKS={};_REDIS={}

def validate_listener_policy(cfg):
    from .http_transport import number, boolean
    if str(cfg.get('policyStore') or 'memory') not in ('memory','redis'):raise fault('Policy storage must be memory or redis')
    if str(cfg.get('requestBodyMode') or 'memory') not in ('memory','file'):raise fault('Request body storage must be memory or file')
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
