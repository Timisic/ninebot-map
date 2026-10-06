import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { chromium } from 'playwright';

const root = process.cwd();
const output = path.resolve(process.env.VERIFICATION_OUTPUT || 'work/startup-verification');
await fs.mkdir(output, { recursive: true });
const scratch = await fs.mkdtemp(path.join(root, 'work/startup-'));
const site = path.join(scratch, 'map');
execFileSync('./run', ['export-site', '--dataset', 'tests/fixtures/synthetic-map.json', '--output', site]);
const dataset = await fs.readFile(path.join(site, 'dataset.json'));
const zero = JSON.parse(dataset);
zero.tracks = [];
Object.assign(zero.summary, { map_ride_count: 0, map_distance_m: 0, map_point_count: 0, map_exclusions: { insufficient_points: 12 } });
const scenarios = new Map();
const requests = [];
const timers = new Set();
const later = (callback, milliseconds) => {
  const timer = setTimeout(() => { timers.delete(timer); callback(); }, milliseconds);
  timers.add(timer);
};
const types = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.woff2': 'font/woff2' };
const csp = "default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'";
const server = createServer(async (request, response) => {
  const match = request.url.match(/^\/case\/([^/]+)\/map\/(.*)$/);
  if (!match || match[2].includes('..') || match[2].includes('?')) { response.writeHead(404).end(); return; }
  const [, name, asset] = match, scenario = scenarios.get(name);
  if (!scenario) { response.writeHead(404).end(); return; }
  const record = { scenario: name, method: request.method, path: request.url, at: performance.now() };
  requests.push(record);
  response.on('finish', () => { record.finished = performance.now(); record.status = response.statusCode; });
  response.on('close', () => { record.closed = performance.now(); });
  if (asset === 'dataset.json') {
    if (scenario.kind === 'network') { request.socket.destroy(); return; }
    const status = scenario.kind === 'missing' ? 404 : scenario.kind === 'http' ? 503 : 200;
    if (request.method === 'HEAD') { response.writeHead(status, { ETag: '"startup-test"' }).end(); return; }
    const bytes = scenario.kind === 'zero' ? Buffer.from(JSON.stringify(zero)) : scenario.kind === 'invalid' ? Buffer.from('{') : dataset;
    response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...(!scenario.noETag ? { ETag: '"startup-test"' } : {}), ...(scenario.kind === 'body' ? { 'Content-Length': bytes.length + 50 } : {}) });
    response.flushHeaders();
    if (scenario.kind === 'body') {
      response.write(bytes.subarray(0, 25));
      later(() => response.destroy(), 80);
    } else if (scenario.holdBody) scenario.releaseBody = () => response.end(bytes);
    else later(() => response.end(bytes), scenario.bodyDelay || 0);
    return;
  }
  if (asset === 'api/update') {
    if (scenario.holdStatus) {
      if (!scenario.holdStatusHeaders) { response.writeHead(200, { 'Content-Type': 'application/json' }); response.flushHeaders(); }
      scenario.releaseStatus = () => {
        if (scenario.holdStatusHeaders) response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ phase: 'queued', can_request: false, requested_at: '2026-01-01T00:00:00Z', next_allowed_at: null }));
      };
    } else response.writeHead(404).end();
    return;
  }
  if (scenario.kind === 'entry-missing' && asset.endsWith('/startup.js')) { response.writeHead(404).end(); return; }
  try {
    const bytes = await fs.readFile(path.join(site, asset || 'index.html'));
    const headers = { 'Content-Type': types[path.extname(asset || 'index.html')] || 'text/plain', 'Cache-Control': 'no-store', 'Content-Security-Policy': csp };
    const send = () => response.writeHead(200, headers).end(bytes);
    if (asset.endsWith('/app.mjs') && scenario.appDelay) later(send, scenario.appDelay);
    else send();
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
const cases = [];
let cleanup;
try {
  browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? {} : { channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }), headless: true });
  async function open(name, scenario, instrumentation) {
    scenarios.set(name, scenario);
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const errors = [], external = [], violations = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (!request.url().startsWith(origin) && !request.url().startsWith('data:')) external.push(request.url()); });
    await page.addInitScript(() => {
      window.__violations = [];
      window.__fetches = [];
      window.__intervals = new Set();
      const setInterval = window.setInterval, clearInterval = window.clearInterval;
      window.setInterval = (...args) => { const id = setInterval(...args); window.__intervals.add(id); return id; };
      window.clearInterval = id => { window.__intervals.delete(id); clearInterval(id); };
      const fetch = window.fetch;
      window.fetch = (input, options) => { window.__fetches.push({ url: String(input), method: options?.method || 'GET' }); return fetch(input, options); };
      document.addEventListener('securitypolicyviolation', event => window.__violations.push(event.violatedDirective));
    });
    if (instrumentation) await page.addInitScript(instrumentation);
    await page.goto(`${origin}/case/${name}/map/${scenario.basemap ? '#basemap=osm' : ''}`, { waitUntil: 'commit' });
    return { page, context, errors, external, violations, name };
  }
  async function finish(test, details = {}) {
    assert.deepEqual(test.errors, [], test.name);
    assert.deepEqual(test.external, [], test.name);
    const violations = await test.page.evaluate(() => window.__violations);
    assert.deepEqual(violations, [], test.name);
    const dataRequests = requests.filter(request => request.scenario === test.name && request.method === 'GET' && request.path.endsWith('/dataset.json'));
    const fetches = await test.page.evaluate(() => window.__fetches.filter(request => request.method === 'GET' && request.url.endsWith('/dataset.json')));
    assert.equal(fetches.length, details.startupMissing ? 0 : details.refresh ? 2 : 1, test.name);
    if (test.name !== 'network') assert.equal(dataRequests.length, fetches.length, test.name);
    else assert.ok(dataRequests.length >= 1, 'Native TCP retries are distinct from application fetch calls.');
    cases.push({ name: test.name, ...details, fetches, dataRequests, errors: test.errors, external: test.external, violations });
    await test.context.close();
  }
  const delayed = await open('delayed', { kind: 'valid', appDelay: 600, holdBody: true });
  await delayed.page.waitForFunction(() => document.querySelector('#visible-stat'));
  assert.equal(await delayed.page.locator('#empty').isVisible(), false);
  assert.match(await delayed.page.locator('#visible-stat').textContent(), /读取中/);
  assert.equal(await delayed.page.locator('#update-status').textContent(), '正在加载路线…');
  assert.equal(requests.filter(request => request.scenario === 'delayed' && request.path.endsWith('/dataset.json')).length, 1);
  await delayed.page.waitForFunction(() => document.querySelector('.route-canvas'));
  assert.match(await delayed.page.locator('#history-stat').textContent(), /读取中/);
  scenarios.get('delayed').releaseBody();
  await delayed.page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  const assets = requests.filter(request => request.scenario === 'delayed' && /\.mjs$/.test(request.path));
  assert.equal(new Set(assets.map(request => request.path)).size, assets.length, 'Preloaded imports reuse each module URL.');
  assert.equal(assets.length, 6);
  assert.ok(assets.every(request => /\/map\/assets\/[a-f0-9]{64}\//.test(request.path)));
  const dataRequest = requests.find(request => request.scenario === 'delayed' && request.path.endsWith('/dataset.json'));
  const appRequest = assets.find(request => request.path.endsWith('/app.mjs'));
  assert.ok(dataRequest.at < appRequest.finished, 'Dataset starts before app evaluation can start.');
  await delayed.page.screenshot({ path: path.join(output, 'startup-ready.png') });
  assert.equal(await delayed.page.evaluate(() => 'dataset' in window.alongStartup), false, 'App releases the consumed text handoff.');
  await finish(delayed, { truthfulPending: true, modules: assets });
  const missingEntry = await open('entry-missing', { kind: 'entry-missing' });
  await missingEntry.page.waitForFunction(() => !document.querySelector('#error').hidden);
  assert.equal(await missingEntry.page.locator('#error').textContent(), '地图页面未能加载，请稍后刷新。');
  assert.equal(await missingEntry.page.locator('#empty').isVisible(), false);
  assert.equal(await missingEntry.page.locator('#update-status').isVisible(), false);
  assert.match(await missingEntry.page.locator('#history-stat').textContent(), /未能读取/);
  assert.equal(await missingEntry.page.locator('.route-canvas').count(), 0);
  await finish(missingEntry, { startupMissing: true, noFallbackFetch: true });
  for (const kind of ['missing', 'http', 'network', 'body', 'invalid', 'zero']) {
    const test = await open(kind, { kind });
    if (kind === 'missing') {
      await test.page.waitForFunction(() => !document.querySelector('#empty').hidden);
      assert.equal(await test.page.locator('#empty-title').textContent(), '地图数据尚未发布');
      assert.equal(await test.page.locator('#error').isVisible(), false);
    } else if (kind === 'zero') {
      await test.page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('0 次'));
      assert.match(await test.page.locator('#history-stat').textContent(), /12 次/);
      assert.equal(await test.page.locator('#empty-title').textContent(), '历史已保留，暂无地图轨迹');
      assert.equal(await test.page.locator('#error').isVisible(), false);
    } else {
      await test.page.waitForFunction(() => !document.querySelector('#error').hidden);
      assert.equal(await test.page.locator('#empty').isVisible(), false);
      assert.match(await test.page.locator('#visible-stat').textContent(), /未能读取/);
    }
    if (kind === 'invalid') {
      scenarios.get(kind).kind = 'valid';
      await test.page.evaluate(() => window.dispatchEvent(new Event('focus')));
      await test.page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
    }
    await test.page.waitForFunction(() => document.querySelector('#update-map').title.includes('暂不支持'));
    assert.equal(await test.page.locator('#update-status').isVisible(), false);
    await finish(test, { refresh: kind === 'invalid', validatedETag: kind === 'invalid' });
  }
  const pauseDigests = () => {
    window.__digests = [];
    const digest = crypto.subtle.digest.bind(crypto.subtle);
    crypto.subtle.digest = (...args) => new Promise(resolve => window.__digests.push(async () => resolve(await digest(...args))));
    const get = Storage.prototype.getItem;
    Storage.prototype.getItem = function(key) { if (key.startsWith('ride-map-labels:')) throw new Error('Storage unavailable'); return get.call(this, key); };
  };
  for (const [name, scenario, instrumentation, wait] of [
    ['close-before-app', { kind: 'valid', appDelay: 600, holdBody: true }, null, () => !!document.querySelector('#map') && !document.querySelector('.route-canvas') && !!window.alongStartup],
    ['close-body', { kind: 'valid', holdBody: true }, null, () => !!document.querySelector('.route-canvas')],
    ['close-frame', { kind: 'valid' }, () => {
      window.__frames = new Map(); let next = 1;
      window.requestAnimationFrame = callback => { const id = next++; window.__frames.set(id, callback); return id; };
      window.cancelAnimationFrame = id => window.__frames.delete(id);
    }, () => document.querySelector('#local-status')?.textContent === '正在读取…'],
    ['close-labels', { kind: 'valid', basemap: true }, pauseDigests, () => window.__digests?.length === 2],
    ['close-revision', { kind: 'valid', noETag: true, basemap: true }, pauseDigests, () => window.__digests?.length === 2],
    ['close-status-body', { kind: 'valid', holdStatus: true }, null, () => document.querySelector('#visible-stat')?.textContent.includes('12 次')],
    ['close-status-headers', { kind: 'valid', holdStatus: true, holdStatusHeaders: true }, null, () => document.querySelector('#visible-stat')?.textContent.includes('12 次')]
  ]) {
    const test = await open(name, scenario, instrumentation);
    await test.page.waitForFunction(wait);
    if (name === 'close-revision') {
      await test.page.evaluate(async () => Promise.all(window.__digests.map(release => release())));
      await test.page.waitForFunction(() => window.__digests.length === 3);
    }
    if (scenario.holdStatus) {
      const deadline = performance.now() + 5000;
      while (!scenario.releaseStatus && performance.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
      assert.equal(typeof scenario.releaseStatus, 'function', 'The status request must reach the owned server.');
    }
    const before = await test.page.evaluate(() => ({ html: document.querySelector('.topbar').innerHTML + document.querySelector('.toolbar').innerHTML + document.querySelector('.map-summary').innerHTML, note: document.querySelector('#label-note').textContent }));
    await test.page.evaluate(() => { window.__transportResult = window.alongStartup.dataset; window.dispatchEvent(new Event('pagehide')); });
    if (scenario.releaseBody) scenario.releaseBody();
    if (scenario.releaseStatus) scenario.releaseStatus();
    await test.page.evaluate(async () => {
      if (window.__digests) await Promise.all(window.__digests.map(release => release()));
    });
    await test.page.waitForTimeout(700);
    const after = await test.page.evaluate(() => ({ html: document.querySelector('.topbar').innerHTML + document.querySelector('.toolbar').innerHTML + document.querySelector('.map-summary').innerHTML, note: document.querySelector('#label-note').textContent, closed: window.alongStartup.closed, canvas: !!document.querySelector('.route-canvas'), frames: window.__frames?.size || 0, intervals: window.__intervals.size }));
    assert.equal(after.closed, true); assert.equal(after.canvas, false); assert.equal(after.frames, 0);
    assert.equal(after.intervals, 0);
    assert.equal(after.html, before.html); assert.equal(after.note, before.note);
    if (name === 'close-before-app' || name === 'close-body') assert.equal(await test.page.evaluate(async () => (await window.__transportResult).kind), 'closed');
    await finish(test, { closedAt: name, noLateCommit: true, canceledFrames: after.frames, remainingIntervals: after.intervals });
  }
} finally {
  await browser?.close();
  for (const timer of timers) clearTimeout(timer);
  await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
  await fs.rm(scratch, { recursive: true, force: true });
  let socketClosed = false;
  try { await fetch(origin); } catch { socketClosed = true; }
  cleanup = { serverClosed: !server.listening, socketClosed, scratchRemoved: !(await fs.stat(scratch).catch(() => false)) };
  await fs.writeFile(path.join(output, 'startup.json'), JSON.stringify({ passed: cases.length === 15, synthetic: true, withoutRequestInterception: true, cases, cleanup }, null, 2));
}
assert.equal(cases.length, 15);
assert.deepEqual(cleanup, { serverClosed: true, socketClosed: true, scratchRemoved: true });
console.log('Startup passed: one early dataset GET, truthful loading, missing and failed results, zero tracks, nested CSP-safe modules, validated revisions, and closed-page cleanup.');
