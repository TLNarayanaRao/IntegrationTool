"""Shared Python HTTP transport and authentication for Studio and both exports."""
from __future__ import annotations
import atexit, base64, hashlib, hmac, ipaddress, json, math, os, re, ssl, tempfile, threading, time, urllib.parse, uuid
from pathlib import Path
import httpx
from .rest_contract import operation_config, validate_parameters
from .http_messages import request_config, mime_body, response_tree

class HTTPFault(ValueError):
    def __init__(self, message, fault_type='HTTP_SECURITY', status=401):
        super().__init__(message); self.fault_type=fault_type; self.status=status

def boolean(value, default=False):
    if value is None or value == '': return default
    return str(value).lower() in ('true','1','yes','on')

def number(cfg,key,default,minimum=0,maximum=1000000000):
    try: value=float(default if cfg.get(key) in (None,'') else cfg[key])
    except (ValueError,TypeError): raise HTTPFault(f'{key} must be a number','HTTP_CONFIGURATION',400)
    if not math.isfinite(value) or not minimum <= value <= maximum: raise HTTPFault(f'{key} must be between {minimum} and {maximum}','HTTP_CONFIGURATION',400)
    return value

def object_value(value,label):
    if value in (None,''): return {}
    if isinstance(value,str):
        try: value=json.loads(value)
        except ValueError: raise HTTPFault(f'{label} must be a JSON object','HTTP_CONFIGURATION',400)
    if not isinstance(value,dict): raise HTTPFault(f'{label} must be a JSON object','HTTP_CONFIGURATION',400)
    return value

def merged(connection,activity):
    result={**(connection or {}),**(activity or {})}
    result['headers']={**object_value((connection or {}).get('headers'),'Default headers'),**object_value((activity or {}).get('headers'),'Headers')}
    result['query']={**object_value((connection or {}).get('query'),'Default query'),**object_value((activity or {}).get('query'),'Query')}
    return result

def _store(path,kind,password,alias=''):
    if not path: return b'',b'',b''
    raw=Path(path).expanduser().read_bytes()
    if kind.upper() in ('PKCS12','P12','PFX'):
        from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
        key,cert,chain=pkcs12.load_key_and_certificates(raw,password.encode() if password else None)
        return (cert.public_bytes(Encoding.PEM) if cert else b'')+b''.join(item.public_bytes(Encoding.PEM) for item in chain or []), key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()) if key else b'', b''.join(item.public_bytes(Encoding.PEM) for item in ([cert] if cert else [])+list(chain or []))
    if kind.upper() == 'JKS':
        import shutil, subprocess
        executable=shutil.which('keytool')
        if not executable and os.environ.get('JAVA_HOME'):
            candidate=Path(os.environ['JAVA_HOME'])/'bin'/('keytool.exe' if os.name=='nt' else 'keytool')
            if candidate.is_file():executable=str(candidate)
        if not executable:raise HTTPFault('JKS stores require Java keytool or convert the store to PKCS12','HTTP_CONFIGURATION',400)
        with tempfile.TemporaryDirectory(prefix='mina-jks-') as directory:
            target=Path(directory)/'converted.p12';destination_password=uuid.uuid4().hex
            arguments=[executable,'-importkeystore','-srckeystore',str(Path(path).expanduser()),'-srcstoretype','JKS','-srcstorepass:env','MINA_SOURCE_STORE_PASS','-destkeystore',str(target),'-deststoretype','PKCS12','-deststorepass:env','MINA_DEST_STORE_PASS','-noprompt']
            if alias:arguments+=['-srcalias',alias]
            result=subprocess.run(arguments,env={**os.environ,'MINA_SOURCE_STORE_PASS':password,'MINA_DEST_STORE_PASS':destination_password},stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            if result.returncode:raise HTTPFault('JKS conversion failed; check store password and alias','HTTP_CONFIGURATION',400)
            return _store(target,'PKCS12',destination_password)
    if kind.upper() != 'PEM': raise HTTPFault('Store type must be PEM, PKCS12 or JKS','HTTP_CONFIGURATION',400)
    return raw,b'',raw

def certificate_files(folder):
    """Read ordinary certificate files; OpenSSL hash-directory names are unnecessary."""
    directory=Path(str(folder)).expanduser()
    try:
        if not directory.is_dir():raise ValueError()
        files=sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in ('.pem','.crt','.cer','.der')),key=lambda path:path.name.lower())
        if not files:raise HTTPFault('Trusted certificate folder contains no PEM/CRT/CER/DER certificates','HTTP_CONFIGURATION',400)
        if len(files)>256:raise HTTPFault('Trusted certificate folder exceeds 256 certificate files','HTTP_CONFIGURATION',400)
        return files
    except HTTPFault:raise
    except (OSError,ValueError):raise HTTPFault('Trusted certificate folder does not exist or cannot be read','HTTP_CONFIGURATION',400) from None

