const readline = require('node:readline');

const header = 'X-MINA-Desktop-Token';

function waitForPort(child, signal, timeoutMs) {
  return new Promise((resolve, reject) => {
    const output = readline.createInterface({ input: child.stdout });
    const timer = setTimeout(() => finish(new Error('The local runtime did not announce its port.')), timeoutMs);
    const abort = () => finish(signal.reason);
    const error = (reason) => finish(reason);
    const ended = (code) => finish(new Error(`The local runtime exited before announcing its port (code ${code}).`));
    function finish(reason, port) {
      clearTimeout(timer);
      output.removeAllListeners('line');
      output.close();
      signal.removeEventListener('abort', abort);
      child.removeListener('error', error);
      child.removeListener('exit', ended);
      if (reason) reject(reason);
      else resolve(port);
    }
    output.on('line', (line) => {
      const match = /^MINA_DESKTOP_PORT=(\d{1,5})$/.exec(line);
      if (match && Number(match[1]) > 0 && Number(match[1]) <= 65535) finish(null, Number(match[1]));
    });
    child.once('exit', ended);
    child.once('error', error);
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
  });
}

function protectStudioRequests(contents, origin, token) {
  const controller = contents.session.webRequest;
  controller.onBeforeSendHeaders({ urls: ['<all_urls>'] }, (details, callback) => {
    const url = new URL(details.url);
    // Chromium can retain custom headers on redirects. Strip the credential
    // before deciding whether this particular hop is still authorized.
    for (const name of Object.keys(details.requestHeaders)) {
      if (name.toLowerCase() === header.toLowerCase()) delete details.requestHeaders[name];
    }
    if (details.webContentsId === contents.id && url.origin === origin &&
        (!details.initiatorOrigin || details.initiatorOrigin === origin) &&
        (url.pathname === '/api' || url.pathname.startsWith('/api/'))) {
      details.requestHeaders[header] = token;
    }
    callback({ requestHeaders: details.requestHeaders });
  });
  contents.on('will-navigate', (event, url) => {
    if (new URL(event.url || url).origin !== origin) event.preventDefault();
  });
}

module.exports = { header, waitForPort, protectStudioRequests };
