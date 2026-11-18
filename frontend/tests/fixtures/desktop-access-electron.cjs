// Test the actual Chromium request hook with private, never-shown windows.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const http = require('node:http');
const { once } = require('node:events');
const { protectStudioRequests } = require('../../electron/desktop-access.cjs');

const profile = process.argv[2];
if (!profile) throw new Error('Provide an isolated test profile directory.');
app.setPath('userData', profile);
app.disableHardwareAcceleration();

async function listen(handler) {
  const server = http.createServer(handler);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return { server, origin: `http://127.0.0.1:${server.address().port}` };
}

app.whenReady().then(async () => {
  const observed = [];
  const peer = await listen((request, response) => {
    observed.push(request.headers['x-mina-desktop-token']);
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.end('peer');
  });
  const owned = await listen((request, response) => {
    if (!request.url.startsWith('/api/')) return response.end('<!doctype html><title>MINA fixture</title>');
    if (request.headers['x-mina-desktop-token'] !== 'synthetic-session') {
      response.statusCode = 403;
      return response.end('denied');
    }
    if (request.url === '/api/redirect') {
      response.writeHead(302, { Location: peer.origin });
    }
    response.end('authorized');
  });
  const studio = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true } });
  const another = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true } });
  try {
    protectStudioRequests(studio.webContents, owned.origin, 'synthetic-session');
    await studio.loadURL(owned.origin);
    await another.loadURL(owned.origin);
    assert.equal(await studio.webContents.executeJavaScript("fetch('/api/probe').then(r => r.status)"), 200);
    assert.equal(await another.webContents.executeJavaScript("fetch('/api/probe').then(r => r.status)"), 403);
    await studio.webContents.executeJavaScript("fetch('/api/redirect').catch(() => undefined)");
    assert.equal(observed.length, 1);
    assert.equal(observed[0], undefined);
    console.log('Electron authorized its own renderer and kept the credential off redirects and other windows.');
  } finally {
    studio.destroy();
    another.destroy();
    await Promise.all([owned.server, peer.server].map(server => {
      server.closeAllConnections();
      return new Promise(resolve => server.close(resolve));
    }));
  }
}).then(() => app.exit(0), error => {
  console.error(error);
  app.exit(1);
});
