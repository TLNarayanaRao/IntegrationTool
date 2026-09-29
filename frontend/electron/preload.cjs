const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('minaDesktop', {
  isDesktop: true,
  getAppInfo: () => ipcRenderer.invoke('mina:app-info'),
  saveFile: (options) => ipcRenderer.invoke('mina:save-file', options),
  selectArchiveOutput: (options) => ipcRenderer.invoke('mina:select-archive-output', options),
  saveProjectFolder: (options) => ipcRenderer.invoke('mina:save-project-folder', options),
  openProject: (fileType) => ipcRenderer.invoke('mina:open-file', fileType),
  openProjectFolder: () => ipcRenderer.invoke('mina:open-project-folder'),
  openProjectSource: () => ipcRenderer.invoke('mina:open-project-source'),
  selectCodeArtifact: (kind) => ipcRenderer.invoke('mina:select-code-artifact', kind),
  openUtilityFile: (options) => ipcRenderer.invoke('mina:open-utility-file', options),
  readUtilityFileChunk: (options) => ipcRenderer.invoke('mina:read-utility-file-chunk', options),
  saveUtilityFileWindow: (options) => ipcRenderer.invoke('mina:save-utility-file-window', options),
  saveUtilityFileAs: (options) => ipcRenderer.invoke('mina:save-utility-file-as', options),
  closeUtilityFile: (id) => ipcRenderer.invoke('mina:close-utility-file', id),
  platform: process.platform,
  exit: () => ipcRenderer.invoke('mina:exit'),
  completeWindowClose: () => ipcRenderer.invoke('mina:complete-window-close'),
  onWindowCloseRequested: (listener) => {
    const callback = () => listener();
    ipcRenderer.on('mina:request-window-close', callback);
    return () => ipcRenderer.removeListener('mina:request-window-close', callback);
  },
});
