const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('fabricDesktop', {
  isDesktop: true,
  saveFile: (options) => ipcRenderer.invoke('fabric:save-file', options),
  saveProjectFolder: (options) => ipcRenderer.invoke('fabric:save-project-folder', options),
  openProject: () => ipcRenderer.invoke('fabric:open-file'),
  selectCodeArtifact: (kind) => ipcRenderer.invoke('fabric:select-code-artifact', kind),
  platform: process.platform,
});
