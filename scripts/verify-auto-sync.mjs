import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import net from 'node:net';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { makeDataset } from '../tests/map-fixture.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const evidence = process.env.VERIFICATION_OUTPUT ? path.resolve(process.env.VERIFICATION_OUTPUT) : null;
if (evidence) await fs.mkdir(evidence, { recursive: true });
const proof = { source: 'synthetic_test_not_real_rides', actions: [], passed: false };
async function record(action, result) {
  proof.actions.push({ action, result, at: new Date().toISOString() });
  if (evidence) await fs.writeFile(path.join(evidence, 'refresh.json'), JSON.stringify(proof, null, 2) + '\n');
}
async function doctor(url, expected) {
  const response = await fetch(url + 'dataset.json', { signal: AbortSignal.timeout(5000) });
  assert.equal(response.status, 200);
  const bytes = await response.text();
  const dataset = JSON.parse(bytes);
  assert.deepEqual(dataset.summary, expected.summary);
  assert.equal(response.headers.get('etag'), '"' + createHash('sha256').update(bytes).digest('hex') + '"');
  const head = await fetch(url + 'dataset.json', { method: 'HEAD', signal: AbortSignal.timeout(5000) });
  assert.equal(head.headers.get('etag'), response.headers.get('etag'));
  const result = { url, process_pid: server.pid, summary: dataset.summary, etag: response.headers.get('etag') };
  await record('Read-only HTTP doctor: GET summary and content hash match HEAD ETag', result);
  return result;
}
function socketOpen(url) {
  return new Promise(resolve => {
    const socket = net.connect({ host: '127.0.0.1', port: Number(new URL(url).port) });
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('error', () => resolve(false));
    socket.setTimeout(1000, () => { socket.destroy(); resolve(true); });
  });
}
await fs.mkdir(path.join(root, 'work'), { recursive: true });
const directory = await fs.mkdtemp(path.join(root, 'work', 'map-refresh-'));
const datasetPath = path.join(directory, 'dataset.json');
const old = makeDataset([{ id: 'old', xy: [[0, 0], [100, 0], [200, 0]], date: '2026-01-10' }]);
const fresh = makeDataset([
  { id: 'old', xy: [[0, 0], [100, 0], [200, 0]], date: '2026-01-10' },
  { id: 'new', xy: [[0, 0], [100, 0], [200, 0]], date: '2026-01-11' },
]);
async function replace(value) {
  await fs.writeFile(datasetPath + '.writing', JSON.stringify(value));
  await fs.rename(datasetPath + '.writing', datasetPath);
}
await replace(old);
const server = spawn('./run', ['map', '--dataset', datasetPath, '--port', '0', '--no-open'], { cwd: root });
let browser, url;
let serverOutput = '';
server.stdout.on('data', chunk => { serverOutput += chunk; });
server.stderr.on('data', chunk => { serverOutput += chunk; });
try {
  url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error('Map did not start')), 10000);
    server.on('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}`)); });
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.stdout.on('data', chunk => {
      output += chunk;
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
  });
  await doctor(url, old);
  browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? {} : { channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }), headless: true });
  const context = await browser.newContext();
  const external = [], errors = [];
  await context.route('**/*', route => {
    if (!route.request().url().startsWith(url) && !route.request().url().startsWith('data:')) {
      external.push(route.request().url()); route.abort();
    } else route.continue();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('#history-stat').textContent.includes('1 次'));
  if (evidence) await page.screenshot({ path: path.join(evidence, 'before.png') });
  await record('Launch normal map CLI with synthetic dataset', { history: await page.locator('#history-stat').textContent() });
  await page.locator('#date-panel > summary').click();
  await page.locator('#from').fill('2026-01-10');
  await page.locator('#from').dispatchEvent('change');
  await page.locator('#to').fill('2026-01-10');
  await page.locator('#to').dispatchEvent('change');
  await page.locator('#date-panel > summary').click();
  await page.locator('#map-options > summary').click();
  await page.locator('#show-grid').check();
  await page.locator('#map-options > summary').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  await page.locator('#edit-place').click(); await page.locator('#place-label').fill('Synthetic saved label');
  await page.locator('#label-form button[type=submit]').click();
  const view = await page.locator('.leaflet-map-pane').getAttribute('style');
  await record('Set date range, grid, saved label and preserve view', { from: '2026-01-10', to: '2026-01-10', grid: true, label: 'Synthetic saved label', view });
  await replace(fresh);
  const freshSnapshot = await doctor(url, fresh);
  await record('Atomically replace server dataset then focus browser', { ride_count: fresh.summary.ride_count });
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(() => document.querySelector('#history-stat').textContent.includes('2 次'));
  assert.match(await page.locator('#visible-stat').textContent(), /1 次/);
  assert.equal(await page.locator('#from').inputValue(), '2026-01-10');
  assert.equal(await page.locator('#to').inputValue(), '2026-01-10');
  assert.equal(await page.locator('#show-grid').isChecked(), true);
  assert.equal(await page.locator('.place-name').first().textContent(), 'Synthetic saved label');
  assert.equal(await page.locator('.leaflet-map-pane').getAttribute('style'), view);
  if (evidence) await page.screenshot({ path: path.join(evidence, 'after.png') });
  await record('Browser refreshed and retained preferences', { history: await page.locator('#history-stat').textContent(), visible: await page.locator('#visible-stat').textContent(), view: await page.locator('.leaflet-map-pane').getAttribute('style') });
  await replace({ invalid: true });
  assert.equal((await doctor(url, fresh)).etag, freshSnapshot.etag);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  assert.match(await page.locator('#history-stat').textContent(), /2 次/);
  assert.equal(await page.locator('input[type=file], #import-button').count(), 0);
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  proof.passed = true;
  await record('No external requests or page errors', { external, errors });
  console.log('Synthetic browser refresh passed: live update, date/grid/labels/view retained, invalid update retained, no manual import, zero external requests.');
} catch (error) {
  await record('Failed verification', { message: error.message });
  throw error;
} finally {
  try { await browser?.close(); } finally {
    if (server.exitCode === null && server.signalCode === null) {
      await new Promise(resolve => {
        server.once('exit', resolve);
        server.kill('SIGTERM');
        const timer = setTimeout(() => server.kill('SIGKILL'), 5000);
        server.once('exit', () => clearTimeout(timer));
      });
    }
    const closed = !url || !(await socketOpen(url));
    await fs.rm(directory, { recursive: true, force: true });
    if (evidence) await fs.writeFile(path.join(evidence, 'server.log'), serverOutput);
    proof.passed &&= closed;
    await record('Cleanup owned server and scratch dataset', { process_pid: server.pid, socket_closed: closed, scratch_removed: true });
    assert.equal(closed, true, 'Owned map socket must be closed after cleanup');
  }
}
