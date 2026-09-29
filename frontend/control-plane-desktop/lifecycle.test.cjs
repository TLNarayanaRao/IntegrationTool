const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
test('connection lifecycle isolates remote content and closes hidden launcher',async()=>{
  const windows=[],handlers={},sessions=[],writes=[];
  class Window extends EventEmitter {
    constructor(options){super();this.options=options;this.visible=options.show!==false;this.webContents=new EventEmitter();this.webContents.mainFrame={url:''};this.webContents.setWindowOpenHandler=handler=>{this.popup=handler;};this.webContents.loadURL=async url=>{this.webContents.mainFrame.url=url;this.webContents.emit('did-finish-load');};windows.push(this);}
    removeMenu(){} setMenu(menu){this.menu=menu;} show(){this.visible=true;} hide(){this.visible=false;} focus(){} isVisible(){return this.visible;} isDestroyed(){return !!this.destroyed;}
    loadFile(file){this.webContents.mainFrame.url=pathToFileURL(file).href;return Promise.resolve();}
    destroy(){this.destroyed=true;this.emit('closed');} close(){this.destroy();}
  }
  const app=new EventEmitter();Object.assign(app,{setName(){},setPath(){},getPath:()=>'/profile',requestSingleInstanceLock:()=>true,whenReady:()=>Promise.resolve(),quit(){}});
  const electron={app,BrowserWindow:Window,Menu:{buildFromTemplate:x=>x},ipcMain:{handle:(name,fn)=>{handlers[name]=fn;}},dialog:{showErrorBox(){}},session:{fromPartition:(name)=>{
    const s=new EventEmitter();Object.assign(s,{name,webRequest:{onBeforeRequest(fn){s.network=fn;}},setPermissionRequestHandler(fn){s.permission=fn;},setPermissionCheckHandler(){},clearStorageData(){s.cleared=true;return Promise.resolve();},closeAllConnections(){}});sessions.push(s);return s;
  }}};
  const source=fs.readFileSync(path.join(__dirname,'main.cjs'),'utf8');
  vm.runInNewContext(source,{__dirname,URL,console,setTimeout,clearTimeout,require:name=>name==='electron'?electron:name==='node:fs'?{mkdirSync(){},readFileSync(){throw Error('missing');},writeFileSync:(file,data)=>writes.push({file,data})}:name==='./policy.cjs'?require('./policy.cjs'):require(name)});
  await new Promise(resolve=>setImmediate(resolve));
  const launcher=windows[0],event={sender:launcher.webContents,senderFrame:launcher.webContents.mainFrame};
  assert.equal(handlers['mina-cp:settings'](event),'');
  const result=await handlers['mina-cp:connect'](event,'https://mina.example');assert.equal(result.error,undefined);
  const remote=windows[1];assert.equal(remote.options.webPreferences.preload,undefined);assert.equal(remote.visible,true);assert.equal(launcher.visible,false);
  assert.ok(!sessions[0].name.startsWith('persist:'));assert.equal(remote.popup().action,'deny');
  assert.throws(()=>handlers['mina-cp:settings']({sender:remote.webContents,senderFrame:remote.webContents.mainFrame}),/Untrusted/);
  let denied; sessions[0].network({url:'https://attacker.example'},r=>{denied=r.cancel;});assert.equal(denied,true);
  assert.deepEqual(JSON.parse(writes[0].data),{server:'https://mina.example'});
  remote.destroy();assert.equal(launcher.destroyed,true);assert.equal(sessions[0].cleared,true);
});

test('HTML input dialogs support submit and cancel without native prompt',async()=>{
  class Element extends EventEmitter {
    constructor(tag){super();this.tag=tag;this.children=[];this.value='';}
    append(...children){this.children.push(...children);} addEventListener(name,fn){this.on(name,fn);} showModal(){} focus(){} close(){this.emit('close');} remove(){this.removed=true;}
  }
  const body=new Element('body'),document={body,createElement:tag=>new Element(tag)};
  const source=fs.readFileSync(path.resolve(__dirname,'../../administrator/web/admin.js'),'utf8');
  const helper=source.slice(source.indexOf('function askControlPlaneValue('),source.indexOf('async function api('));
  const context=vm.createContext({document});vm.runInContext(helper,context);
  const pending=vm.runInContext("askControlPlaneValue('Credential','',true)",context);
  const modal=body.children[0],form=modal.children[0],input=form.children[0].children[0];assert.equal(input.type,'password');
  input.value='test-value';form.emit('submit',{preventDefault(){}});assert.equal(await pending,'test-value');assert.equal(input.value,'');assert.equal(modal.removed,true);
  const cancel=vm.runInContext("askControlPlaneValue('Name','original')",context);body.children[1].close();assert.equal(await cancel,null);
});
