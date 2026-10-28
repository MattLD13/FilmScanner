'use strict';
// Pure helpers for the desktop shell: finding, starting and trusting the local FRAME service.
// No Electron imports here, so `node --test` can exercise them without a GUI.
const net = require('node:net');
const path = require('node:path');

const LOOPBACK = '127.0.0.1';
const DEFAULT_PORT = 8765;

function serviceOrigin(port) {
  return `http://${LOOPBACK}:${port}`;
}

// Only the FRAME service's own origin may be shown in the window.
function isAllowedUrl(target, origin) {
  try {
    return new URL(target).origin === origin;
  } catch {
    return false;
  }
}

// Every request the window makes must stay on the loopback service (HTTP or its event WebSocket),
// or be an in-page data/blob URL. The shell therefore never opens a TLS connection itself.
function isServiceRequest(target, origin) {
  let url;
  try {
    url = new URL(target);
  } catch {
    return false;
  }
  if (url.protocol === 'data:' || url.protocol === 'blob:') return true;
  const service = new URL(origin);
  return (url.protocol === 'http:' || url.protocol === 'ws:') && url.host === service.host;
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, LOOPBACK, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

// A FRAME service answers /api/health with {status: 'ok', mode, version}; anything else is not ours.
async function probeFrame(origin, timeoutMs = 1500) {
  try {
    const response = await fetch(`${origin}/api/health`, { signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) return null;
    const body = await response.json();
    return body && body.status === 'ok' && typeof body.mode === 'string' ? body : null;
  } catch {
    return null;
  }
}

async function waitForHealth(origin, { timeoutMs = 30000, intervalMs = 250, isAlive = () => true } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isAlive()) throw new Error('FRAME service exited before it became healthy');
    const health = await probeFrame(origin, Math.min(1500, intervalMs * 4));
    if (health) return health;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`FRAME service did not become healthy at ${origin} within ${timeoutMs} ms`);
}

// Command for an owned service; bound to loopback only, never --reload, so killing the pid ends it.
function serviceCommand({ root, port, env = process.env, dataDir }) {
  const childEnv = { ...env, PYTHONUNBUFFERED: '1' };
  if (dataDir) childEnv.FRAME_DATA_DIR = dataDir;
  return {
    command: env.FRAME_PYTHON || 'python',
    args: ['-m', 'uvicorn', 'services.api.main:app', '--host', LOOPBACK, '--port', String(port)],
    options: { cwd: root, env: childEnv, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] },
  };
}

function workspaceRoot(dirname = __dirname) {
  return path.resolve(dirname, '..', '..', '..');
}

module.exports = {
  DEFAULT_PORT, LOOPBACK, findFreePort, isAllowedUrl, isServiceRequest, probeFrame, serviceCommand,
  serviceOrigin, waitForHealth, workspaceRoot,
};