def load_certificate_folder(ctx,folder):
    total=0
    for path in certificate_files(folder):
        try:
            with path.open('rb') as source:raw=source.read(8*1024**2+1)
            total+=len(raw)
            if len(raw)>8*1024**2 or total>32*1024**2:raise HTTPFault('Trusted certificate folder exceeds certificate size limits','HTTP_CONFIGURATION',400)
            if b'-----BEGIN' in raw:
                if b'PRIVATE KEY-----' in raw:raise ValueError()
                certificates=re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',raw,re.S)
                if not certificates:raise ValueError()
                pem=b'\n'.join(certificates).decode('ascii')
            else:pem=ssl.DER_cert_to_PEM_cert(raw)
            ctx.load_verify_locations(cadata=pem)
        except HTTPFault:raise
        except (OSError,ValueError,ssl.SSLError):raise HTTPFault(f'Cannot load trusted certificate file: {path.name}','HTTP_CONFIGURATION',400) from None
    # Intermediates assist path building; a chain must still reach a trusted root.
    if hasattr(ssl,'VERIFY_X509_PARTIAL_CHAIN'):ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN

def tls_context(cfg,server=False):
    verify=boolean(cfg.get('verifyTls'),True)
    ctx=ssl.create_default_context(ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH)
    if not server and not verify: ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    version=str(cfg.get('tlsVersion') or 'TLSv1.2')
    versions={'TLSv1.2':ssl.TLSVersion.TLSv1_2,'TLSv1.3':ssl.TLSVersion.TLSv1_3}
    if version not in versions: raise HTTPFault('Only TLSv1.2 and TLSv1.3 are supported','HTTP_CONFIGURATION',400)
    ctx.minimum_version=versions[version]
    if cfg.get('maximumTlsVersion'):
        ctx.maximum_version=versions[cfg['maximumTlsVersion']]
        if ctx.maximum_version<ctx.minimum_version: raise HTTPFault('Maximum TLS version precedes minimum','HTTP_CONFIGURATION',400)
    if cfg.get('cipherSuites'): ctx.set_ciphers(str(cfg['cipherSuites']))
    ca=cfg.get('trustStoreFile') or cfg.get('certificateAuthorityFile')
    if ca:
        _,_,trust=_store(ca,str(cfg.get('trustStoreType') or 'PEM'),str(cfg.get('trustStorePassword') or ''))
        if not trust: raise HTTPFault('Trust store contains no certificates','HTTP_CONFIGURATION',400)
        ctx.load_verify_locations(cadata=trust.decode())
    if cfg.get('trustedCertificateFolder'):load_certificate_folder(ctx,cfg['trustedCertificateFolder'])
    if cfg.get('crlFile'):
        ctx.load_verify_locations(cafile=str(cfg['crlFile']));ctx.verify_flags|=ssl.VERIFY_CRL_CHECK_CHAIN
    identity=cfg.get('identityStoreFile');cert=cfg.get('certificateFile') or cfg.get('clientCertificateFile');key=cfg.get('privateKeyFile') or cfg.get('clientKeyFile')
    if identity:
        cert_data,key_data,_=_store(identity,str(cfg.get('identityStoreType') or 'PKCS12'),str(cfg.get('identityStorePassword') or ''),str(cfg.get('keyAlias') or ''))
        if not cert_data or not key_data: raise HTTPFault('Identity store needs a private key and certificate','HTTP_CONFIGURATION',400)
        with tempfile.TemporaryDirectory(prefix='mina-tls-') as folder:
            cp=Path(folder)/'cert.pem';kp=Path(folder)/'key.pem';cp.write_bytes(cert_data);kp.write_bytes(key_data);os.chmod(kp,0o600);ctx.load_cert_chain(cp,kp)
    elif cert:
        ctx.load_cert_chain(str(cert),str(key) if key else None,cfg.get('privateKeyPassword') or cfg.get('clientKeyPassword') or None)
    elif server: raise HTTPFault('HTTPS server requires an identity store or certificate and private key','HTTP_CONFIGURATION',400)
    if server:
        mode=str(cfg.get('clientAuthentication') or 'none').lower()
        if mode not in ('none','optional','required'): raise HTTPFault('Invalid client certificate authentication mode','HTTP_CONFIGURATION',400)
        ctx.verify_mode={'none':ssl.CERT_NONE,'optional':ssl.CERT_OPTIONAL,'required':ssl.CERT_REQUIRED}[mode]
    return ctx

def validate_authentication(cfg,server=False):
    scheme=str(cfg.get('authentication') or 'None').lower()
    allowed={'none','basic','bearer','jwt','hmac','oauth2','certificate'}|({'ldap'} if server else {'digest','ntlm'})
    if scheme not in allowed:raise HTTPFault('Authentication is not supported for this connection role','HTTP_CONFIGURATION',400)
    def require(key,label):
        if not cfg.get(key):raise HTTPFault(label+' is required','HTTP_CONFIGURATION',400)
    if scheme in ('basic','digest','ntlm'):require('username','Username');require('password','Password')
    elif scheme=='bearer':require('bearerToken','Bearer token')
    elif scheme=='hmac':require('hmacSecret','HMAC secret')
    elif scheme=='jwt' and not (not server and cfg.get('jwtToken')):
        if not _jwt_key(cfg,sign=not server):raise HTTPFault('JWT key is required','HTTP_CONFIGURATION',400)
    elif scheme=='oauth2':
        require('oauthClientId','OAuth client ID')
        secure_url(str(cfg.get('oauthIntrospectionUrl' if server else 'oauthTokenUrl') or ''),{**cfg,'confidentiality':True})
    elif scheme=='ldap':
        require('ldapUrl','LDAP URL')
        if not cfg.get('ldapUserDnTemplate') and not cfg.get('ldapBaseDn'):raise HTTPFault('LDAP user DN template or search base is required','HTTP_CONFIGURATION',400)
        if not str(cfg['ldapUrl']).startswith('ldaps://') and not boolean(cfg.get('ldapStartTls'),True):raise HTTPFault('LDAP requires LDAPS or StartTLS','HTTP_CONFIGURATION',400)
    elif scheme=='certificate' and not server and not (cfg.get('identityStoreFile') or cfg.get('clientCertificateFile') or cfg.get('certificateFile')):raise HTTPFault('Client identity certificate is required','HTTP_CONFIGURATION',400)

