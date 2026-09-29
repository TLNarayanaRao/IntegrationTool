const {app, BrowserWindow, Menu, ipcMain, session, dialog} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {randomUUID} = require('node:crypto');
const {preferences, serverURL, sameOrigin} = require('./policy.cjs');
app.setName('MINA Control Plane');
// Never share Studio's profile, even when running from source.
app.setPath('userData', path.join(app.getPath('appData'), 'MINAControlPlaneDesktop'));
let connection, remote, connecting=false;
const connectionURL=pathToFileURL(path.join(__dirname,'connect.html')).href;
const settingsPath=path.join(app.getPath('userData'),'server.json');
function trusted(event) {
  if (!connection || event.sender !== connection.webContents || event.senderFrame !== connection.webContents.mainFrame || event.senderFrame.url !== connectionURL) throw Error('Untrusted connection request.');
}
function showConnection() {
  if (!connection || connection.isDestroyed()) {
    connection=new BrowserWindow({width:720,height:700,minWidth:540,minHeight:640,title:'MINA Control Plane — Connect',backgroundColor:'#0a1927',webPreferences:{...preferences,preload:path.join(__dirname,'preload.cjs')}});
    connection.removeMenu();
    connection.webContents.setWindowOpenHandler(() => ({action:'deny'}));
    connection.webContents.on('will-navigate',e=>e.preventDefault());
    connection.loadFile(path.join(__dirname,'connect.html'));
    connection.on('closed',()=>{connection=null;});
  }
  connection.show(); connection.focus();
}
async function connect(origin) {
  // Non-persistent partition: credentials/cookies/localStorage stay in memory.
  const isolated=session.fromPartition(`mina-cp-${randomUUID()}`,{cache:false});
  isolated.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  isolated.setPermissionCheckHandler(()=>false);
  isolated.webRequest.onBeforeRequest((details,callback)=>{
    const allowed=sameOrigin(details.url,origin) || details.url.startsWith(`blob:${origin}/`) || details.url.startsWith('data:');
    callback({cancel:!allowed});
  });
  isolated.on('will-download',(_event,item)=>{
    item.setSaveDialogOptions({title:'Save Control Plane export'});
    item.once('done',(_event,state)=>{if(state==='interrupted')dialog.showErrorBox('Download failed','The download was interrupted. Check connectivity and retry the export.');});
  });
  const win=new BrowserWindow({width:1500,height:980,minWidth:1050,minHeight:700,show:false,title:`MINA Control Plane — ${origin}`,webPreferences:{...preferences,session:isolated}});
  remote=win;
  const wc=win.webContents;
  wc.setWindowOpenHandler(()=>({action:'deny'}));
  for(const event of ['will-navigate','will-redirect','will-frame-navigate']) wc.on(event,(e,url)=>{if(!sameOrigin(url,origin))e.preventDefault();});
  wc.on('will-attach-webview',e=>e.preventDefault());
  wc.on('page-title-updated',e=>e.preventDefault());
  win.setMenu(Menu.buildFromTemplate([{label:'Connection',submenu:[
    {label:'Reload / reconnect',accelerator:'CmdOrCtrl+R',click:()=>wc.loadURL(origin).catch(()=>dialog.showErrorBox('Connection unavailable','Check the server, network and TLS certificate, then retry from Connection → Reload.'))},
    {label:'Sign out / change server',click:()=>{showConnection();win.destroy();}},
    {type:'separator'},{role:'quit'}
  ]},{label:'Edit',submenu:[{role:'undo'},{role:'redo'},{type:'separator'},{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]},
  {label:'View',submenu:[{role:'resetZoom'},{role:'zoomIn'},{role:'zoomOut'},{role:'togglefullscreen'}]}]));
  win.on('closed',()=>{if(remote===win)remote=null;isolated.clearStorageData().catch(()=>{});isolated.closeAllConnections();if(connection && !connection.isVisible())connection.close();});
  wc.on('render-process-gone',()=>{if(!win.isDestroyed())dialog.showErrorBox('Control Plane view stopped','Use Connection → Reload / reconnect to restore the view. Server workloads are unaffected.');});
  try {
    await Promise.race([wc.loadURL(origin),new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('Connection timed out')),30000);timer.unref();wc.once('did-finish-load',()=>clearTimeout(timer));})]);
    if(win.isDestroyed())throw Error('Connection closed');
    fs.mkdirSync(path.dirname(settingsPath),{recursive:true});
    fs.writeFileSync(settingsPath,JSON.stringify({server:origin}),'utf8');
    win.show(); connection?.hide();
  } catch(error) {if(!win.isDestroyed())win.destroy();throw error;}
}
ipcMain.handle('mina-cp:settings',event=>{trusted(event);try{return serverURL(JSON.parse(fs.readFileSync(settingsPath,'utf8')).server);}catch{return '';}});
ipcMain.handle('mina-cp:connect',async(event,address)=>{
  trusted(event);if(connecting || remote)return {error:'A connection is already open.'};
  connecting=true;
  try{await connect(serverURL(address));return {};}catch(error){return {error:`Connection failed: ${error.message}. Check network access and use a trusted TLS certificate.`};}finally{connecting=false;}
});
app.on('certificate-error',(event,_wc,_url,_error,_certificate,callback)=>{event.preventDefault();callback(false);});
app.on('window-all-closed',()=>app.quit());
if(!app.requestSingleInstanceLock())app.quit();else {
  app.on('second-instance',()=>{const win=remote||connection;if(win){if(win.isMinimized())win.restore();win.show();win.focus();}});
  app.whenReady().then(showConnection);
}
