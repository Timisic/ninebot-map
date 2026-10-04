import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { makeDataset } from '../tests/map-fixture.mjs';

const root = process.cwd();
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
let browser;
try {
  const url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error('Map did not start')), 10000);
    server.on('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}`)); });
    server.stdout.on('data', chunk => {
      output += chunk;
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
  });
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
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
  await page.locator('#date-panel > summary').click();
  await page.locator('#from').fill('2026-01-10');
  await page.locator('#from').dispatchEvent('change');
  await page.locator('#to').fill('2026-01-10');
  await page.locator('#to').dispatchEvent('change');
  await page.locator('#date-panel > summary').click();
  await page.locator('#map-options > summary').click();
  await page.locator('#crs').selectOption('gcj02');
  await page.waitForFunction(() => document.querySelector('#crs-note').textContent.includes('GCJ02'));
  await page.locator('#map-options > summary').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  await page.locator('#place-label').fill('Synthetic saved label');
  await page.locator('#label-form button[type=submit]').click();
  const view = await page.locator('.leaflet-map-pane').getAttribute('style');
  await replace(fresh);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(() => document.querySelector('#history-stat').textContent.includes('2 次'));
  assert.match(await page.locator('#visible-stat').textContent(), /1 次/);
  assert.equal(await page.locator('#from').inputValue(), '2026-01-10');
  assert.equal(await page.locator('#to').inputValue(), '2026-01-10');
  assert.equal(await page.locator('#crs').inputValue(), 'gcj02');
  assert.equal(await page.locator('.place-name').first().textContent(), 'Synthetic saved label');
  assert.equal(await page.locator('.leaflet-map-pane').getAttribute('style'), view);
  await replace({ invalid: true });
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  assert.match(await page.locator('#history-stat').textContent(), /2 次/);
  await page.locator('#file').setInputFiles({ name: 'manual.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(old)) });
  await page.waitForFunction(() => document.querySelector('#history-stat').textContent.includes('1 次'));
  await replace(fresh);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  assert.match(await page.locator('#history-stat').textContent(), /1 次/);
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
  console.log('Synthetic browser refresh passed: live update, date/CRS/labels/view retained, invalid update retained, manual import retained, zero external requests.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
  await fs.rm(directory, { recursive: true, force: true });
}
