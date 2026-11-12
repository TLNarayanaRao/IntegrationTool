// Use Chromium's real XML DOM, without adding a production DOM dependency.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs');
const [requestPath,resultPath]=process.argv.slice(2);
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 try {
  const request=JSON.parse(fs.readFileSync(requestPath,'utf8'));
  const window=new BrowserWindow({show:false,webPreferences:{nodeIntegration:false,contextIsolation:true}});
  await window.loadURL('data:text/html,<html><body></body></html>');
  const evaluated=await window.webContents.executeJavaScript(`(()=>{try{return {result:eval(${JSON.stringify(request.script)})}}catch(error){return {error:String(error.stack||error)}}})()`);
  if(evaluated.error)throw new Error(evaluated.error);
  const result=evaluated.result;
  fs.writeFileSync(resultPath,JSON.stringify({result}));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(resultPath,JSON.stringify({error:String(error.stack||error)}));app.exit(1);}
});
