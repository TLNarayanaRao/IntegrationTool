"""Offline Swagger UI shell and shared browser/Postman HMAC signing helper."""
import json,secrets

SIGNER = r'''
async function minaSign(request, secret, keyId, algorithm) {
  if (!crypto.subtle) throw new Error('HMAC signing requires HTTPS or localhost and Web Crypto support.');
  if (!secret) throw new Error('Enter the HMAC secret locally before sending a signed request.');
  const url = new URL(request.url);
  if (request.body != null && typeof request.body !== 'string') throw new Error('Automatic HMAC signing supports raw text/JSON bodies. Sign multipart/file requests with your API client.');
  const encoder = new TextEncoder();
  const body = encoder.encode(request.body || '');
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', body))).map(x=>x.toString(16).padStart(2,'0')).join('');
  const stamp = String(Math.floor(Date.now()/1000));
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16))).map(x=>x.toString(16).padStart(2,'0')).join('');
  const canonical = [request.method.toUpperCase(),url.pathname+url.search,stamp,nonce,digest].join('\n');
  const hash = {'SHA256':'SHA-256','SHA384':'SHA-384','SHA512':'SHA-512'}[algorithm];
  if (!hash) throw new Error('Unsupported MINA HMAC algorithm.');
  const key = await crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash},false,['sign']);
  const signature = btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.sign('HMAC',key,encoder.encode(canonical)))));
  return {'Authorization':'HMAC '+signature,'X-MINA-Key-Id':keyId,'X-MINA-Timestamp':stamp,'X-MINA-Nonce':nonce};
}
'''

def postman_hmac_script(algorithm):
    return SIGNER + r'''
let target = pm.variables.replaceIn(pm.request.url.toString());
pm.request.url.variables.each(v => { target=target.replace(':'+v.key,encodeURIComponent(pm.variables.replaceIn(v.value||''))); });
target = new URL(target).toString();
if (pm.request.body && pm.request.body.mode !== 'raw') throw new Error('MINA automatic HMAC signing requires a raw request body.');
const body = pm.request.body ? pm.variables.replaceIn(pm.request.body.raw || '') : '';
if (pm.request.body) pm.request.body.update({mode:'raw',raw:body});
pm.request.url.update(target);
const signed = await minaSign({method:pm.request.method,url:target,body},pm.variables.get('hmacSecret'),pm.variables.get('hmacKeyId')||'default',ALGORITHM);
Object.entries(signed).forEach(([key,value])=>pm.request.headers.upsert({key,value}));
'''.replace('ALGORITHM',json.dumps(algorithm))

