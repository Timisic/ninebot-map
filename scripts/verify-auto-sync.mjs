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
  assert.equal(await page.locator('#date-panel, #from, #to').count(), 0);
  await page.locator('#map-options > summary').click();
  await page.locator('#show-grid').check();
  await page.locator('#map-options > summary').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  await page.locator('#edit-place').click(); await page.locator('#place-label').fill('Synthetic saved label');
  await page.locator('#label-form button[type=submit]').click();
  const view = await page.locator('.leaflet-map-pane').getAttribute('style');
  await record('Set grid, saved label and preserve view', { grid: true, label: 'Synthetic saved label', view });
  await replace(fresh);
  const freshSnapshot = await doctor(url, fresh);
  await record('Atomically replace server dataset then focus browser', { ride_count: fresh.summary.ride_count });
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(() => document.querySelector('#history-stat').textContent.includes('2 次'));
  assert.match(await page.locator('#visible-stat').textContent(), /2 次/);
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
  assert.equal(await page.locator('#update-map').isDisabled(), true);
  assert.match(await page.locator('#update-map').getAttribute('title'), /暂不支持/);

  let updateStatus = { phase: 'idle', can_request: true, requested_at: null, next_allowed_at: null };
  let responseCode = 202, postCount = 0;
  const requestedAt = '2026-10-06T00:00:00Z';
  const nextAllowedAt = new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString();
  await page.route(url + 'api/update', async route => {
    const request = route.request();
    if (request.method() === 'POST') {
      postCount++;
      assert.equal(request.headers()['content-type'], 'application/json');
      assert.equal(request.postData(), '{}');
      if (responseCode === 202) updateStatus = { phase: 'queued', can_request: false, requested_at: requestedAt, next_allowed_at: nextAllowedAt };
    }
    await route.fulfill({ status: request.method() === 'POST' ? responseCode : 200, contentType: 'application/json', body: JSON.stringify(updateStatus) });
  });
  await replace(fresh);
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#update-map').disabled);
  await page.locator('#map-options > summary').click();
  await page.locator('#show-grid').check();
  await page.locator('#map-options > summary').click();
  await page.locator('#theme-toggle').click();
  await page.locator('button[data-theme-preference=dark]').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  const selectedId = await page.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id');
  await page.locator('#edit-place').click();
  await page.locator('#place-label').fill('Synthetic unsaved draft');
  const updateView = await page.locator('.leaflet-map-pane').getAttribute('style');
  await page.locator('#update-map').click();
  await page.waitForFunction(() => document.querySelector('#update-status').textContent === '等待更新');
  assert.equal(postCount, 1);
  await page.locator('#update-map').click();
  assert.equal(await page.locator('#inline-hint').textContent(), '正在Riding中...');
  const ridingHint = await page.locator('#inline-hint').evaluate(element => {
    const style = getComputedStyle(element); return [style.backgroundColor, style.color, style.fontSize, style.borderRadius];
  });
  await page.locator('#running').click();
  assert.equal(await page.locator('#inline-hint').textContent(), '正在running中...');
  assert.deepEqual(await page.locator('#inline-hint').evaluate(element => {
    const style = getComputedStyle(element); return [style.backgroundColor, style.color, style.fontSize, style.borderRadius];
  }), ridingHint);
  assert.equal(postCount, 1);
  updateStatus.phase = 'running';
  await page.waitForFunction(() => document.querySelector('#update-status').textContent === '更新中');
  updateStatus.phase = 'succeeded';
  await page.waitForFunction(() => document.querySelector('#update-status').textContent === '等待地图更新');
  assert.match(await page.locator('#visible-stat').textContent(), /2 次/);
  const published = makeDataset([
    { id: 'old', xy: [[0, 0], [100, 0], [200, 0]], date: '2026-01-10' },
    { id: 'new', xy: [[0, 0], [100, 0], [200, 0]], date: '2026-01-11' },
    { id: 'published', xy: [[0, 0], [100, 0], [200, 0]], date: '2026-01-12' },
  ]);
  published.updated_at = '2026-10-06T00:01:00Z';
  await replace(published);
  await page.waitForFunction(() => document.querySelector('#update-status').textContent === '地图已更新');
  assert.match(await page.locator('#visible-stat').textContent(), /3 次/);
  assert.equal(await page.locator('#place-label').inputValue(), 'Synthetic unsaved draft');
  assert.equal(await page.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id'), selectedId);
  assert.equal(await page.locator('#show-grid').isChecked(), true);
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal(await page.locator('.leaflet-map-pane').getAttribute('style'), updateView);
  await record('Public update waits for workflow and published data, retaining draft, selection, grid, theme and view', { postCount, history: await page.locator('#history-stat').textContent(), status: await page.locator('#update-status').textContent() });

  updateStatus = { phase: 'idle', can_request: true, requested_at: null, next_allowed_at: null };
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#update-map').disabled);
  responseCode = 429;
  updateStatus = { phase: 'succeeded', can_request: false, requested_at: requestedAt, next_allowed_at: nextAllowedAt };
  await page.locator('#update-map').click();
  await page.waitForFunction(() => document.querySelector('#inline-hint').textContent === '正在Riding中...');
  assert.equal(postCount, 2);
  await page.locator('#update-map').click();
  assert.equal(postCount, 2);
  await record('Server cooldown and repeated clicks share the activity hint without further dispatch', { postCount });

  for (const [code, phase, hint] of [[502, 'failed', '更新未能开始'], [503, 'unavailable', '更新服务暂不可用']]) {
    updateStatus = { phase: 'idle', can_request: true, requested_at: null, next_allowed_at: null };
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('#update-map').disabled);
    responseCode = code;
    updateStatus = { phase, can_request: code === 502, requested_at: null, next_allowed_at: null };
    await page.locator('#update-map').click();
    await page.waitForFunction(text => document.querySelector('#inline-hint').textContent.includes(text), hint);
    assert.match(await page.locator('#visible-stat').textContent(), /3 次/);
    assert.equal(await page.locator('#error').isVisible(), false);
    if (code === 502) assert.match(await page.locator('#update-status').textContent(), /未完成/);
    if (code === 503) assert.equal(await page.locator('#update-map').isDisabled(), true);
  }
  await record('Dispatch rejection and unavailable update service retain the visible map', { postCount, phases: ['failed', 'unavailable'] });
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  proof.passed = true;
  await record('No external requests or page errors', { external, errors });
  console.log('Synthetic browser refresh passed: live update, grid/labels/view retained, invalid update retained, no manual import, zero external requests.');
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
