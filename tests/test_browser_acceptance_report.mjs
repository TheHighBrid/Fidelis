import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { CdpSession, writeAcceptanceReport } from '../scripts/browser-acceptance.mjs';

function report(overrides = {}) {
  return {
    checks: { mouse_pointer_paint: true, runtime_error_count: 0 },
    observed_defects: [],
    ...overrides,
  };
}

test('all required checks pass and no defects yields exit zero', () => {
  let output = '';
  const code = writeAcceptanceReport(report(), null, { write: (s) => { output += s; } });
  assert.equal(code, 0);
  assert.equal(JSON.parse(output).acceptance_passed, true);
  assert.deepEqual(JSON.parse(output).failed_checks, []);
});

test('false checks and nonzero error counts fail closed and preserve diagnostics', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fidelis-report-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'receipt.json');
  let output = '';
  const code = writeAcceptanceReport(report({
    checks: { mouse_pointer_paint: false, runtime_error_count: 2 },
  }), file, { write: (s) => { output += s; } });
  assert.equal(code, 1);
  const receipt = JSON.parse(output);
  assert.equal(receipt.acceptance_passed, false);
  assert.deepEqual(receipt.failed_checks, ['mouse_pointer_paint', 'runtime_error_count']);
  assert.equal(fs.readFileSync(file, 'utf8'), output);
});

test('reported UI regression fails the gate even when functional checks pass', () => {
  let output = '';
  const code = writeAcceptanceReport(report({
    observed_defects: [{ id: 'UX-DESKTOP-CANVAS-SCROLL', severity: 'minor' }],
  }), null, { write: (s) => { output += s; } });
  const receipt = JSON.parse(output);
  assert.equal(code, 1);
  assert.equal(receipt.acceptance_passed, false);
  assert.equal(receipt.observed_defects[0].id, 'UX-DESKTOP-CANVAS-SCROLL');
});

test('missing or invalid measured values cannot count as successful checks', () => {
  let output = '';
  const code = writeAcceptanceReport(report({
    checks: { paint: null, export: 1, runtime_error_count: false, http_error_count: -1 },
  }), null, { write: (s) => { output += s; } });
  assert.equal(code, 1);
  assert.equal(JSON.parse(output).failed_checks.length, 4);
});

test('an empty measurement report never passes', () => {
  assert.equal(writeAcceptanceReport(report({ checks: {} }), null, { write() {} }), 1);
});

async function connectedSession(timeoutMs = 30) {
  const socket = { send() {} };
  const session = new CdpSession('unused', { socket, timeoutMs });
  const connected = session.connect();
  socket.onopen();
  await connected;
  return { session, socket };
}

test('CDP connection and unanswered commands are bounded', async () => {
  const disconnected = new CdpSession('unused', { socket: {}, timeoutMs: 20 });
  await assert.rejects(disconnected.connect(), /connection timed out/);
  const { session } = await connectedSession();
  await assert.rejects(session.send('Runtime.evaluate'), /Runtime.evaluate timed out/);
  assert.equal(session.pending.size, 0);
});

test('CDP replies clear timeouts, while a closed transport rejects pending work', async () => {
  const { session, socket } = await connectedSession();
  const call = session.send('Page.enable');
  socket.onmessage({ data: JSON.stringify({ id: 1, result: { enabled: true } }) });
  assert.deepEqual(await call, { enabled: true });
  const pending = session.send('Page.navigate');
  socket.onclose();
  await assert.rejects(pending, /WebSocket closed/);
  assert.equal(session.pending.size, 0);
});

test('CDP close during opening and synchronous send failure reject promptly', async () => {
  const socket = {};
  const session = new CdpSession('unused', { socket, timeoutMs: 100 });
  const connection = session.connect();
  socket.onclose();
  await assert.rejects(connection, /closed during connection/);
  const connected = await connectedSession();
  connected.socket.send = () => { throw new Error('send failed'); };
  await assert.rejects(connected.session.send('Page.enable'), /send failed/);
  assert.equal(connected.session.pending.size, 0);
});

test('report publication rejects a symlink without modifying its target', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fidelis-report-link-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const target = path.join(dir, 'existing.json');
  const link = path.join(dir, 'receipt.json');
  fs.writeFileSync(target, 'original');
  fs.symlinkSync(target, link);
  assert.throws(() => writeAcceptanceReport(report(), link, { write() {} }), /regular file/);
  assert.equal(fs.readFileSync(target, 'utf8'), 'original');
  assert.ok(fs.lstatSync(link).isSymbolicLink());
});
