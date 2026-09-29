const {contextBridge, ipcRenderer} = require('electron');
// Loaded ONLY in the bundled connection screen, never in remote content.
contextBridge.exposeInMainWorld('minaConnection', {
  settings: () => ipcRenderer.invoke('mina-cp:settings'),
  connect: address => ipcRenderer.invoke('mina-cp:connect', address)
});