def secure_url(url,cfg):
    parts=urllib.parse.urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.fragment: raise HTTPFault('HTTP URL must have a host, no embedded credentials or fragment','HTTP_CONFIGURATION',400)
    if (str(cfg.get('authentication') or '').lower()=='certificate' or boolean(cfg.get('defaultConfidentiality')) or boolean(cfg.get('confidentiality')) or boolean(cfg.get('tlsEnabled'))) and parts.scheme!='https': raise HTTPFault('Confidentiality requires HTTPS','HTTP_CONFIGURATION',400)
    return url

def _seconds(cfg,ms,seconds,default):
    value=number(cfg,ms,default*1000)/1000 if ms in cfg and cfg[ms] not in ('',None) else number(cfg,seconds,default)
    return value or None

_POOL={};_POOL_LOCK=threading.RLock();_TOKENS={};_TOKEN_SCOPES={};_NONCES={};_SECURITY_LOCK=threading.RLock()

def close_clients(scope=None):
    with _POOL_LOCK:
        keys=[key for key,client in _POOL.items() if scope is None or client._mina_scope==scope]
        clients=[_POOL.pop(key) for key in keys]
    for client in clients: client.close()
    with _SECURITY_LOCK:
        for key in list(_TOKENS):
            if scope is None or _TOKEN_SCOPES.get(key)==scope:_TOKENS.pop(key,None);_TOKEN_SCOPES.pop(key,None)
atexit.register(close_clients)

_NETWORK=('verifyTls','tlsVersion','maximumTlsVersion','cipherSuites','certificateAuthorityFile','trustStoreFile','trustStoreType','trustStorePassword','identityStoreFile','identityStoreType','identityStorePassword','keyAlias','certificateFile','privateKeyFile','privateKeyPassword','clientCertificateFile','clientKeyFile','clientKeyPassword','crlFile','proxyHost','proxyPort','proxyUrl','proxyUsername','proxyPassword','httpVersion','maximumTotalConnections','maximumConnectionsPerHost','idleConnectionTimeoutMs','disableConnectionPooling','usePersistentConnections','authentication','username','password','bearerToken','oauthClientId','oauthClientSecret','oauthTokenUrl','oauthScope','oauthGrantType','oauthRefreshToken','oauthAuthorizationCode','oauthRedirectUri','jwtSecret','jwtToken','hmacSecret','hmacKeyId','enableCookies','resourceId','_httpScope','baseUrl','oauthCodeVerifier','oauthClientAuthentication','jwtPrivateKeyFile','jwtPublicKeyFile')
def _fingerprint(cfg):
    values={key:cfg.get(key) for key in _NETWORK}
    folder=cfg.get('trustedCertificateFolder');values['trustedCertificateFolder']=folder
    if folder:
        try:values['_certificateFiles']=[(str(path),path.stat().st_mtime_ns,path.stat().st_size) for path in certificate_files(folder)]
        except OSError:raise HTTPFault('Trusted certificate folder cannot be read','HTTP_CONFIGURATION',400) from None
    return hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()

def client_for(cfg):
    key=_fingerprint(cfg)
    with _POOL_LOCK:
        if key in _POOL:return _POOL[key]
        if len(_POOL)>=128: raise HTTPFault('HTTP shared client limit reached; close unused clients','HTTP_CONFIGURATION',400)
        total=int(number(cfg,'maximumTotalConnections',200,1,100000));per=int(number(cfg,'maximumConnectionsPerHost',20,1,total))
        persistent=boolean(cfg.get('usePersistentConnections'),True) and not boolean(cfg.get('disableConnectionPooling'))
        proxy=cfg.get('proxyUrl')
        if not proxy and cfg.get('proxyHost'):
            credentials=urllib.parse.quote(str(cfg.get('proxyUsername') or ''),safe='')+':'+urllib.parse.quote(str(cfg.get('proxyPassword') or ''),safe='')+'@' if cfg.get('proxyUsername') else ''
            proxy=f'http://{credentials}{cfg["proxyHost"]}:{int(number(cfg,"proxyPort",8080,1,65535))}'
        version=str(cfg.get('httpVersion') or '1.1')
        if version not in ('1.1','2'): raise HTTPFault('Client HTTP version must be 1.1 or 2','HTTP_CONFIGURATION',400)
        import http.cookiejar
        class RejectCookies(http.cookiejar.DefaultCookiePolicy):
            def set_ok(self,cookie,request):return False
        cookies=None if boolean(cfg.get('enableCookies')) else http.cookiejar.CookieJar(policy=RejectCookies())
        client=httpx.Client(cookies=cookies,verify=tls_context(cfg),proxy=proxy or None,http2=version=='2',trust_env=False,limits=httpx.Limits(max_connections=total,max_keepalive_connections=total if persistent else 0,keepalive_expiry=number(cfg,'idleConnectionTimeoutMs',30000)/1000),timeout=30)
        client._mina_route_limit=per;client._mina_routes={};client._mina_lock=threading.Lock();client._mina_scope=cfg.get('_httpScope');_POOL[key]=client
        return client

