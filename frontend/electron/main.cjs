const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');

let mainWindow;
let runtimeProcess;

const availablePort = () => new Promise((resolve, reject) => {
  const server = net.createServer();
  server.unref();
  server.on('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const address = server.address();
    server.close(() => resolve(address.port));
  });
});

const healthReady = (port, attempts = 100) => new Promise((resolve, reject) => {
  const probe = () => {
    const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
      response.resume();
      if (response.statusCode === 200) resolve();
      else retry();
    });
    request.on('error', retry);
    request.setTimeout(500, () => { request.destroy(); retry(); });
  };
  const retry = () => attempts-- > 0 ? setTimeout(probe, 150) : reject(new Error('The Integration Fabric runtime did not become ready.'));
  probe();
});

function startRuntime(port) {
  const environment = {
    ...process.env,
    FABRIC_PORT: String(port),
    FABRIC_DATA_DIR: path.join(app.getPath('userData'), 'workspace-data'),
  };
  let executable;
  let args = [];
  let cwd;
  if (app.isPackaged) {
    executable = path.join(process.resourcesPath, 'runtime', 'IntegrationFabricRuntime', process.platform === 'win32' ? 'IntegrationFabricRuntime.exe' : 'IntegrationFabricRuntime');
    cwd = path.dirname(executable);
  } else {
    const root = path.resolve(__dirname, '..', '..');
    const windowsPython = path.join(root, 'backend', '.venv', 'Scripts', 'python.exe');
    const unixPython = path.join(root, 'backend', '.venv', 'bin', 'python');
    executable = process.env.FABRIC_PYTHON || (fs.existsSync(windowsPython) ? windowsPython : unixPython);
    args = ['run_sidecar.py'];
    cwd = path.join(root, 'backend');
  }
  runtimeProcess = spawn(executable, args, { cwd, env: environment, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  runtimeProcess.stdout?.on('data', (value) => process.stdout.write(`[runtime] ${value}`));
  runtimeProcess.stderr?.on('data', (value) => process.stderr.write(`[runtime] ${value}`));
  runtimeProcess.on('exit', (code) => {
    if (!app.isQuitting && mainWindow) dialog.showErrorBox('Integration Fabric Runtime', `The local runtime stopped unexpectedly (exit code ${code}).`);
  });
}

async function createWindow() {
  const port = await availablePort();
  startRuntime(app.isPackaged ? port : 8787);
  const runtimePort = app.isPackaged ? port : 8787;
  await healthReady(runtimePort);
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: '#071522',
    title: 'Integration Fabric Studio',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.removeMenu();
  await mainWindow.loadURL(process.env.FABRIC_DEV_URL || `http://127.0.0.1:${runtimePort}`);
}

ipcMain.handle('fabric:save-file', async (_event, options) => {
  let filePath = options.path;
  if (!filePath) {
    const result = await dialog.showSaveDialog(mainWindow, {
      defaultPath: options.filename,
      filters: options.filters || [{ name: 'Integration Fabric file', extensions: ['ifproject', 'ifpkg', 'zip', 'json'] }],
    });
    if (result.canceled || !result.filePath) return null;
    filePath = result.filePath;
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, Buffer.from(options.bytes));
  return filePath;
});

ipcMain.handle('fabric:open-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [{ name: 'Integration Fabric Project', extensions: ['ifproject', 'zip', 'json'] }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0];
  return { path: filePath, name: path.basename(filePath), bytes: [...fs.readFileSync(filePath)] };
});

app.whenReady().then(createWindow).catch((error) => {
  dialog.showErrorBox('Integration Fabric Studio', error.stack || String(error));
  app.quit();
});
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  app.isQuitting = true;
  if (runtimeProcess && !runtimeProcess.killed) runtimeProcess.kill();
});
