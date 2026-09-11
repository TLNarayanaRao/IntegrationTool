const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const crypto = require('node:crypto');

let mainWindow;
let runtimeProcess;
let runtimeStartupError;
let runtimeLogPath;
const utilityFiles = new Map();

const availablePort = () => new Promise((resolve, reject) => {
  const server = net.createServer();
  server.unref();
  server.on('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const address = server.address();
    server.close(() => resolve(address.port));
  });
});

const logTail = (filePath, maximum = 12000) => {
  try {
    const value = fs.readFileSync(filePath, 'utf8');
    return value.slice(Math.max(0, value.length - maximum)).trim();
  } catch {
    return '';
  }
};

const healthReady = (port, executable, timeoutMs = 60000) => new Promise((resolve, reject) => {
  const deadline = Date.now() + timeoutMs;
  let complete = false;
  const finish = (error) => {
    if (complete) return;
    complete = true;
    if (!error) return resolve();
    const details = logTail(runtimeLogPath);
    const message = [
      error,
      `Runtime executable: ${executable}`,
      `Startup log: ${runtimeLogPath}`,
      details ? `\nLast runtime output:\n${details}` : '\nThe runtime produced no output. Check antivirus quarantine and Windows Event Viewer.',
    ].join('\n');
    reject(new Error(message));
  };
  const retry = () => {
    if (complete) return;
    if (runtimeStartupError) return finish(`The Integration Fabric runtime could not start: ${runtimeStartupError.message}`);
    if (runtimeProcess && runtimeProcess.exitCode !== null) return finish(`The Integration Fabric runtime exited during startup with code ${runtimeProcess.exitCode}.`);
    if (Date.now() >= deadline) return finish(`The Integration Fabric runtime did not become ready on 127.0.0.1:${port} within ${Math.round(timeoutMs / 1000)} seconds.`);
    setTimeout(probe, 250);
  };
  const probe = () => {
    if (complete) return;
    let retried = false;
    const retryOnce = () => {
      if (retried) return;
      retried = true;
      retry();
    };
    const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
      response.resume();
      if (response.statusCode === 200) finish();
      else retryOnce();
    });
    request.on('error', retryOnce);
    request.setTimeout(1000, () => request.destroy(new Error('Runtime health probe timed out')));
  };
  probe();
});