def _jwt_key(cfg,sign=False):
    key=cfg.get('jwtPrivateKeyFile') if sign else cfg.get('jwtPublicKeyFile')
    return Path(key).read_text(encoding='utf-8') if key else str(cfg.get('jwtSecret') or '')

def jwt_token(cfg):
    if cfg.get('jwtToken'):return str(cfg['jwtToken'])
    import jwt
    algorithm=str(cfg.get('jwtAlgorithm') or 'HS256')
    if algorithm not in ('HS256','HS384','HS512','RS256','RS384','RS512','ES256','ES384'):raise HTTPFault('Unsupported JWT algorithm','HTTP_CONFIGURATION',400)
    key=_jwt_key(cfg,True)
    if not key:raise HTTPFault('JWT signing key is required','HTTP_CONFIGURATION',400)
    now=int(time.time());claims=object_value(cfg.get('jwtClaims'),'JWT claims');claims={**claims,'iat':now,'exp':now+int(number(cfg,'jwtLifetimeSeconds',300,1,86400))}
    if cfg.get('jwtIssuer'):claims['iss']=cfg['jwtIssuer']
    if cfg.get('jwtAudience'):claims['aud']=cfg['jwtAudience']
    return jwt.encode(claims,key,algorithm=algorithm)

def _oauth(cfg,client):
    token_url=secure_url(str(cfg.get('oauthTokenUrl') or ''),{**cfg,'confidentiality':True})
    key=hashlib.sha256((_fingerprint(cfg)+json.dumps({k:cfg.get(k) for k in ('oauthTokenUrl','oauthClientId','oauthClientSecret','oauthScope','oauthGrantType','oauthRefreshToken','oauthAuthorizationCode','oauthRedirectUri')},sort_keys=True)).encode()).hexdigest()
    # Lock prevents simultaneous refreshes and authorization-code re-use.
    with _SECURITY_LOCK:
        cached=_TOKENS.get(key)
        if cached and cached[1]>time.time()+5:return cached[0]
        grant=str(cfg.get('oauthGrantType') or 'client_credentials');data={'grant_type':grant}
        if cached and grant in ('authorization_code','refresh_token'):
            if not cached[2]:raise HTTPFault('OAuth token expired; reauthorize or supply a refresh token','HTTP_SECURITY',401)
            grant='refresh_token';data={'grant_type':grant,'refresh_token':cached[2]}
        if cfg.get('oauthScope'):data['scope']=cfg['oauthScope']
        if grant=='refresh_token':data.setdefault('refresh_token',cfg.get('oauthRefreshToken'))
        elif grant=='authorization_code':data.update(code=cfg.get('oauthAuthorizationCode'),redirect_uri=cfg.get('oauthRedirectUri'))
        elif grant!='client_credentials':raise HTTPFault('Unsupported OAuth grant','HTTP_CONFIGURATION',400)
        if cfg.get('oauthCodeVerifier'):data['code_verifier']=cfg['oauthCodeVerifier']
        cid=str(cfg.get('oauthClientId') or '');secret=str(cfg.get('oauthClientSecret') or '')
        if not cid:raise HTTPFault('OAuth client ID is required','HTTP_CONFIGURATION',400)
        auth=(cid,secret) if str(cfg.get('oauthClientAuthentication') or 'basic')=='basic' else None
        if not auth:data.update(client_id=cid,client_secret=secret)
        try:
            response=client.post(token_url,data=data,auth=auth,timeout=number(cfg,'oauthTimeoutSeconds',30,1,300),follow_redirects=False);response.raise_for_status();body=response.json()
            token=body['access_token'];expires=float(body.get('expires_in',60))
            if not token or str(body.get('token_type','Bearer')).lower()!='bearer' or not math.isfinite(expires) or expires<=0:raise ValueError()
        except Exception:raise HTTPFault('OAuth token exchange failed','HTTP_SECURITY',401) from None
        if len(_TOKENS)>=1024:_TOKENS.clear();_TOKEN_SCOPES.clear()
        _TOKEN_SCOPES[key]=cfg.get('_httpScope');_TOKENS[key]=(str(token),time.time()+expires,body.get('refresh_token') or (cached[2] if cached else cfg.get('oauthRefreshToken')));return str(token)

