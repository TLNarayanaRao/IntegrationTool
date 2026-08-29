const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('fabricDesktop', {
  isDesktop: true,
  saveFile: (options) => ipcRenderer.invoke('fabric:save-file', options),
  openProject: () => ipcRenderer.invoke('fabric:open-file'),
  platform: process.platform,
});
