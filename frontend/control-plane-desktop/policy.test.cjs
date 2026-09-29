const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {preferences,serverURL,sameOrigin}=require('./policy.cjs');
test('canonical HTTPS server and explicit port',()=>{
  assert.equal(serverURL(' https://MINA.example:8443/ '),'https://mina.example:8443');
});
test('reject insecure servers, credentials, paths and executable schemes',()=>{
  for(const value of ['http://mina.example','http://127.0.0.1:8080','file:///etc/passwd','javascript:alert(1)','https://a:b@mina.example','https://mina.example/api','https://mina.example/?token=secret','https://mina.example/#x',null,{},'garbage']) assert.throws(()=>serverURL(value));
});
test('navigation cannot escape the selected origin',()=>{
  const origin='https://mina.example';
  assert.equal(sameOrigin(origin+'/api/packages',origin),true);
  for(const url of ['https://mina.example.evil.org','https://evil.org','http://mina.example','https://mina.example:8443','file:///tmp/a','javascript:alert(1)'])assert.equal(sameOrigin(url,origin),false);
});
test('sandboxed renderer defaults',()=>{
  assert.equal(preferences.nodeIntegration,false);assert.equal(preferences.sandbox,true);assert.equal(preferences.contextIsolation,true);assert.equal(preferences.webSecurity,true);assert.equal(preferences.allowRunningInsecureContent,false);
});
test('desktop packaging is independent of Studio and backend',()=>{
  const config=require('./builder.cjs');
  assert.equal(config.appId,'io.mina.controlplane.desktop');assert.deepEqual(config.extraResources,[]);
  assert.ok(!config.files.some(f=>/backend|dist|runtime|\.test\./.test(f)));
  for(const file of config.files.filter(f=>!f.startsWith('!')))assert.ok(fs.existsSync(path.join(__dirname,file)),file);
});
test('Control Plane retains web UI and no unsupported synchronous prompts',()=>{
  const root=path.resolve(__dirname,'../../administrator/web');
  const script=fs.readFileSync(path.join(root,'admin.js'),'utf8');
  assert.doesNotMatch(script,/(?<![\w])(?:window\.)?prompt\(/);
  assert.match(script,/input.type=secret\?'password'/);
  assert.ok(fs.existsSync(path.join(root,'index.html')));
});