def hmac_signature(cfg,method,target,body,timestamp,nonce):
    algorithm=str(cfg.get('hmacAlgorithm') or 'SHA256').upper()
    if algorithm not in ('SHA256','SHA384','SHA512'):raise HTTPFault('Unsupported HMAC algorithm','HTTP_CONFIGURATION',400)
    secret=str(cfg.get('hmacSecret') or '')
    if not secret:raise HTTPFault('HMAC secret is required','HTTP_CONFIGURATION',400)
    canonical='\n'.join((method.upper(),target,str(timestamp),nonce,hashlib.sha256(body).hexdigest()))
    return base64.b64encode(hmac.new(secret.encode(),canonical.encode(),getattr(hashlib,algorithm.lower())).digest()).decode()

class NonPreemptiveBasic(httpx.Auth):
    requires_request_body=True
    def __init__(self,username,password):
        self.header='Basic '+base64.b64encode((username+':'+password).encode()).decode()
    def auth_flow(self,request):
        response=yield request
        if response.status_code==401 and 'basic' in response.headers.get('www-authenticate','').lower():
            request.headers['Authorization']=self.header
            yield request

def request(cfg,connection=None):
    cfg=merged(connection,cfg)
    try:cfg=request_config(cfg)
    except (ValueError,TypeError,KeyError) as error:raise HTTPFault(str(error),'HTTP_CONFIGURATION',400) from None
    try:cfg=operation_config(cfg)
    except (ValueError,KeyError,TypeError) as error:raise HTTPFault('Invalid REST contract: '+str(error),'HTTP_CONFIGURATION',400) from None
    validate_authentication(cfg)
    if cfg.get('connectorMode')=='server':raise HTTPFault('Outbound call requires a client shared connection','HTTP_CONFIGURATION',400)
    url=str(cfg.get('url') or cfg.get('path') or '')
    if not urllib.parse.urlsplit(url).scheme:
        base=str(cfg.get('baseUrl') or f'{"https" if boolean(cfg.get("defaultConfidentiality")) or boolean(cfg.get("confidentiality")) or boolean(cfg.get("tlsEnabled")) else cfg.get("scheme") or "http"}://{cfg.get("host") or "localhost"}:{cfg.get("port") or (443 if cfg.get("scheme")=="https" else 80)}')
        url=base.rstrip('/')+'/'+('/'.join(part for part in (str(cfg.get('basePath') or '').strip('/'),url.lstrip('/')) if part))
    for name,value in object_value(cfg.get('pathParameters'),'URI parameters').items():url=url.replace('{'+name+'}',urllib.parse.quote(str(value),safe=''))
    if re.search(r'\{[^}]+\}',url):raise HTTPFault('Required URI parameter is missing','HTTP_CONFIGURATION',400)
    secure_url(url,cfg);method=str(cfg.get('method') or 'GET').upper()
    if method not in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'):raise HTTPFault('Unsupported HTTP method','HTTP_CONFIGURATION',400)
    headers={str(k).lower():([str(item) for item in v] if isinstance(v,list) else str(v)) for k,v in cfg['headers'].items()}
    if any('\r' in k+str(v) or '\n' in k+str(v) for k,v in headers.items()):raise HTTPFault('HTTP headers cannot contain newlines','HTTP_CONFIGURATION',400)
    if cfg.get('accept'):headers.setdefault('accept',str(cfg['accept']))
    if cfg.get('contentType'):headers.setdefault('content-type',str(cfg['contentType']))
    body=cfg.get('body');mode=str(cfg.get('sendBodyMode') or 'ALWAYS').upper()
    errors=validate_parameters(cfg,object_value(cfg.get('pathParameters'),'URI parameters'),cfg['query'],headers,body)
    if errors:raise HTTPFault('; '.join(errors),'REST_VALIDATION',400)
    if boolean(cfg.get('validateRequest'),bool(cfg.get('openApiDocument'))) and cfg.get('requestSchema'):
        from .mapper import validate_output
        if validate_output(body,cfg['requestSchema']):raise HTTPFault('Request schema validation failed','REST_VALIDATION',400)
    if mode not in ('ALWAYS','AUTO','NEVER'):raise HTTPFault('Invalid send body mode','HTTP_CONFIGURATION',400)
    if mode=='NEVER' or mode=='AUTO' and method in ('GET','HEAD','OPTIONS'):body=None
    body_type=str(cfg.get('bodyType') or 'json').lower()
    if '_mimeEnvelope' in cfg:
        try:raw,mime_type=mime_body(cfg['_mimeEnvelope'],int(number(cfg,'maxRequestBodyBytes',64*1024**2,1)),body,str(headers.get('content-type') or headers.get('Content-Type') or cfg.get('contentType') or 'application/json'))
        except (ValueError,TypeError,OSError) as error:raise HTTPFault(str(error),'HTTP_CONFIGURATION',400) from None
        headers={key:value for key,value in headers.items() if key.lower()!='content-type'};headers['content-type']=mime_type
    elif body is None:raw=b''
    elif body_type=='form':raw=urllib.parse.urlencode(object_value(body,'Form body'),doseq=True).encode();headers.setdefault('content-type','application/x-www-form-urlencoded')
    elif body_type=='file':
        source=Path(str(body))
        if source.stat().st_size>number(cfg,'maxRequestBodyBytes',64*1024**2,1):raise HTTPFault('HTTP request body limit exceeded','HTTP_BAD_REQUEST',413)
        raw=source.read_bytes()
    elif isinstance(body,(bytes,bytearray)):raw=bytes(body)
    elif body_type=='json':raw=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode();headers.setdefault('content-type','application/json')
    else:raw=str(body).encode(str(cfg.get('encoding') or 'utf-8'))
    if len(raw)>number(cfg,'maxRequestBodyBytes',64*1024**2,1):raise HTTPFault('HTTP request body limit exceeded','HTTP_BAD_REQUEST',413)
    client=client_for(cfg);auth=None;scheme=str(cfg.get('authentication') or 'None').lower()
    if scheme in ('basic','digest'):
        if not cfg.get('username') or not cfg.get('password'):raise HTTPFault('Authentication credentials are required','HTTP_CONFIGURATION',400)
        auth=(NonPreemptiveBasic(str(cfg['username']),str(cfg['password'])) if boolean(cfg.get('nonPreemptiveAuthentication')) else httpx.BasicAuth(str(cfg['username']),str(cfg['password']))) if scheme=='basic' else httpx.DigestAuth(str(cfg['username']),str(cfg['password']))
    elif scheme in ('bearer','jwt','oauth2'):
        token=_oauth(cfg,client) if scheme=='oauth2' else jwt_token(cfg) if scheme=='jwt' else str(cfg.get('bearerToken') or '')
        if not token:raise HTTPFault('Bearer token is required','HTTP_CONFIGURATION',400)
        headers['authorization']='Bearer '+token
    elif scheme=='ntlm':
        from httpx_ntlm import HttpNtlmAuth
        auth=HttpNtlmAuth(str(cfg.get('username') or ''),str(cfg.get('password') or ''))
    elif scheme not in ('none','certificate','hmac'):raise HTTPFault('Unsupported outbound authentication','HTTP_CONFIGURATION',400)
    if scheme=='certificate' and not (cfg.get('identityStoreFile') or cfg.get('certificateFile') or cfg.get('clientCertificateFile')):raise HTTPFault('Certificate authentication requires an identity','HTTP_CONFIGURATION',400)
    timeout=httpx.Timeout(connect=_seconds(cfg,'connectionTimeoutMs','connectTimeoutSeconds',30),read=_seconds(cfg,'socketTimeoutMs','timeoutSeconds',60),write=_seconds(cfg,'writeTimeoutMs','writeTimeoutSeconds',60),pool=_seconds(cfg,'poolTimeoutMs','poolTimeoutSeconds',30))
    if cfg.get('timeout') not in (None,''):timeout=httpx.Timeout(number(cfg,'timeout',30) or None,connect=timeout.connect)
    activity_limit=number(cfg,'activityTimeoutSeconds',180,1)
    for phase in ('connect','read','write','pool'):
        value=getattr(timeout,phase)
        if value is None or value>activity_limit:setattr(timeout,phase,activity_limit)
    started=time.monotonic();maximum=int(number(cfg,'maxResponseBodyBytes',64*1024**2,1));retries=int(number(cfg,'retryCount',0,0,10))
    # Per-route gates complement HTTPX's global connection limit.
    route=urllib.parse.urlsplit(url).netloc
    with client._mina_lock:gate=client._mina_routes.setdefault(route,threading.BoundedSemaphore(client._mina_route_limit))
    acquired=gate.acquire(timeout=timeout.pool)
    if not acquired:raise HTTPFault('HTTP pool timeout','HTTP_TIMEOUT',504)
    try:
        for attempt in range(retries+1):
            try:
                pairs=[(key,item) for key,value in headers.items() for item in (value if isinstance(value,list) else [value])]
                query=httpx.QueryParams(urllib.parse.urlsplit(url).query).merge(cfg['query']) if cfg['query'] else None
                req=client.build_request(method,url,params=query,headers=pairs,content=raw if body is not None or '_mimeEnvelope' in cfg else None,timeout=timeout)
                if not boolean(cfg.get('enableCookies')) and not any(key.lower()=='cookie' for key in headers):req.headers.pop('cookie',None)
                if scheme=='hmac':
                    if boolean(cfg.get('followRedirects')):raise HTTPFault('Signed HMAC requests cannot follow redirects','HTTP_CONFIGURATION',400)
                    stamp=str(int(time.time()));nonce=uuid.uuid4().hex
                    req.headers['X-MINA-Timestamp']=stamp;req.headers['X-MINA-Nonce']=nonce;req.headers['X-MINA-Key-Id']=str(cfg.get('hmacKeyId') or 'default');req.headers['Authorization']='HMAC '+hmac_signature(cfg,method,req.url.raw_path.decode('ascii'),raw,stamp,nonce)
                if str(cfg.get('requestEntityProcessing') or 'BUFFERED').upper()=='CHUNKED' and (body is not None or '_mimeEnvelope' in cfg):
                    req.headers.pop('content-length',None);req.headers['Transfer-Encoding']='chunked'
                response=client.send(req,auth=auth,follow_redirects=boolean(cfg.get('followRedirects')),stream=True)
                try:
                    chunks=[];size=0
                    for chunk in response.iter_bytes(chunk_size=int(number(cfg,'responseBufferSize',65536,1024,1024**2))):
                        size+=len(chunk)
                        if size>maximum:raise HTTPFault('HTTP response body limit exceeded','HTTP_BAD_RESPONSE',502)
                        if cfg.get('activityTimeoutSeconds') and time.monotonic()-started>number(cfg,'activityTimeoutSeconds',180,1):raise HTTPFault('HTTP activity timeout','HTTP_TIMEOUT',504)
                        chunks.append(chunk)
                    data=b''.join(chunks);text=data.decode(response.encoding or 'utf-8',errors='replace')
                    try:value=json.loads(text)
                    except ValueError:value=text
                    valid=str(cfg.get('successStatusCodes') or '200-299')
                    accepted=any(int(part.split('-')[0])<=response.status_code<=int(part.split('-')[-1]) for part in valid.replace(' ','').split(','))
                    if boolean(cfg.get('raiseForStatus'),True) and not accepted:raise HTTPFault(f'HTTP response status {response.status_code}','HTTP_CLIENT_ERROR' if response.status_code<500 else 'HTTP_SERVER_ERROR',response.status_code)
                    schema=(cfg.get('_restResponseSchemas') or {}).get(str(response.status_code),cfg.get('responseSchema'))
                    if boolean(cfg.get('validateResponse'),bool(cfg.get('openApiDocument'))) and schema and accepted:
                        from .mapper import validate_output
                        if validate_output(value,schema):raise HTTPFault('Response schema validation failed','REST_VALIDATION',502)
                    result={'statusCode':response.status_code,'headers':dict(response.headers),'body':value,'elapsedMs':round((time.monotonic()-started)*1000),'httpVersion':response.http_version}
                    if cfg.get('_structuredRequest') or cfg.get('requestModel')=='tree':
                        try:tree=response_tree(response,data)
                        except (ValueError,LookupError) as error:raise HTTPFault(str(error),'HTTP_BAD_RESPONSE',502) from None
                        tree['body']=value;result['RestOutputResponse']=tree
                    return result
                finally:response.close()
            except (httpx.ConnectError,httpx.ConnectTimeout):
                if attempt>=retries:raise HTTPFault('HTTP connection failed','HTTP_CONNECTIVITY',502) from None
                time.sleep(number(cfg,'retryDelayMs',100,0,60000)/1000)
            except httpx.TimeoutException:raise HTTPFault('HTTP request timed out','HTTP_TIMEOUT',504) from None
            except httpx.HTTPError:raise HTTPFault('HTTP transport failed','HTTP_CONNECTIVITY',502) from None
    finally:gate.release()

