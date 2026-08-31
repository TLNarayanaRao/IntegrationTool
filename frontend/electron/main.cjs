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

const safeProjectPart = (value, fallback = 'item') => {
  const normalized = String(value || '').replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '');
  return normalized || fallback;
};
const writeProjectJson = (filePath, value) => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, filePath);
};

ipcMain.handle('fabric:save-project-folder', async (_event, options) => {
  let folderPath = options.path;
  if (!folderPath) {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Choose where to save the Integration Fabric project folder',
      buttonLabel: 'Select folder',
      properties: ['openDirectory', 'createDirectory'],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    const parent = result.filePaths[0];
    const folderName = safeProjectPart(options.folderName, 'IntegrationFabricProject');
    folderPath = path.basename(parent).toLowerCase() === folderName.toLowerCase() ? parent : path.join(parent, folderName);
  }
  const project = options.project || {};
  const tasks = structuredClone(Array.isArray(project.tasks) ? project.tasks : []);
  const resources = Array.isArray(project.resources) ? project.resources : [];
  const schemas = Array.isArray(project.schemas) ? project.schemas : [];
  const properties = project.properties || {};
  const taskFiles = tasks.map((item) => `tasks/${safeProjectPart(item.id)}.json`);
  const resourceFiles = resources.map((item) => `resources/connections/${safeProjectPart(item.id)}.json`);
  const schemaFiles = schemas.map((item) => `schemas/${safeProjectPart(item.name || item.id, 'schema.xsd')}`);
  const propertyFiles = Object.keys(properties).map((environment) => `properties/${safeProjectPart(environment)}.json`);
  tasks.forEach((task) => (task.activities || []).forEach((activity) => {
    const source = activity.config?.artifactPath;
    if (!source || !fs.existsSync(source) || !fs.statSync(source).isFile()) return;
    const relative = `resources/code/${safeProjectPart(path.basename(source))}`;
    const target = path.join(folderPath, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    if (path.resolve(source) !== path.resolve(target)) fs.copyFileSync(source, target);
    activity.config.artifactPath = target;
    activity.config.projectArtifact = relative.replaceAll('\\', '/');
  }));
  const metadata = { ...project, tasks: undefined, resources: undefined, schemas: undefined, properties: undefined, packaging: undefined, process: undefined,
    layout: { format: 'integration-fabric-folder-project', version: 1, tasks: taskFiles, resources: resourceFiles, schemas: schemaFiles, properties: propertyFiles, packaging: 'packaging/packaging.json' } };
  writeProjectJson(path.join(folderPath, 'project.json'), metadata);
  tasks.forEach((item, index) => writeProjectJson(path.join(folderPath, taskFiles[index]), item));
  resources.forEach((item, index) => writeProjectJson(path.join(folderPath, resourceFiles[index]), item));
  schemas.forEach((item, index) => { const target = path.join(folderPath, schemaFiles[index]); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, item.content || '', 'utf8'); writeProjectJson(`${target}.meta.json`, { id: item.id, name: item.name }); });
  Object.entries(properties).forEach(([environment, values], index) => writeProjectJson(path.join(folderPath, propertyFiles[index]), { environment, values }));
  writeProjectJson(path.join(folderPath, 'packaging', 'packaging.json'), project.packaging || {});
  return folderPath;
});

ipcMain.handle('fabric:open-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'openDirectory'],
    filters: [{ name: 'Integration Fabric Project', extensions: ['ifproject', 'zip', 'json'] }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0];
  if (fs.statSync(filePath).isDirectory()) {
    const descriptorPath = path.join(filePath, 'project.json');
    if (!fs.existsSync(descriptorPath)) throw new Error('The selected folder does not contain project.json.');
    const metadata = JSON.parse(fs.readFileSync(descriptorPath, 'utf8'));
    const layout = metadata.layout || {};
    const readJson = (relative) => JSON.parse(fs.readFileSync(path.join(filePath, relative), 'utf8'));
    const taskFiles = layout.tasks || [];
    const resourceFiles = layout.resources || [];
    const schemaFiles = layout.schemas || [];
    const propertyFiles = layout.properties || [];
    const properties = Object.fromEntries(propertyFiles.map((relative) => { const value = readJson(relative); return [value.environment, value.values]; }));
    const schemas = schemaFiles.map((relative) => { const target = path.join(filePath, relative); const meta = fs.existsSync(`${target}.meta.json`) ? JSON.parse(fs.readFileSync(`${target}.meta.json`, 'utf8')) : {}; return { id: meta.id || safeProjectPart(path.basename(relative, path.extname(relative))), name: meta.name || path.basename(relative), content: fs.readFileSync(target, 'utf8') }; });
    const project = { ...metadata, layout: undefined, tasks: taskFiles.map(readJson), resources: resourceFiles.map(readJson), schemas, properties, packaging: layout.packaging ? readJson(layout.packaging) : {} };
    return { path: filePath, name: path.basename(filePath), project, kind: 'folder' };
  }
  return { path: filePath, name: path.basename(filePath), bytes: [...fs.readFileSync(filePath)], kind: 'file' };
});

ipcMain.handle('fabric:select-code-artifact', async (_event, kind) => {
  const filters = kind === 'python'
    ? [{ name: 'Python module or package', extensions: ['py', 'zip', 'whl'] }]
    : [{ name: 'Java class or library', extensions: ['jar', 'class', 'java'] }];
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'], filters });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0];
  return { path: filePath, name: path.basename(filePath), kind };
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
