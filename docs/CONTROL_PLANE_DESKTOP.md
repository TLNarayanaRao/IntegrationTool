# MINA Control Plane — optional Windows client

The Linux Control Plane remains the server. The existing browser UI remains
available at the same HTTPS address. This client adds a Windows application;
it does not install Python, start a local Control Plane or change server permissions.

## Build on Windows

From `frontend`, run `npm ci` if dependencies are not installed, then:

```powershell
npm run control-plane:installer
# Or an unpacked build:
npm run control-plane:unpacked
# Override the version without editing application code:
powershell -File ../scripts/build-control-plane-desktop.ps1 -Version 1.2.0
```

Installer: `frontend/release-control-plane/MINAControlPlane-<version>-Setup.exe`.
Unpacked executable: `frontend/release-control-plane/win-unpacked/MINA Control Plane.exe`.
These are separate from the Studio installer and Administrator server archive.
Release signing requires your organization's Windows code-signing configuration;
unsigned development installers may trigger Windows SmartScreen warnings.

## Connect

1. Update the Linux server's `administrator/web/admin.js` from this version (or
   redeploy the updated Control Plane). Sign-in and rename dialogs now support
   both browsers and Electron. Older servers using `window.prompt` are incompatible.
2. Expose the existing Control Plane through HTTPS with a certificate trusted by
   Windows. A reverse proxy can terminate TLS and forward to the existing service.
   Serve at the origin root, e.g. `https://mina.company.com`, not `/control-plane`.
   Enable authentication and preserve existing API routes, uploads and downloads.
3. Install and launch **MINA Control Plane** on Windows, enter that HTTPS address,
   then enter your existing Control Plane credential when requested.
4. Use **Connection → Reload / reconnect** after a connection failure, or
   **Sign out / change server** to end the local session. Closing the app does not
   stop remote applications or cancel operations already accepted by the server.

## Security and limitations

Only the server address is stored in `%APPDATA%/MINAControlPlaneDesktop/server.json`.
Remote browsing uses an isolated, non-persistent session. Its cookies, credentials
and local storage are not persisted across app restarts; changing server creates a
new session. Browser credential storage behavior is unchanged. Local sign-out does
not revoke a server-issued credential; revoke credentials through server administration.

Remote pages have no Node.js or desktop IPC access. Sandboxing, context isolation,
certificate validation and web security are enabled. HTTP and invalid certificates
are rejected; there is no bypass switch. Cross-origin navigation, pop-ups and device
permissions are blocked. External identity-provider redirects and cross-origin CDNs
are not supported by this initial client. Existing same-origin Control Plane
credential authentication, uploads, exports and management APIs remain available.

Network outages interrupt the desktop view, not deployed workloads. Reload when
connectivity returns. This is an online client, not an offline administration replica.

## Development and tests

`npm run control-plane:desktop` launches from source. `npm run control-plane:test`
checks URL policy, isolation settings, independent packaging and dialog compatibility.
The entry point is `frontend/control-plane-desktop/main.cjs`; the connection screen
is `connect.html`, `connect.js` and `connect.css`. Remote content has no preload.
The local screen's narrow IPC bridge is validated against its exact sender/frame.
Follow release qualification with a real HTTPS Linux server: sign-in, team isolation,
package upload/download, start/stop, network interruption, reconnect and local sign-out.
