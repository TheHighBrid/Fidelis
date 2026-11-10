#!/usr/bin/env node
/**
 * Same-host Chromium/Chrome DevTools Protocol acceptance runner for /regions.
 *
 * Drives a real browser against a local loopback Fidelis Studio server:
 * - file-input pass upload (base + texture PNGs),
 * - mouse pointer brush painting, Undo/Redo, keyboard Cmd/Ctrl+Z, Save/Reload persistence,
 * - Native 100%/200% pixel crop inspection & comparison slider,
 * - out-of-band 409 stale-revision conflict preservation,
 * - mobile 390x844 touch painting & horizontal overflow audit.
 *
 * Emits machine-readable JSON evidence plus optional PNG screenshots. This tests
 * Chromium on the current host; physical mobile touch hardware and human visual
 * signoff remain separate gates.
 */
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const opts = {
    url: null,
    chrome: process.env.CHROME_BIN || null,
    python: process.env.PYTHON_BIN || null,
    screenshotsDir: null,
    report: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--chrome') opts.chrome = argv[++i];
    else if (arg === '--python') opts.python = argv[++i];
    else if (arg === '--screenshots-dir') opts.screenshotsDir = argv[++i];
    else if (arg === '--report') opts.report = argv[++i];
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return opts;
}

function findChrome(explicitPath) {
  const candidates = [
    explicitPath,
    process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    'google-chrome',
    'chromium',
    'chromium-browser',
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate.startsWith('/')) {
      if (fs.existsSync(candidate)) return candidate;
      continue;
    }
    try {
      const resolved = execFileSync('which', [candidate], { encoding: 'utf8' }).trim();
      if (resolved) return resolved;
    } catch {
      // keep probing
    }
  }
  throw new Error('No Chrome/Chromium executable found; set CHROME_BIN or pass --chrome');
}

function resolvePython(repoRoot, explicitPython) {
  if (explicitPython) return explicitPython;
  const venvPython = path.join(repoRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  return 'python3';
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close((err) => (err ? reject(err) : resolve(port)));
    });
  });
}

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i += 1) {
    c ^= buf[i];
    for (let k = 0; k < 8; k += 1) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return (c ^ 0xffffffff) >>> 0;
}

function makeChunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const kind = Buffer.from(type, 'ascii');
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([kind, data])), 0);
  return Buffer.concat([len, kind, data, crcBuf]);
}

function encodeRgbPng(width, height, pixelFn) {
  const raw = Buffer.alloc(height * (1 + width * 3));
  for (let y = 0; y < height; y += 1) {
    const rowOff = y * (1 + width * 3);
    raw[rowOff] = 0;
    for (let x = 0; x < width; x += 1) {
      const [r, g, b] = pixelFn(x, y);
      const off = rowOff + 1 + x * 3;
      raw[off] = r;
      raw[off + 1] = g;
      raw[off + 2] = b;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // RGB
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    makeChunk('IHDR', ihdr),
    makeChunk('IDAT', zlib.deflateSync(raw)),
    makeChunk('IEND', Buffer.alloc(0)),
  ]);
}

class CdpSession {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.events = new Map();
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = (err) => reject(new Error(`CDP WebSocket error: ${err.message || err}`));
    });
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id) {
        const entry = this.pending.get(msg.id);
        if (!entry) return;
        this.pending.delete(msg.id);
        if (msg.error) entry.reject(new Error(`CDP ${entry.method}: ${msg.error.message}`));
        else entry.resolve(msg.result);
      } else if (msg.method) {
        const listeners = this.events.get(msg.method) || [];
        for (const fn of listeners) fn(msg.params);
      }
    };
  }

  on(method, fn) {
    if (!this.events.has(method)) this.events.set(method, []);
    this.events.get(method).push(fn);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, method });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (res.exceptionDetails) {
      const desc = res.exceptionDetails.exception?.description || res.exceptionDetails.text;
      throw new Error(`Page evaluation error: ${desc}`);
    }
    return res.result?.value;
  }

  close() {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.close();
  }
}

async function waitFor(fn, { timeoutMs = 10000, intervalMs = 50, label = 'condition' } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastVal = null;
  while (Date.now() < deadline) {
    lastVal = await fn();
    if (lastVal) return lastVal;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`Timed out waiting for ${label} (last value: ${JSON.stringify(lastVal)})`);
}

