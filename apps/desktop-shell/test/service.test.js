'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const test = require('node:test');
const {
  findFreePort, isAllowedUrl, isAllowedFullscreen, isServiceRequest, probeFrame, serviceCommand, serviceOrigin, waitForHealth, workspaceRoot,
} = require('../src/service');

function serve(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => resolve({ server, origin: serviceOrigin(server.address().port) }));
  });
}

test('only the service origin is navigable', () => {
  const origin = serviceOrigin(8765);
  assert.equal(isAllowedUrl('http://127.0.0.1:8765/rolls?x=1', origin), true);
  for (const url of ['http://127.0.0.1:8766/', 'http://localhost:8765/', 'https://127.0.0.1:8765/',
    'file:///C:/Windows/', 'javascript:alert(1)', 'not a url']) {
    assert.equal(isAllowedUrl(url, origin), false, url);
  }
});

test('fullscreen is limited to FRAME main-frame user-triggered permission', () => {
  const origin = serviceOrigin(8765), page = origin + '/?workspace=frame';
  assert.equal(isAllowedFullscreen('fullscreen', page, page, origin, true), true);
  for (const permission of ['automatic-fullscreen', 'camera', 'media', 'usb', 'serial', 'unknown']) {
    assert.equal(isAllowedFullscreen(permission, page, page, origin, true), false);
  }
  for (const source of ['https://example.com', 'http://127.0.0.1:9999', 'file:///C:/', undefined]) {
    assert.equal(isAllowedFullscreen('fullscreen', source, page, origin, true), false);
    assert.equal(isAllowedFullscreen('fullscreen', page, source, origin, true), false);
  }
  assert.equal(isAllowedFullscreen('fullscreen', page, page, origin, false), false);
  assert.equal(isAllowedFullscreen('fullscreen', page, page, origin, undefined), false);
});

test('window requests stay on the loopback service and never reach TLS hosts', () => {
  const origin = serviceOrigin(8765);
  for (const url of ['http://127.0.0.1:8765/api/state', 'ws://127.0.0.1:8765/api/events',
    'data:image/png;base64,AA==', 'blob:http://127.0.0.1:8765/4b1d']) {
    assert.equal(isServiceRequest(url, origin), true, url);
  }
  for (const url of ['https://127.0.0.1:8765/', 'wss://127.0.0.1:8765/api/events', 'http://127.0.0.1:9999/',
    'https://example.com/', 'http://localhost:8765/', 'file:///C:/', 'nonsense']) {
    assert.equal(isServiceRequest(url, origin), false, url);
  }
});

test('free port is bindable on loopback', async () => {
  const port = await findFreePort();
  await new Promise((resolve, reject) => {
    const server = net.createServer().once('error', reject).listen(port, '127.0.0.1', () => server.close(resolve));
  });
});

test('owned service binds loopback without reload and isolates smoke data', () => {
  const { command, args, options } = serviceCommand({
    root: 'C:/frame', port: 50123, env: { FRAME_PYTHON: 'py.exe', PATH: 'x' }, dataDir: 'C:/tmp/lib',
  });
  assert.equal(command, 'py.exe');
  assert.deepEqual(args, ['-m', 'uvicorn', 'services.api.main:app', '--host', '127.0.0.1', '--port', '50123']);
  assert.ok(!args.includes('--reload'));
  assert.equal(options.cwd, 'C:/frame');
  assert.equal(options.env.FRAME_DATA_DIR, 'C:/tmp/lib');
  assert.equal(options.env.PATH, 'x');
  assert.equal(serviceCommand({ root: '.', port: 1, env: {} }).options.env.FRAME_DATA_DIR, undefined);
});

test('workspace root is three levels above src', () => {
  const ws = path.resolve('/ws');
  assert.equal(workspaceRoot(path.join(ws, 'apps', 'desktop-shell', 'src')), ws);
});

test('probe accepts a FRAME health answer and rejects other services', async () => {
  const frame = await serve((req, res) => res.end(JSON.stringify({ status: 'ok', mode: 'simulator', version: '0.1.0' })));
  const other = await serve((req, res) => res.end(JSON.stringify({ status: 'ok' })));
  const broken = await serve((req, res) => { res.statusCode = 500; res.end('{}'); });
  try {
    assert.equal((await probeFrame(frame.origin)).mode, 'simulator');
    assert.equal(await probeFrame(other.origin), null);
    assert.equal(await probeFrame(broken.origin), null);
    assert.equal(await probeFrame(serviceOrigin(await findFreePort())), null);
  } finally {
    for (const s of [frame, other, broken]) s.server.close();
  }
});

test('wait for health succeeds once ready, fails fast when the process died, and times out', async () => {
  let ready = false;
  const svc = await serve((req, res) => {
    if (!ready) { res.statusCode = 503; return res.end(); }
    res.end(JSON.stringify({ status: 'ok', mode: 'simulator' }));
  });
  try {
    setTimeout(() => { ready = true; }, 150);
    assert.equal((await waitForHealth(svc.origin, { timeoutMs: 3000, intervalMs: 50 })).status, 'ok');
    const dead = serviceOrigin(await findFreePort());
    await assert.rejects(waitForHealth(dead, { timeoutMs: 3000, intervalMs: 50, isAlive: () => false }), /exited/);
    await assert.rejects(waitForHealth(dead, { timeoutMs: 300, intervalMs: 50 }), /did not become healthy/);
  } finally {
    svc.server.close();
  }
});