def swagger_html(authentication='None',algorithm='SHA256',asset_base='/_mina/assets'):
    from .swagger_assets import VERSION
    nonce=secrets.token_urlsafe(24)
    mode='basic' if authentication.lower() in ('basic','ldap') else 'hmac' if authentication.lower()=='hmac' else 'bearer' if authentication.lower() in ('jwt','oauth2','bearer') else 'none'
    script=SIGNER+r'''
let ui;
const status=document.getElementById('access-status');
const page=new URL(location.href);page.search='';page.hash='';page.pathname=page.pathname.replace(/\/$/,'')+'/';
const apiRoot=new URL('../',page);
const specUrl=new URL('openapi.json',apiRoot).href;
const collectionUrl=new URL('postman.json',apiRoot).href;
document.getElementById('access-mode').value=DEFAULT_MODE;
async function accessHeaders(request){
  const mode=document.getElementById('access-mode').value;
  if(mode==='basic')return {Authorization:'Basic '+btoa(unescape(encodeURIComponent(document.getElementById('username').value+':'+document.getElementById('password').value)))};
  if(mode==='bearer'){const token=document.getElementById('token').value;return token?{Authorization:'Bearer '+token}:{};}
  if(mode==='hmac')return minaSign(request,document.getElementById('password').value,document.getElementById('username').value||'default',ALGORITHM);
  return {};
}
async function loadDocs(event){
  if(event)event.preventDefault();status.textContent='Loading API documentation…';
  try{
    const headers=await accessHeaders({method:'GET',url:specUrl,body:''});
    const response=await fetch(specUrl,{headers,credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error(response.status===401?'Enter API credentials above and select Load API docs.':'Documentation request failed: HTTP '+response.status);
    const spec=await response.json();
    ui=SwaggerUIBundle({spec,dom_id:'#swagger-ui',deepLinking:true,displayRequestDuration:true,validatorUrl:null,persistAuthorization:false,queryConfigEnabled:false,useUnsafeMarkdown:false,
      requestInterceptor:async request=>{
        const url=new URL(request.url,location.href);request.url=url.href;
        if(url.origin===location.origin){
          const hasAuthorization=Object.keys(request.headers||{}).some(key=>key.toLowerCase()==='authorization');
          if(!hasAuthorization||document.getElementById('access-mode').value==='hmac')request.headers={...(request.headers||{}),...await accessHeaders(request)};
        }
        return request;
      }});
    status.textContent='Ready. Expand an operation and select Try it out. Debug requests wait while paused at a breakpoint.';
  }catch(error){status.textContent=error.message;}
}
document.getElementById('api-access').addEventListener('submit',loadDocs);
document.getElementById('download-postman').addEventListener('click',async()=>{
  try{
    const headers=await accessHeaders({method:'GET',url:collectionUrl,body:''});const response=await fetch(collectionUrl,{headers,credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error('Collection download failed: HTTP '+response.status);
    const url=URL.createObjectURL(await response.blob());const anchor=document.createElement('a');anchor.href=url;anchor.download='MINA-API.postman_collection.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){status.textContent=error.message;}
});
void loadDocs();
'''.replace('DEFAULT_MODE',json.dumps(mode)).replace('ALGORITHM',json.dumps(algorithm))
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MINA API Explorer · Swagger UI</title>
<link rel="stylesheet" href="ASSETS/swagger-ui.css?v=VERSION"><style>body{margin:0;background:#fafafa;font:14px system-ui}header{padding:18px;background:#10283b;color:#f1f8ff}h1{margin:0 0 12px;font-size:22px}form{display:flex;flex-wrap:wrap;gap:8px;align-items:end}label{display:flex;flex-direction:column;gap:4px}input,select,button{padding:8px;font:inherit;border:1px solid #789;border-radius:4px}button{cursor:pointer}#access-status{margin:12px 0 0;overflow-wrap:anywhere}#swagger-ui{max-width:1500px;margin:auto}.notes{font-size:12px;line-height:1.5}.swagger-ui .topbar{display:none}</style></head><body>
<header><h1>MINA API Explorer · Swagger UI</h1><form id="api-access">
<label>Documentation access<select id="access-mode"><option value="none">No credentials</option><option value="basic">Basic / LDAP</option><option value="bearer">Bearer / JWT / OAuth2 token</option><option value="hmac">MINA HMAC</option></select></label>
<label>Username / HMAC key ID<input id="username" autocomplete="off"></label><label>Password / HMAC secret<input id="password" type="password" autocomplete="off"></label><label>Access token<input id="token" type="password" autocomplete="off"></label>
<button type="submit">Load API docs</button><button type="button" id="download-postman">Download Postman collection</button></form><p id="access-status" role="status"></p><p class="notes">Credentials stay in this tab and are never included in the downloaded collection. Configure browser client certificates separately for mutual TLS. <a href="ASSETS/LICENSE" style="color:inherit">Swagger UI license</a> · <a href="ASSETS/NOTICE" style="color:inherit">Notices</a></p></header><main id="swagger-ui"></main>
<script src="ASSETS/swagger-ui-bundle.js?v=VERSION"></script><script nonce="NONCE">SCRIPT</script></body></html>'''
    # Relative paths work with a gateway prefix as well as a direct listener URL.
    import html as escape_html
    html=html.replace('ASSETS',escape_html.escape(asset_base,quote=True)).replace('VERSION',VERSION).replace('NONCE',nonce).replace('SCRIPT',script)
    return html.encode(),nonce