function startRuntime(port) {
  runtimeStartupError = undefined;
  const logDirectory = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(logDirectory, { recursive: true });
  runtimeLogPath = path.join(logDirectory, 'runtime-startup.log');
  const environment = {
    ...process.env,
    FABRIC_PORT: String(port),
    FABRIC_DATA_DIR: path.join(app.getPath('userData'), 'workspace-data'),
    FABRIC_LOG_LEVEL: process.env.FABRIC_LOG_LEVEL || 'info',
    FABRIC_BUILD_VERSION: app.getVersion(),
    PYTHONUTF8: '1',
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
  if (!fs.existsSync(executable)) throw new Error(`The packaged runtime executable is missing: ${executable}`);
  fs.writeFileSync(runtimeLogPath, `[${new Date().toISOString()}] Starting ${executable}\nWorking directory: ${cwd}\nPort: ${port}\n`, 'utf8');
  runtimeProcess = spawn(executable, args, { cwd, env: environment, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const record = (stream, value) => {
    const line = `[${new Date().toISOString()}] [${stream}] ${value}`;
    fs.appendFileSync(runtimeLogPath, line);
    if (stream === 'stdout') process.stdout.write(`[runtime] ${value}`);
    else process.stderr.write(`[runtime] ${value}`);
  };
  runtimeProcess.stdout?.on('data', (value) => record('stdout', value));
  runtimeProcess.stderr?.on('data', (value) => record('stderr', value));
  runtimeProcess.on('error', (error) => {
    runtimeStartupError = error;
    fs.appendFileSync(runtimeLogPath, `[${new Date().toISOString()}] [spawn-error] ${error.stack || error}\n`);
  });
  runtimeProcess.on('exit', (code) => {
    fs.appendFileSync(runtimeLogPath, `[${new Date().toISOString()}] [exit] Runtime exited with code ${code}\n`);
    if (!app.isQuitting && mainWindow) dialog.showErrorBox('Integration Fabric Runtime', `The local runtime stopped unexpectedly (exit code ${code}).`);
  });
  return executable;
}

async function createWindow() {
  const port = await availablePort();
  const runtimePort = app.isPackaged ? port : 8787;
  const executable = startRuntime(runtimePort);
  await healthReady(runtimePort, executable);
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: '#071522',
    title: 'Integration Fabric Studio',
    icon: path.join(__dirname, 'integration-fabric-icon.svg'),
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

const readProjectFolder = (folderPath) => {
  const descriptorPath = path.join(folderPath, 'project.json');
  if (!fs.existsSync(descriptorPath)) throw new Error('The selected folder does not contain project.json.');
  const metadata = JSON.parse(fs.readFileSync(descriptorPath, 'utf8'));
  const layout = metadata.layout && typeof metadata.layout === 'object' ? metadata.layout : {};
  // Accept folders produced by older Studio builds, which kept the complete
  // project directly in project.json instead of using a layout manifest.
  if (!metadata.layout && Array.isArray(metadata.tasks)) {
    return { path: folderPath, name: path.basename(folderPath), project: metadata, kind: 'folder' };
  }
  const relativePath = (value, label) => {
    if (typeof value !== 'string' || !value.trim() || path.isAbsolute(value) || value.includes('..')) throw new Error(`Invalid ${label} path in project.json.`);
    return value.replaceAll('/', path.sep);
  };
  const readJson = (relative, label) => {
    const target = path.join(folderPath, relativePath(relative, label));
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) throw new Error(`Missing ${label}: ${relative}`);
    return JSON.parse(fs.readFileSync(target, 'utf8'));
  };
  const taskFiles = Array.isArray(layout.tasks) ? layout.tasks : [];
  const resourceFiles = Array.isArray(layout.resources) ? layout.resources : [];
  const schemaFiles = Array.isArray(layout.schemas) ? layout.schemas : [];
  const propertyFiles = Array.isArray(layout.properties) ? layout.properties : [];
  const properties = Object.fromEntries(propertyFiles.map((relative) => {
    const value = readJson(relative, 'environment properties');
    if (!value.environment) throw new Error(`Environment properties file ${relative} has no environment name.`);
    return [value.environment, value.values && typeof value.values === 'object' ? value.values : {}];
  }));
  const schemas = schemaFiles.map((relative) => {
    const normalized = relativePath(relative, 'schema');
    const target = path.join(folderPath, normalized);
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) throw new Error(`Missing schema: ${relative}`);
    const metaPath = `${target}.meta.json`;
    const meta = fs.existsSync(metaPath) ? JSON.parse(fs.readFileSync(metaPath, 'utf8')) : {};
    return { id: meta.id || safeProjectPart(path.basename(normalized, path.extname(normalized))), name: meta.name || path.basename(normalized), content: fs.readFileSync(target, 'utf8') };
  });
  const packaging = layout.packaging ? readJson(layout.packaging, 'packaging') : {};
  const tasks = taskFiles.map((item) => readJson(item, 'task'));
  tasks.forEach((task) => (task.activities || []).forEach((activity) => {
    const artifact = activity.config && activity.config.projectArtifact;
    if (artifact) activity.config.artifactPath = path.join(folderPath, relativePath(artifact, 'project artifact'));
  }));
  const project = { ...metadata, layout: undefined, tasks, resources: resourceFiles.map((item) => readJson(item, 'resource')), schemas, properties, packaging };
  delete project.layout;
  return { path: folderPath, name: path.basename(folderPath), project, kind: 'folder' };
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

ipcMain.handle('fabric:open-file', async (_event, fileType) => {
  const extensions = fileType === 'ifproject' ? ['ifproject'] : fileType === 'ifpkg' ? ['ifpkg'] : fileType === 'zip' ? ['zip'] : fileType === 'json' ? ['json'] : ['ifproject', 'ifpkg', 'zip', 'json'];
  const result = await dialog.showOpenDialog(mainWindow, {
    // Import must be a file picker. Combining openFile and openDirectory on
    // Windows causes Electron to show a folder-only dialog and prevents the
    // .ifproject filter from being selected.
    properties: ['openFile'],
    filters: [{ name: 'Integration Fabric Project', extensions }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0];
  return { path: filePath, name: path.basename(filePath), bytes: [...fs.readFileSync(filePath)], kind: 'file' };
});

ipcMain.handle('fabric:open-utility-file', async (_event, options = {}) => {
  const extensions = Array.isArray(options.extensions) ? options.extensions.map((value) => String(value).replace(/^\./, '')).filter((value) => /^[A-Za-z0-9]+$/.test(value)).slice(0, 20) : [];
  const result = await dialog.showOpenDialog(mainWindow, {
    title: String(options.title || 'Open file').slice(0, 120),
    properties: ['openFile'],
    filters: extensions.length ? [{ name: String(options.filterName || 'Supported files').slice(0, 80), extensions }, { name: 'All files', extensions: ['*'] }] : [{ name: 'All files', extensions: ['*'] }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0], stats = fs.statSync(filePath), id = crypto.randomUUID();
  utilityFiles.set(id, filePath);
  return { id, name: path.basename(filePath), size: stats.size, modified: stats.mtimeMs };
});

ipcMain.handle('fabric:read-utility-file-chunk', async (_event, options = {}) => {
  const filePath = utilityFiles.get(String(options.id || ''));
  if (!filePath) throw new Error('The file handle is closed or was not selected by this Studio session.');
  const stats = await fs.promises.stat(filePath), offset = Math.floor(Math.max(0, Math.min(Number(options.offset) || 0, stats.size)));
  const length = Math.floor(Math.max(1, Math.min(Number(options.length) || 1048576, 4 * 1024 * 1024, stats.size - offset)));
  if (!length) return { offset, length: 0, size: stats.size, base64: '', eof: true };
  const handle = await fs.promises.open(filePath, 'r');
  try {
    const buffer = Buffer.allocUnsafe(length), result = await handle.read(buffer, 0, length, offset), bytes = buffer.subarray(0, result.bytesRead);
    return { offset, length: result.bytesRead, size: stats.size, base64: bytes.toString('base64'), eof: offset + result.bytesRead >= stats.size };
  } finally { await handle.close(); }
});

ipcMain.handle('fabric:save-utility-file-window', async (_event, options = {}) => {
  const filePath = utilityFiles.get(String(options.id || ''));
  if (!filePath) throw new Error('The file handle is closed or was not selected by this Studio session.');
  const stats = await fs.promises.stat(filePath), expectedModified = Number(options.expectedModified);
  if (Number.isFinite(expectedModified) && Math.abs(stats.mtimeMs - expectedModified) > 1) throw new Error('The file changed outside Studio. Reopen it before saving to avoid overwriting newer content.');
  const offset = Math.floor(Math.max(0, Math.min(Number(options.offset) || 0, stats.size)));
  const originalLength = Math.floor(Math.max(0, Math.min(Number(options.originalLength) || 0, stats.size - offset)));
  const replacement = Buffer.from(String(options.base64 || ''), 'base64');
  if (replacement.length > 64 * 1024 * 1024) throw new Error('The edited window exceeds the 64 MB safe-save limit. Save smaller windows instead.');
  const temporaryPath = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${crypto.randomUUID()}.fabric-tmp`);
  let source, target;
  try {
    source = await fs.promises.open(filePath, 'r');
    target = await fs.promises.open(temporaryPath, 'wx', stats.mode);
    const copyRange = async (start, end) => {
      const buffer = Buffer.allocUnsafe(1024 * 1024);
      let position = start;
      while (position < end) {
        const requested = Math.min(buffer.length, end - position), result = await source.read(buffer, 0, requested, position);
        if (!result.bytesRead) break;
        await target.write(buffer, 0, result.bytesRead, null);
        position += result.bytesRead;
      }
    };
    await copyRange(0, offset);
    if (replacement.length) await target.write(replacement, 0, replacement.length, null);
    await copyRange(offset + originalLength, stats.size);
    await target.sync();
    await source.close(); source = null;
    await target.close(); target = null;
    await fs.promises.rename(temporaryPath, filePath);
    const updated = await fs.promises.stat(filePath);
    return { name: path.basename(filePath), size: updated.size, modified: updated.mtimeMs };
  } catch (error) {
    if (source) await source.close().catch(() => undefined);
    if (target) await target.close().catch(() => undefined);
    await fs.promises.unlink(temporaryPath).catch(() => undefined);
    throw error;
  }
});

ipcMain.handle('fabric:close-utility-file', (_event, id) => utilityFiles.delete(String(id || '')));

ipcMain.handle('fabric:open-project-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { title: 'Open Integration Fabric project folder', buttonLabel: 'Open folder', properties: ['openDirectory'] });
  if (result.canceled || !result.filePaths[0]) return null;
  return readProjectFolder(result.filePaths[0]);
});

ipcMain.handle('fabric:open-project-source', async () => {
  const choice = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: 'Open Integration Fabric project',
    message: 'Choose the project source to open',
    buttons: ['Project file', 'Project folder', 'Cancel'],
    defaultId: 0,
    cancelId: 2,
  });
  if (choice.response === 2) return null;
  if (choice.response === 1) {
    const result = await dialog.showOpenDialog(mainWindow, { title: 'Open Integration Fabric project folder', buttonLabel: 'Open folder', properties: ['openDirectory'] });
    if (result.canceled || !result.filePaths[0]) return null;
    return readProjectFolder(result.filePaths[0]);
  }
  const result = await dialog.showOpenDialog(mainWindow, { title: 'Open Integration Fabric project file', properties: ['openFile'], filters: [{ name: 'Integration Fabric Project', extensions: ['ifproject', 'ifpkg', 'zip', 'json'] }] });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0];
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
