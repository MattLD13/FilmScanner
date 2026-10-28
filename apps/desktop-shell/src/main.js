'use strict';
// FRAME desktop shell: a native Windows window around the existing React client and Python service.
// The shell adds no scanner capability; the service decides which backend (simulator today) is used.
const { app, BrowserWindow, Menu, dialog, session, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  DEFAULT_PORT, findFreePort, isAllowedUrl, isServiceRequest, probeFrame, serviceCommand, serviceOrigin,
  waitForHealth, workspaceRoot,
} = require('./service');

const smoke = process.argv.includes('--smoke');
const screenshotArg = process.argv.find((arg) => arg.startsWith('--screenshot='));
const root = workspaceRoot();
let child = null;
let origin = null;
let window = null;

function logPath() {
  const dir = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, 'service.log');
}

async function startService() {
  // Attach to an already running FRAME service so two processes never share one library database.
  // Smoke runs always own a throwaway service and library.
  if (!smoke) {
    const existing = serviceOrigin(Number(process.env.FRAME_PORT) || DEFAULT_PORT);
    if (await probeFrame(existing)) return { origin: existing, owned: false };
  }
  const port = await findFreePort();
  const dataDir = smoke ? fs.mkdtempSync(path.join(os.tmpdir(), 'frame-desktop-smoke-')) : undefined;
  const { command, args, options } = serviceCommand({ root, port, dataDir });
  const log = fs.createWriteStream(logPath(), { flags: 'a' });
  log.write(`\n--- ${new Date().toISOString()} starting ${command} ${args.join(' ')}\n`);
  child = spawn(command, args, options);
  child.stdout.pipe(log);
  child.stderr.pipe(log);
  let exited = false;
  child.once('exit', (code) => {
    exited = true;
    log.write(`--- service exited with ${code}\n`);
    if (!app.isQuitting && window) {
      dialog.showErrorBox('FRAME service stopped', `The local FRAME service exited (code ${code}). See ${logPath()}.`);
      app.quit();
    }
  });
  child.once('error', (error) => log.write(`--- service failed to start: ${error.message}\n`));
  const target = serviceOrigin(port);
  await waitForHealth(target, { isAlive: () => !exited });
  return { origin: target, owned: true, dataDir };
}

function stopService() {
  // Resolves once the owned service has really exited, so its library files are released.
  const running = child;
  child = null;
  if (!running || running.exitCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, 5000);
    running.once('exit', () => { clearTimeout(timer); resolve(); });
    running.kill();
  });
}

function harden(allowedOrigin) {
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    callback({ cancel: !isServiceRequest(details.url, allowedOrigin) });
  });
  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-attach-webview', (event) => event.preventDefault());
    contents.on('will-navigate', (event, url) => {
      if (!isAllowedUrl(url, allowedOrigin)) event.preventDefault();
    });
    contents.setWindowOpenHandler(({ url }) => {
      // Ordinary web links leave FRAME and open in the user's browser; nothing opens inside the shell.
      if (/^https:\/\//.test(url)) shell.openExternal(url);
      return { action: 'deny' };
    });
  });
}

function createWindow() {
  window = new BrowserWindow({
    width: 1320, height: 880, minWidth: 380, minHeight: 600, show: false, title: 'FRAME',
    backgroundColor: '#111418', autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true, spellcheck: false },
  });
  window.once('ready-to-show', () => { if (!smoke) window.show(); });
  window.on('closed', () => { window = null; });
  return window;
}

async function runSmoke(win) {
  // Wait until the client has authenticated with the service and loaded the library state.
  const result = await win.webContents.executeJavaScript(`(async () => {
    const started = Date.now();
    while (Date.now() - started < 20000) {
      const state = await fetch('/api/state', { credentials: 'same-origin' }).then((r) => r.status).catch(() => 0);
      if (state === 200 && document.body && document.body.innerText.trim().length > 0) {
        const health = await fetch('/api/health').then((r) => r.json());
        return { ok: true, state, health, title: document.title, text: document.body.innerText.slice(0, 200) };
      }
      await new Promise((r) => setTimeout(r, 250));
    }
    return { ok: false };
  })()`);
  if (screenshotArg && result.ok) {
    win.setContentSize(1320, 880);
    await new Promise((resolve) => setTimeout(resolve, 500));
    const image = await win.webContents.capturePage();
    fs.writeFileSync(path.resolve(screenshotArg.slice('--screenshot='.length)), image.toPNG());
  }
  return { ...result, origin, sandboxed: true, electron: process.versions.electron, chrome: process.versions.chrome };
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) { if (window.isMinimized()) window.restore(); window.focus(); }
  });
  app.on('before-quit', () => { app.isQuitting = true; stopService(); });
  app.on('window-all-closed', () => app.quit());

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    if (!fs.existsSync(path.join(root, 'apps', 'web', 'dist', 'index.html'))) {
      dialog.showErrorBox('FRAME client not built', 'Run "npm run build" in the FRAME folder, then start the desktop app again.');
      app.exit(2);
      return;
    }
    try {
      const service = await startService();
      origin = service.origin;
      harden(origin);
      const win = createWindow();
      await win.loadURL(`${origin}/`);
      if (smoke) {
        const result = await runSmoke(win);
        process.stdout.write(`${JSON.stringify({ ...result, owned: service.owned })}\n`);
        app.isQuitting = true;
        await stopService();
        if (service.dataDir) fs.rmSync(service.dataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
        app.exit(result.ok ? 0 : 1);
      }
    } catch (error) {
      if (smoke) process.stdout.write(`${JSON.stringify({ ok: false, error: error.message })}\n`);
      else dialog.showErrorBox('FRAME could not start', `${error.message}\n\nService log: ${logPath()}`);
      app.isQuitting = true;
      await stopService();
      app.exit(1);
    }
  });
}
