const preferences = Object.freeze({nodeIntegration:false, contextIsolation:true, sandbox:true, webSecurity:true, allowRunningInsecureContent:false});
function serverURL(value) {
  if (typeof value !== 'string' || value.length > 2048) throw Error('Enter a Control Plane HTTPS address.');
  let u; try { u = new URL(value.trim()); } catch { throw Error('Enter a valid URL, including https://.'); }
  if (u.protocol !== 'https:') throw Error('HTTPS is required. Configure TLS on the Linux Control Plane or its reverse proxy.');
  if (u.username || u.password || u.search || u.hash || u.pathname !== '/') throw Error('Use the server origin only, such as https://mina.company.com (no credentials, path or query).');
  return u.origin;
}
function sameOrigin(value, origin) { try { return new URL(value).origin === origin; } catch { return false; } }
module.exports = {preferences, serverURL, sameOrigin};