def _basic(headers):
    try:
        kind,value=headers.get('authorization','').split(' ',1)
        if kind.lower()!='basic':raise ValueError()
        username,password=base64.b64decode(value,validate=True).decode().split(':',1)
        if not username or not password:raise ValueError()
        return username,password
    except Exception:raise HTTPFault('Authentication failed') from None

def ldap_authenticate(cfg,username,password):
    import ldap3
    if not username or not password:raise HTTPFault('Authentication failed')
    url=urllib.parse.urlsplit(str(cfg.get('ldapUrl') or ''))
    if url.scheme not in ('ldap','ldaps') or not url.hostname:raise HTTPFault('LDAP URL must use ldap or ldaps','HTTP_CONFIGURATION',400)
    if url.scheme=='ldap' and not boolean(cfg.get('ldapStartTls'),True):raise HTTPFault('LDAP requires LDAPS or StartTLS','HTTP_CONFIGURATION',400)
    tls=ldap3.Tls(validate=ssl.CERT_REQUIRED,ca_certs_file=cfg.get('ldapCaFile') or None,version=ssl.PROTOCOL_TLS_CLIENT)
    server=ldap3.Server(url.hostname,port=url.port or (636 if url.scheme=='ldaps' else 389),use_ssl=url.scheme=='ldaps',tls=tls,connect_timeout=number(cfg,'ldapTimeoutSeconds',10,1,60))
    connections=[]
    def connect(user,pwd):
        conn=ldap3.Connection(server,user=user,password=pwd,receive_timeout=int(number(cfg,'ldapTimeoutSeconds',10,1,60)),raise_exceptions=True);connections.append(conn);conn.open()
        if url.scheme=='ldap' and not conn.start_tls():raise HTTPFault('Authentication failed')
        if not conn.bind():raise HTTPFault('Authentication failed')
        return conn
    try:
        if cfg.get('ldapUserDnTemplate'):
            from ldap3.utils.dn import escape_rdn
            dn=str(cfg['ldapUserDnTemplate']).replace('{username}',escape_rdn(username))
        else:
            from ldap3.utils.conv import escape_filter_chars
            if not cfg.get('ldapBindDn') or not cfg.get('ldapBindPassword') or not cfg.get('ldapBaseDn'):raise HTTPFault('LDAP search requires bind DN, password and base DN','HTTP_CONFIGURATION',400)
            service=connect(cfg['ldapBindDn'],cfg['ldapBindPassword']);query=str(cfg.get('ldapSearchFilter') or '(uid={username})').replace('{username}',escape_filter_chars(username))
            service.search(cfg['ldapBaseDn'],query,attributes=['memberOf'],size_limit=2)
            if len(service.entries)!=1:raise HTTPFault('Authentication failed')
            dn=service.entries[0].entry_dn
            if cfg.get('ldapRequiredGroup') and str(cfg['ldapRequiredGroup']) not in list(service.entries[0].memberOf.values):raise HTTPFault('Authentication failed')
        user_connection=connect(dn,password)
        if cfg.get('ldapRequiredGroup') and cfg.get('ldapUserDnTemplate'):
            user_connection.search(dn,'(objectClass=*)',search_scope=ldap3.BASE,attributes=['memberOf'],size_limit=1)
            if len(user_connection.entries)!=1 or str(cfg['ldapRequiredGroup']) not in list(user_connection.entries[0].memberOf.values):raise HTTPFault('Authentication failed')
        return {'subject':username}
    except HTTPFault:raise
    except Exception:raise HTTPFault('Authentication failed') from None
    finally:
        for conn in connections:
            try:conn.unbind()
            except Exception:pass