async function stopProcess(proc) {
  if (!proc || proc.exitCode !== null) return;
  const exited = new Promise((resolve) => proc.once('exit', resolve));
  proc.kill('SIGTERM');
  const timer = setTimeout(() => {
    if (proc.exitCode === null) proc.kill('SIGKILL');
  }, 2000);
  await exited;
  clearTimeout(timer);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(SCRIPT_DIR, '..');
  const chromeBin = findChrome(opts.chrome);
  const chromeVersion = execFileSync(chromeBin, ['--version'], { encoding: 'utf8' }).trim();
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fidelis-browser-accept-'));
  const profileDir = path.join(tmpDir, 'chrome-profile');
  fs.mkdirSync(profileDir, { recursive: true });
  if (opts.screenshotsDir) fs.mkdirSync(opts.screenshotsDir, { recursive: true });

  let serverProc = null;
  let chromeProc = null;
  let cdp = null;

  try {
    let baseUrl = opts.url;
    if (!baseUrl) {
      const port = await findFreePort();
      const pythonBin = resolvePython(repoRoot, opts.python);
      const workspaceDir = path.join(tmpDir, 'region_jobs');
      serverProc = spawn(
        pythonBin,
        [
          path.join(repoRoot, 'scripts', 'web-ui.py'),
          '--bind', '127.0.0.1',
          '--port', String(port),
          '--region-workspace', workspaceDir,
        ],
        { cwd: repoRoot, stdio: ['ignore', 'pipe', 'pipe'] },
      );
      baseUrl = `http://127.0.0.1:${port}`;
      await waitFor(
        async () => {
          try {
            const res = await fetch(`${baseUrl}/regions`);
            return res.ok;
          } catch {
            return false;
          }
        },
        { timeoutMs: 12000, label: 'Fidelis /regions HTTP startup' },
      );
    }

    const basePng = path.join(tmpDir, 'base.png');
    const texPng = path.join(tmpDir, 'texture.png');
    fs.writeFileSync(
      basePng,
      encodeRgbPng(320, 240, (x, y) => [
        ((x * 3) % 180) + 40,
        ((y * 2) % 160) + 45,
        x >= 80 && x < 240 && y >= 60 && y < 180 ? 210 : 70,
      ]),
    );
    fs.writeFileSync(
      texPng,
      encodeRgbPng(320, 240, (x, y) => [
        x % 16 < 8 ? 225 : 40,
        y % 16 < 8 ? 210 : 60,
        90,
      ]),
    );

    chromeProc = spawn(
      chromeBin,
      [
        '--headless=new',
        '--disable-gpu',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        `--user-data-dir=${profileDir}`,
        '--remote-debugging-port=0',
        'about:blank',
      ],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    );

    const devToolsPort = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Chrome DevTools port timeout')), 10000);
      chromeProc.stderr.on('data', (chunk) => {
        const match = chunk.toString().match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//);
        if (match) {
          clearTimeout(timer);
          resolve(match[1]);
        }
      });
      chromeProc.on('exit', (code) => {
        clearTimeout(timer);
        reject(new Error(`Chrome exited prematurely with code ${code}`));
      });
    });

    const targets = await (await fetch(`http://127.0.0.1:${devToolsPort}/json/list`)).json();
    const pageTarget = targets.find((t) => t.type === 'page') || targets[0];
    cdp = new CdpSession(pageTarget.webSocketDebuggerUrl);
    await cdp.connect();

    const runtimeErrors = [];
    const unexpectedResponses = [];
    const favicon404Urls = [];
    await cdp.send('Page.enable');
    await cdp.send('DOM.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Network.enable');

    cdp.on('Runtime.exceptionThrown', (params) => {
      runtimeErrors.push(params.exceptionDetails?.exception?.description || params.exceptionDetails?.text);
    });
    cdp.on('Runtime.consoleAPICalled', (params) => {
      if (params.type === 'error') {
        const text = (params.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
        // Expected HTTP 409 during stale-revision test and missing /favicon.ico are tracked separately.
        if (!text.includes('409') && !text.includes('404 (Not Found)')) {
          runtimeErrors.push(`console.error: ${text}`);
        }
      }
    });
    cdp.on('Network.responseReceived', (params) => {
      const status = params.response.status;
      const url = params.response.url;
      if (status === 404 && url.endsWith('/favicon.ico')) {
        favicon404Urls.push(url);
        return;
      }
      if (status >= 400 && status !== 409) {
        unexpectedResponses.push(`${status} ${url}`);
      }
    });

    const regionsUrl = `${baseUrl}/regions`;
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send('Page.navigate', { url: regionsUrl });
    await waitFor(
      () => cdp.eval(`document.readyState === 'complete' && document.getElementById('profile')?.options?.length > 0`),
      { label: '/regions ready and profiles populated' },
    );

    const userAgent = await cdp.eval('navigator.userAgent');

    // 1. Set file inputs via real CDP DOM.setFileInputFiles and import passes
    const doc = await cdp.send('DOM.getDocument', { depth: -1 });
    const baseNode = await cdp.send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: '#base' });
    const texNode = await cdp.send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: '#texture' });
    await cdp.send('DOM.setFileInputFiles', { nodeId: baseNode.nodeId, files: [basePng] });
    await cdp.send('DOM.setFileInputFiles', { nodeId: texNode.nodeId, files: [texPng] });

    await cdp.eval(`document.getElementById('import').click()`);
    await waitFor(
      () =>
        cdp.eval(
          `!document.getElementById('canvasBox').hidden && !loadingMask && document.getElementById('paintCanvas').width === 320 && document.getElementById('paintCanvas').height === 240`,
        ),
      { label: 'job created and mask overlay hydrated' },
    );

    const jobAfterCreate = await cdp.eval('current');
    assert.equal(jobAfterCreate.revision, 1);

    // 2. Real mouse pointer stroke painting + non-empty canvas overlay + undo/redo/keyboard + save/reload
    await cdp.eval(`(() => {
      const layer = document.getElementById('paintLayer');
      layer.value = 'protected';
      const mode = document.getElementById('paintMode');
      mode.value = 'paint';
      mode.dispatchEvent(new Event('change'));
      document.getElementById('canvasBox').scrollIntoView({ block: 'center' });
    })()`);
    await new Promise((r) => setTimeout(r, 60));

    const box = await cdp.eval(`(() => {
      const r = document.getElementById('paintCanvas').getBoundingClientRect();
      return { left: r.left, top: r.top, width: r.width, height: r.height };
    })()`);
    assert.ok(box.width > 100 && box.height > 100, `Unexpected canvas box size: ${JSON.stringify(box)}`);

    const startX = box.left + box.width * 0.25;
    const startY = box.top + box.height * 0.35;
    const endX = box.left + box.width * 0.6;
    const endY = box.top + box.height * 0.35;
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: startX, y: startY, button: 'left', clickCount: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: (startX + endX) / 2, y: startY, button: 'left', buttons: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: endX, y: endY, button: 'left', buttons: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: endX, y: endY, button: 'left', clickCount: 1 });

    await waitFor(
      () => cdp.eval(`history.done.length === 1 && !document.getElementById('undo').disabled`),
      { label: 'mouse stroke added to history' },
    );
    await new Promise((r) => setTimeout(r, 120));

    const paintedAlphaSum = await cdp.eval(`(() => {
      const c = document.getElementById('paintCanvas');
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let sum = 0; for (let i = 3; i < d.length; i += 4) sum += d[i]; return sum;
    })()`);
    assert.ok(paintedAlphaSum > 0, 'Canvas overlay did not render mouse stroke pixels');

    // Keyboard Ctrl+Z defect check when focus remains on <select id="paintMode"> vs document body!
    await cdp.eval(`document.getElementById('paintMode').focus()`);
    const focusTagAfterSelect = await cdp.eval(`document.activeElement.tagName`);
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'z', code: 'KeyZ', modifiers: 2, windowsVirtualKeyCode: 90 });
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'z', code: 'KeyZ', modifiers: 2, windowsVirtualKeyCode: 90 });
    const historyAfterCtrlZOnSelect = await cdp.eval('history.done.length');

    // Blur to main body and test keyboard Ctrl+Z & Ctrl+Shift+Z cleanly
    await cdp.eval(`document.getElementById('paintMode').blur(); document.body.focus();`);
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'z', code: 'KeyZ', modifiers: 2, windowsVirtualKeyCode: 90 });
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'z', code: 'KeyZ', modifiers: 2, windowsVirtualKeyCode: 90 });
    await waitFor(() => cdp.eval(`history.done.length === 0 && history.undone.length === 1`), {
      label: 'Ctrl+Z undo via real keyboard event',
    });

    await cdp.eval(`document.getElementById('redo').click()`);
    await waitFor(() => cdp.eval(`history.done.length === 1 && history.undone.length === 0`), {
      label: 'Redo button click',
    });

    if (opts.screenshotsDir) {
      await cdp.eval(`window.scrollTo(0, 0)`);
      await new Promise((r) => setTimeout(r, 80));
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(opts.screenshotsDir, '01-desktop-painted.png'), Buffer.from(shot.data, 'base64'));
    }

    // Save revision -> reload page -> reopen persisted job -> verify saved mask layer
    await cdp.eval(`document.getElementById('save').click()`);
    await waitFor(() => cdp.eval(`!busy && current && current.revision === 2 && history.done.length === 0`), {
      label: 'save revision 2',
    });

    // Verify full-resolution PNG export endpoint responds HTTP 200 with valid PNG signature
    const exportOk = await cdp.eval(`(async () => {
      const res = await fetch(document.getElementById('export').href);
      const buf = new Uint8Array(await res.arrayBuffer());
      return res.ok && buf[0] === 137 && buf[1] === 80 && buf[2] === 78 && buf[3] === 71;
    })()`);
    assert.equal(exportOk, true, 'Export URL failed to return valid PNG');

    await cdp.eval(`window.__fidelisPreReload = true;`);
    await cdp.send('Page.reload', { ignoreCache: true });
    await waitFor(
      () =>
        cdp.eval(
          `!window.__fidelisPreReload && document.readyState === 'complete' && !busy && !document.getElementById('jobs').disabled && document.getElementById('jobs').options.length > 1`,
        ),
      { label: 'reloaded job list populated and unlocked' },
    );
    await cdp.eval(`(() => {
      const jobs = document.getElementById('jobs');
      jobs.value = ${JSON.stringify(jobAfterCreate.id)};
      jobs.dispatchEvent(new Event('change'));
    })()`);
    await waitFor(
      () =>
        cdp.eval(
          `!busy && !loadingMask && Boolean(current) && current.id === ${JSON.stringify(jobAfterCreate.id)} && current.revision === 2`,
        ),
      { label: 'persisted job reopened after reload' },
    );
    await new Promise((r) => setTimeout(r, 120));
    const persistedMaskAlpha = await cdp.eval(`(() => {
      const c = document.getElementById('paintCanvas');
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let sum = 0; for (let i = 3; i < d.length; i += 4) sum += d[i]; return sum;
    })()`);
    assert.ok(persistedMaskAlpha > 0, 'Reloaded job did not render persisted mask overlay');

    // 3. Native 100%/200% inspection checks
    await cdp.eval(`(() => {
      const mode = document.getElementById('paintMode');
      mode.value = 'off';
      mode.dispatchEvent(new Event('change'));
      document.getElementById('inspectNative').click();
    })()`);
    await waitFor(
      () => cdp.eval(`!document.getElementById('nativeScroll').hidden && document.getElementById('nativePair').children.length === 2`),
      { label: 'native inspection crops loaded' },
    );
    const native100Width = await cdp.eval(`document.getElementById('nativePair').style.width`);
    assert.equal(native100Width, '256px');

    await cdp.eval(`(() => {
      const z = document.getElementById('nativeZoom');
      z.value = '2';
      z.dispatchEvent(new Event('change'));
      const s = document.getElementById('nativeSplit');
      s.value = '30';
      s.dispatchEvent(new Event('input'));
    })()`);
    const native200Check = await cdp.eval(`({
      width: document.getElementById('nativePair').style.width,
      clip: document.getElementById('nativePair').children[1].style.clipPath,
      scrollOverflow: document.getElementById('nativeScroll').scrollWidth >= document.getElementById('nativeScroll').clientWidth,
    })`);
    assert.equal(native200Check.width, '512px');
    assert.match(native200Check.clip, /^inset\(0(?:px)? 70% 0(?:px)? 0(?:px)?\)$/);

    if (opts.screenshotsDir) {
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(opts.screenshotsDir, '02-desktop-native-zoom.png'), Buffer.from(shot.data, 'base64'));
    }

    // 4. Stale save conflict test: draw stroke on rev 2 -> out-of-band save bumps to rev 3 -> Save fails 409 without wiping edits
    await cdp.eval(`(() => {
      const mode = document.getElementById('paintMode');
      mode.value = 'paint';
      mode.dispatchEvent(new Event('change'));
      document.getElementById('canvasBox').scrollIntoView({ block: 'center' });
    })()`);
    await new Promise((r) => setTimeout(r, 60));
    const staleBox = await cdp.eval(`(() => {
      const r = document.getElementById('paintCanvas').getBoundingClientRect();
      return { x: r.left + r.width * 0.4, y: r.top + r.height * 0.6 };
    })()`);
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: staleBox.x, y: staleBox.y, button: 'left', clickCount: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: staleBox.x + 25, y: staleBox.y + 10, button: 'left', buttons: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: staleBox.x + 25, y: staleBox.y + 10, button: 'left', clickCount: 1 });
    await waitFor(() => cdp.eval(`history.done.length === 1`), { label: 'unsaved stroke before stale conflict' });

    const externalSaveRes = await fetch(`${baseUrl}/api/regions/jobs/${jobAfterCreate.id}/reblend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: 2,
        blend: { skin: 0.25, hair: 0.2, fabric: 0.15, edge_protection: 0 },
      }),
    });
    assert.equal(externalSaveRes.status, 200);

    await cdp.eval(`document.getElementById('save').click()`);
    await waitFor(
      () => cdp.eval(`!busy && document.getElementById('error').textContent.length > 0`),
      { label: 'stale revision error banner shown' },
    );
    const staleState = await cdp.eval(`({
      error: document.getElementById('error').textContent,
      unsavedCount: history.done.length,
      revisionStill: current.revision,
    })`);
    assert.match(staleState.error, /revision|reload|changed|conflict/i);
    assert.equal(staleState.unsavedCount, 1, 'Unsaved stroke was discarded during stale save conflict');

    if (opts.screenshotsDir) {
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(opts.screenshotsDir, '03-desktop-stale-conflict.png'), Buffer.from(shot.data, 'base64'));
    }

    // Measure desktop canvas visibility when lower sidebar controls (Save button) scroll into view.
    const desktopCanvasBottomWhenSidebarBottomFocused = await cdp.eval(`(() => {
      document.getElementById('save').scrollIntoView({ block: 'center' });
      return Math.round(document.getElementById('canvasBox').getBoundingClientRect().bottom);
    })()`);

    // Discard unsaved edits and switch to mobile 390x844 with real Chrome touch emulation
    await cdp.eval(`document.getElementById('discard').click(); document.getElementById('reload').click();`);
    await waitFor(() => cdp.eval(`!busy && current && current.revision === 3 && history.done.length === 0`), {
      label: 'reloaded revision 3 before mobile touch test',
    });

    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true,
    });
    await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
    await cdp.eval(`(() => {
      document.getElementById('paintLayer').value = 'skin';
      const mode = document.getElementById('paintMode');
      mode.value = 'paint';
      mode.dispatchEvent(new Event('change'));
      document.getElementById('canvasBox').scrollIntoView({ block: 'center' });
    })()`);
    await new Promise((r) => setTimeout(r, 120));

    const mobileMetrics = await cdp.eval(`({
      innerWidth: window.innerWidth,
      docScrollWidth: document.documentElement.scrollWidth,
      canvasRect: (() => {
        const r = document.getElementById('paintCanvas').getBoundingClientRect();
        return { left: r.left, top: r.top, width: r.width, height: r.height };
      })(),
    })`);
    assert.ok(
      mobileMetrics.docScrollWidth <= mobileMetrics.innerWidth,
      `Mobile horizontal overflow detected: scrollWidth=${mobileMetrics.docScrollWidth} > innerWidth=${mobileMetrics.innerWidth}`,
    );

    const tx = mobileMetrics.canvasRect.left + mobileMetrics.canvasRect.width * 0.3;
    const ty = mobileMetrics.canvasRect.top + mobileMetrics.canvasRect.height * 0.5;
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchStart',
      touchPoints: [{ x: tx, y: ty, id: 1 }],
    });
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [{ x: tx + 45, y: ty + 15, id: 1 }],
    });
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchEnd',
      touchPoints: [],
    });
    await waitFor(() => cdp.eval(`history.done.length === 1`), {
      label: 'mobile touch stroke painted onto mask history',
    });

    if (opts.screenshotsDir) {
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(opts.screenshotsDir, '04-mobile-touch-paint.png'), Buffer.from(shot.data, 'base64'));
    }

    assert.equal(runtimeErrors.length, 0, `Browser runtime errors: ${runtimeErrors.join('; ')}`);
    assert.equal(unexpectedResponses.length, 0, `Unexpected HTTP >=400 responses: ${unexpectedResponses.join('; ')}`);

    const observedDefects = [];
    if (historyAfterCtrlZOnSelect !== 0) {
      observedDefects.push({
        id: 'UX-KEYBOARD-FOCUS-TRAP',
        severity: 'minor',
        detail:
          `Pressing Ctrl+Z while focus remains on <select id="paintMode"> (activeElement=${focusTagAfterSelect}) ` +
          'is ignored because the global keydown handler skips all INPUT/SELECT/TEXTAREA tags.',
      });
    }
    if (favicon404Urls.length > 0) {
      observedDefects.push({
        id: 'MISSING-FAVICON-404',
        severity: 'minor',
        detail: `Browser requested /favicon.ico and received HTTP 404 (${favicon404Urls.length}x).`,
      });
    }
    if (desktopCanvasBottomWhenSidebarBottomFocused <= 0) {
      observedDefects.push({
        id: 'UX-DESKTOP-CANVAS-SCROLL',
        severity: 'minor',
        detail:
          `Scrolling lower sidebar controls (#save) into view on 1440x900 scrolls #canvasBox off the top ` +
          `of the viewport (bottom=${desktopCanvasBottomWhenSidebarBottomFocused}px) because <aside> and <main> share page scroll.`,
      });
    }

    const report = {
      schema_version: 1,
      browser_version: chromeVersion,
      user_agent: userAgent,
      platform: `${os.platform()} ${os.arch()} (${os.release()})`,
      target_url: regionsUrl,
      viewports_tested: [
        { name: 'desktop', width: 1440, height: 900, mobile: false, touch: false },
        { name: 'mobile_emulated', width: 390, height: 844, mobile: true, touch: true },
      ],
      checks: {
        file_input_upload_and_import: true,
        mouse_pointer_paint_and_canvas_render: true,
        keyboard_ctrl_z_after_blur: true,
        redo_button: true,
        save_and_reload_persistence: true,
        export_png_download_200: true,
        native_100_200_crop_and_split: true,
        stale_409_conflict_preserves_unsaved_edit: true,
        mobile_390_no_horizontal_overflow: true,
        mobile_touch_event_paint: true,
        runtime_error_count: runtimeErrors.length,
        unexpected_http_error_count: unexpectedResponses.length,
      },
      measurements: {
        painted_alpha_sum_desktop: paintedAlphaSum,
        persisted_alpha_sum_after_reload: persistedMaskAlpha,
        native_100_width: native100Width,
        native_200_width: native200Check.width,
        mobile_scroll_width: mobileMetrics.docScrollWidth,
        mobile_inner_width: mobileMetrics.innerWidth,
        desktop_canvas_bottom_when_save_scrolled: desktopCanvasBottomWhenSidebarBottomFocused,
        favicon_404_count: favicon404Urls.length,
        stale_error_message: staleState.error,
      },
      observed_defects: observedDefects,
      screenshots_dir: opts.screenshotsDir || null,
      limitations: [
        'Verified in HeadlessChrome on macOS host loopback (127.0.0.1); physical Android/iOS touch hardware, Apple Pencil/stylus tilt/pressure and human visual signoff remain separate open gates.',
      ],
    };

    const formatted = JSON.stringify(report, null, 2) + '\n';
    if (opts.report) {
      fs.mkdirSync(path.dirname(opts.report), { recursive: true });
      fs.writeFileSync(opts.report, formatted, 'utf8');
    }
    process.stdout.write(formatted);
  } finally {
    if (cdp) cdp.close();
    await stopProcess(chromeProc);
    await stopProcess(serverProc);
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
