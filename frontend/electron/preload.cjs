const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('fabricDesktop', {
  isDesktop: true,
  saveFile: (options) => ipcRenderer.invoke('fabric:save-file', options),
  saveProjectFolder: (options) => ipcRenderer.invoke('fabric:save-project-folder', options),
  openProject: (fileType) => ipcRenderer.invoke('fabric:open-file', fileType),
  openProjectFolder: () => ipcRenderer.invoke('fabric:open-project-folder'),
  openProjectSource: () => ipcRenderer.invoke('fabric:open-project-source'),
  selectCodeArtifact: (kind) => ipcRenderer.invoke('fabric:select-code-artifact', kind),
  openUtilityFile: (options) => ipcRenderer.invoke('fabric:open-utility-file', options),
  readUtilityFileChunk: (options) => ipcRenderer.invoke('fabric:read-utility-file-chunk', options),
  saveUtilityFileWindow: (options) => ipcRenderer.invoke('fabric:save-utility-file-window', options),
  saveUtilityFileAs: (options) => ipcRenderer.invoke('fabric:save-utility-file-as', options),
  closeUtilityFile: (id) => ipcRenderer.invoke('fabric:close-utility-file', id),
  platform: process.platform,
});