def authorize(cfg,method,target,headers,body=b'',peer_verified=False):
    headers={str(k).lower():str(v) for k,v in headers.items()};scheme=str(cfg.get('authentication') or 'None').lower()
    if scheme=='none':return {}
    if scheme in ('basic','ldap'):
        user,pwd=_basic(headers)
        if scheme=='ldap':return ldap_authenticate(cfg,user,pwd)
        if not cfg.get('username') or not cfg.get('password') or not hmac.compare_digest(user,str(cfg['username'])) or not hmac.compare_digest(pwd,str(cfg['password'])):raise HTTPFault('Authentication failed')
        return {'subject':user}
    if scheme=='certificate':
        if not peer_verified:raise HTTPFault('Verified mutual TLS is required')
        return {'certificateVerified':True}
    authorization=headers.get('authorization','')
    if scheme=='bearer':
        token=str(cfg.get('bearerToken') or '')
        if not token or not hmac.compare_digest(authorization,'Bearer '+token):raise HTTPFault('Authentication failed')
        return {}
    if scheme=='jwt':
        import jwt
        if not authorization.startswith('Bearer ') or not authorization[7:]:raise HTTPFault('Authentication failed')
        alg=str(cfg.get('jwtAlgorithm') or 'HS256')
        if alg not in ('HS256','HS384','HS512','RS256','RS384','RS512','ES256','ES384'):raise HTTPFault('Unsupported JWT algorithm','HTTP_CONFIGURATION',400)
        key=_jwt_key(cfg)
        if not key:raise HTTPFault('JWT verification key is required','HTTP_CONFIGURATION',400)
        try:return jwt.decode(authorization.removeprefix('Bearer '),key,algorithms=[alg],issuer=cfg.get('jwtIssuer') or None,audience=cfg.get('jwtAudience') or None,leeway=number(cfg,'jwtClockSkewSeconds',30,0,300),options={'require':['exp'],'verify_aud':bool(cfg.get('jwtAudience'))})
        except Exception:raise HTTPFault('Authentication failed') from None
    if scheme=='oauth2':
        endpoint=secure_url(str(cfg.get('oauthIntrospectionUrl') or ''),{**cfg,'confidentiality':True})
        if not authorization.startswith('Bearer ') or not authorization[7:]:raise HTTPFault('Authentication failed')
        try:
            response=client_for(cfg).post(endpoint,data={'token':authorization[7:]},auth=(str(cfg.get('oauthClientId') or ''),str(cfg.get('oauthClientSecret') or '')),timeout=number(cfg,'oauthTimeoutSeconds',30,1,300),follow_redirects=False);response.raise_for_status();claims=response.json()
            if claims.get('active') is not True or claims.get('exp') is not None and float(claims['exp'])<=time.time():raise ValueError()
            scopes=set(str(claims.get('scope') or '').split())
            if not set(str(cfg.get('oauthRequiredScopes') or '').split()).issubset(scopes):raise ValueError()
            return claims
        except Exception:raise HTTPFault('Authentication failed') from None
    if scheme=='hmac':
        stamp=headers.get('x-mina-timestamp','');nonce=headers.get('x-mina-nonce','');window=number(cfg,'hmacClockSkewSeconds',300,1,3600)
        try:valid=abs(time.time()-int(stamp))<=window
        except ValueError:valid=False
        if not valid or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',nonce) or headers.get('x-mina-key-id')!=str(cfg.get('hmacKeyId') or 'default'):raise HTTPFault('Authentication failed')
        expected='HMAC '+hmac_signature(cfg,method,target,body,stamp,nonce)
        if not hmac.compare_digest(authorization,expected):raise HTTPFault('Authentication failed')
        with _SECURITY_LOCK:
            now=time.time()
            for key,deadline in list(_NONCES.items()):
                if deadline<now:del _NONCES[key]
            key=hashlib.sha256((str(cfg.get('hmacSecret'))+nonce).encode()).hexdigest()
            if key in _NONCES:raise HTTPFault('Authentication failed')
            if len(_NONCES)>=100000:raise HTTPFault('Authentication capacity exceeded','HTTP_SECURITY',503)
            _NONCES[key]=now+2*window
        return {'keyId':cfg.get('hmacKeyId') or 'default'}
    raise HTTPFault('Unsupported inbound authentication','HTTP_CONFIGURATION',400)
