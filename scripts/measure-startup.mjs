import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { chromium } from 'playwright';

const [beforeArgument, afterArgument, outputArgument] = process.argv.slice(2);
if (!beforeArgument || !afterArgument || !outputArgument) throw new Error('Usage: node scripts/measure-startup.mjs BEFORE_EXPORT AFTER_EXPORT OUTPUT_DIRECTORY');
const before = path.resolve(beforeArgument), after = path.resolve(afterArgument), output = path.resolve(outputArgument);
await fs.mkdir(output, { recursive: true });
const input = await fs.readFile(path.join(before, 'dataset.json'));
assert.deepEqual(await fs.readFile(path.join(after, 'dataset.json')), input, 'Both exports must have exactly the same dataset bytes.');
const dataset = JSON.parse(input), inputHash = createHash('sha256').update(input).digest('hex');
const expected = { visible: dataset.summary.map_ride_count, history: dataset.summary.ride_count, tracks: dataset.tracks.length, bytes: input.length, sha256: inputHash };
assert.ok(expected.tracks > 0, 'A first route drawing comparison needs actual routes.');
const delay = { request_ms: 120, extra_data_body_ms: 180 };
const claim = 'The complete first route draw finishes earlier for the same captured dataset on fresh browser contexts with fixed request and data-body delays.';
const load = execFileSync('uptime', { encoding: 'utf8' }).trim();
const cores = Number(execFileSync(process.platform === 'darwin' ? 'sysctl' : 'nproc', process.platform === 'darwin' ? ['-n', 'hw.logicalcpu'] : [], { encoding: 'utf8' }).trim());
const requests = [], timers = new Set();
const later = (callback, milliseconds) => {
  const timer = setTimeout(() => { timers.delete(timer); callback(); }, milliseconds);
  timers.add(timer);
};
const types = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = createServer(async (request, response) => {
  const match = request.url.match(/^\/(before|after)\/(.*)$/);
  if (!match || match[2].includes('..') || match[2].includes('?')) { response.writeHead(404).end(); return; }
  const [, side, asset] = match;
  const record = { side, asset: asset || 'index.html', method: request.method, start: performance.now() };
  requests.push(record);
  response.on('finish', () => { record.end = performance.now(); record.status = response.statusCode; });
  if (asset === 'api/update') {
    later(() => response.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify({ phase: 'unavailable', can_request: false, requested_at: null, next_allowed_at: null })), delay.request_ms);
    return;
  }
  try {
    const bytes = await fs.readFile(path.join(side === 'before' ? before : after, asset || 'index.html'));
    later(() => {
      response.writeHead(200, { 'Content-Type': types[path.extname(asset || 'index.html')] || 'text/plain', 'Cache-Control': 'no-store', ...(asset === 'dataset.json' ? { ETag: `"${inputHash}"` } : {}) });
      response.flushHeaders();
      if (asset === 'dataset.json') later(() => response.end(bytes), delay.extra_data_body_ms);
      else response.end(bytes);
    }, delay.request_ms);
  } catch { later(() => response.writeHead(404).end(), delay.request_ms); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const samples = [];
let browser, cleanup, failure;
try {
  browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? {} : { channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }), headless: true });
  for (let run = 0; run < 10; run++) {
    const side = run % 2 ? 'after' : 'before';
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [], failed = [], nonSuccess = [], external = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('requestfailed', request => failed.push({ url: request.url(), error: request.failure()?.errorText }));
    page.on('request', request => { if (!request.url().startsWith(origin) && !request.url().startsWith('data:')) external.push(request.url()); });
    page.on('response', response => { if (!response.ok()) nonSuccess.push({ url: response.url(), status: response.status() }); });
    await page.addInitScript(() => {
      const marks = { firstRouteStroke: null, frameAfterFirstRouteStroke: null, strokeCount: 0, firstFrameStrokeCount: null, readyAt: null, emptyMessages: [], longTasks: [] };
      window.__startupMeasurement = marks;
      const observe = () => {
        const empty = document.querySelector('#empty');
        if (empty && !empty.hidden && getComputedStyle(empty).display !== 'none' && !marks.emptyMessages.includes(empty.innerText)) marks.emptyMessages.push(empty.innerText);
        if (/\d+\s*次/.test(document.querySelector('#visible-stat')?.textContent || '')) marks.readyAt ??= performance.now();
      };
      new MutationObserver(observe).observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
      const stroke = CanvasRenderingContext2D.prototype.stroke;
      CanvasRenderingContext2D.prototype.stroke = function(...args) {
        const result = stroke.apply(this, args);
        if (this.canvas.classList.contains('route-canvas')) {
          marks.strokeCount++;
          if (marks.firstRouteStroke === null) {
            marks.firstRouteStroke = performance.now();
            requestAnimationFrame(() => { marks.frameAfterFirstRouteStroke = performance.now(); marks.firstFrameStrokeCount = marks.strokeCount; });
          }
        }
        return result;
      };
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) marks.longTasks.push({ start: entry.startTime, duration: entry.duration });
      }).observe({ type: 'longtask', buffered: true });
    });
    const startRequest = requests.length;
    const statusResponse = page.waitForResponse(response => response.url().endsWith('/api/update'));
    console.log(`Sample ${run + 1} ${side} navigation.`);
    await page.goto(`${origin}/${side}/`, { waitUntil: 'domcontentloaded' });
    console.log(`Sample ${run + 1} ${side} modules ready.`);
    await page.waitForFunction(() => window.__startupMeasurement.frameAfterFirstRouteStroke !== null);
    console.log(`Sample ${run + 1} ${side} route draw observed.`);
    await statusResponse;
    console.log(`Sample ${run + 1} ${side} status observed.`);
    const sample = await page.evaluate(() => ({ marks: window.__startupMeasurement, visible: document.querySelector('#visible-stat').textContent, history: document.querySelector('#history-stat').textContent, error: document.querySelector('#error').textContent, resources: performance.getEntriesByType('resource').map(entry => ({ path: new URL(entry.name).pathname, start: entry.startTime, headers: entry.responseStart, end: entry.responseEnd, transferBytes: entry.transferSize, decodedBytes: entry.decodedBodySize })), navigation: performance.getEntriesByType('navigation').map(entry => ({ headers: entry.responseStart, end: entry.responseEnd })), canvas: (() => { const canvas = document.querySelector('.route-canvas'); return { width: canvas.width, height: canvas.height, nonzeroPixel: canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data.some(value => value !== 0) }; })() }));
    const dataRequests = requests.slice(startRequest).filter(request => request.method === 'GET' && request.asset === 'dataset.json');
    assert.equal(dataRequests.length, 1);
    assert.equal(sample.resources.filter(resource => resource.path.endsWith('/dataset.json')).length, 1);
    assert.equal(sample.resources.find(resource => resource.path.endsWith('/dataset.json')).decodedBytes, expected.bytes);
    assert.match(sample.visible, new RegExp(`${expected.visible} 次`));
    assert.match(sample.history, new RegExp(`${expected.history} 次`));
    assert.ok(sample.marks.firstFrameStrokeCount >= expected.tracks * 3, 'Each real route renders its casing, color and overlap strokes.');
    assert.equal(sample.canvas.nonzeroPixel, true); assert.equal(sample.error, '');
    assert.deepEqual(errors, []); assert.deepEqual(failed, []); assert.deepEqual(external, []);
    assert.deepEqual(nonSuccess, []);
    const timed = sample.resources.find(resource => resource.path.endsWith('/dataset.json'));
    samples.push({ run: run + 1, side, ...sample, datasetRequest: dataRequests[0], errors, failed, nonSuccess, external, datasetStart: timed.start, datasetEnd: timed.end, postDataToFrame: sample.marks.frameAfterFirstRouteStroke - timed.end });
    await fs.writeFile(path.join(output, 'comparison-progress.json'), JSON.stringify({ samples, requests }, null, 2));
    if (run < 2) await page.screenshot({ path: path.join(output, `${side}.png`) });
    console.log(`Sample ${run + 1} ${side} verified.`);
    await context.close();
  }
} catch (error) { failure = error.stack; }
finally {
  await browser?.close();
  for (const timer of timers) clearTimeout(timer);
  await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
  let socketClosed = false;
  try { await fetch(origin); } catch { socketClosed = true; }
  cleanup = { serverClosed: !server.listening, socketClosed };
  await fs.writeFile(path.join(output, 'comparison-samples.json'), JSON.stringify({ claim, expected, delay, samples, requests, failure, cleanup }, null, 2) + '\n');
}
if (failure) throw new Error(failure);
const summary = values => {
  const sorted = values.toSorted((a, b) => a - b);
  return { median_ms: sorted[Math.floor(sorted.length / 2)], range_ms: [sorted[0], sorted.at(-1)], count: sorted.length };
};
const sides = Object.fromEntries(['before', 'after'].map(side => {
  const selected = samples.filter(sample => sample.side === side);
  return [side, { draw: summary(selected.map(sample => sample.marks.frameAfterFirstRouteStroke)), datasetStart: summary(selected.map(sample => sample.datasetStart)), postDataToFrame: summary(selected.map(sample => sample.postDataToFrame)), falseMissingMessageCount: selected.filter(sample => sample.marks.emptyMessages.some(text => text.includes('尚未发布'))).length }];
}));
const report = { claim, source: 'alternating-local-exports-fresh-contexts-without-request-interception', before, after, expected, delay, machine: { load, cores, browser: browser.version(), node: process.version }, measurement: 'frameAfterFirstRouteStroke measures the next animation frame after the complete route draw containing the first stroke', updateStatus: 'Both sides receive the same valid unavailable status response from the local test server. No update is dispatched.', limiter: 'The baseline discovers app dependencies serially before requesting data. Each discovered request adds the fixed 120 ms delay. The after export overlaps data transfer with module loading. Both keep the same data body delay and route model.', sides, delta_ms: sides.before.draw.median_ms - sides.after.draw.median_ms, samples, cleanup };
await fs.writeFile(path.join(output, 'comparison.json'), JSON.stringify(report, null, 2) + '\n');
assert.deepEqual(cleanup, { serverClosed: true, socketClosed: true });
console.log(JSON.stringify({ sides, delta_ms: report.delta_ms, errors: samples.flatMap(sample => sample.errors), evidence: path.join(output, 'comparison.json') }));
