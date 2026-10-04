import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs/promises';
import net from 'node:net';
import { chromium } from 'playwright';
import { makeDataset } from '../tests/map-fixture.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const fixture = fileURLToPath(new URL('../tests/fixtures/synthetic-map.json', import.meta.url));
const server = spawn('./run', ['map', '--dataset', fixture, '--port', '0', '--no-open'], { cwd: root });
let browser, url;
try {
  url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error('Local map did not start')), 10000);
    server.on('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}`)); });
    server.stderr.on('data', chunk => { output += chunk; });
    server.stdout.on('data', chunk => { output += chunk; const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//); if (match) { clearTimeout(timer); resolve(match[0]); } });
  });
  browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? {} : { channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }), headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce' });
  const external = [], errors = [];
  await context.route('**/*', route => { if (!route.request().url().startsWith(url) && !route.request().url().startsWith('data:')) { external.push(route.request().url()); route.abort(); } else route.continue(); });
  const page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await page.locator('#places li').count(), 4);
  assert.equal(await page.locator('#places-panel').isVisible(), false);
  assert.deepEqual(await page.locator('.place-count').allTextContents(), ['6次', '3次', '2次', '1次']);
  await page.locator('#map').evaluate(element => { window.originalMapElement = element; });
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal((await page.locator('#map-options > summary').textContent()).trim(), '设置');
  await page.locator('#map-options > summary').click();
  assert.equal(await page.locator('#data-notes').getAttribute('open'), null);
  assert.equal(await page.locator('#crs-note').isVisible(), false);
  assert.equal(await page.locator('#basemap-gate').isVisible(), true);
  await page.locator('#map-options > summary').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  await page.locator('#place-label').fill('尚未保存的名称');
  const viewBeforeTheme = await page.locator('.leaflet-map-pane').getAttribute('style');
  await page.locator('#theme-toggle').click();
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  assert.equal(await page.locator('#place-label').inputValue(), '尚未保存的名称');
  assert.equal(await page.locator('.leaflet-map-pane').getAttribute('style'), viewBeforeTheme);
  await page.reload(); await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.locator('#file').setInputFiles(fixture); await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.locator('#theme-toggle').click();
  await page.locator('#map').evaluate(element => { window.originalMapElement = element; });
  await page.locator('#date-panel > summary').click();
  await page.locator('#from').fill('2026-01-10'); await page.locator('#from').dispatchEvent('change');
  assert.match(await page.locator('#visible-stat').textContent(), /3 次/);
  assert.match(await page.locator('#history-stat').textContent(), /12 次/);
  assert.equal(await page.locator('#map').evaluate(element => element === window.originalMapElement), true);
  assert.deepEqual(await page.locator('.place-count').allTextContents(), ['2次', '1次']);
  await page.locator('#clear-dates').click();
  await page.locator('#date-panel > summary').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  await page.locator('#place-label').fill('合成终点 A'); await page.locator('#label-form button[type=submit]').click();
  assert.equal(await page.locator('.place-name').first().textContent(), '合成终点 A');
  await page.reload(); await page.waitForFunction(() => document.querySelector('.place-name')?.textContent === '合成终点 A');
  await page.locator('#file').setInputFiles({ name: 'broken.json', mimeType: 'application/json', buffer: Buffer.from('{broken') });
  await page.waitForFunction(() => !document.querySelector('#error').hidden);
  assert.match(await page.locator('#error').textContent(), /保留上一份/);
  assert.match(await page.locator('#visible-stat').textContent(), /12 次/);
  await page.locator('#show-grid').check();
  const mapBox = await page.locator('#map').boundingBox(); await page.mouse.move(mapBox.x + 500, mapBox.y + 400);
  await page.waitForFunction(() => !document.querySelector('#cell-info').hidden);
  assert.match(await page.locator('#cell-info').textContent(), /次行程经过这个区域/);
  await page.locator('#map-options > summary').click(); assert.equal(await page.locator('#basemap').isDisabled(), true);
  await page.locator('#crs').selectOption('wgs84'); await page.waitForFunction(() => document.querySelector('#crs-note').textContent.includes('原始坐标') && !document.querySelector('#basemap').disabled);
  await page.locator('#crs').selectOption('gcj02'); await page.waitForFunction(() => document.querySelector('#crs-note').textContent.includes('GCJ02') && !document.querySelector('#basemap').disabled);
  assert.match(await page.locator('#crs-note').textContent(), /校准|转为/);
  await page.locator('#crs').selectOption('unverified'); await page.waitForFunction(() => document.querySelector('#basemap').disabled);
  await page.locator('#map-options > summary').click();
  await page.locator('#show-grid').uncheck();
  const single = makeDataset([{ id: 'line', xy: [[0, 0], [500, 0], [900, 300]] }]);
  const repeated = makeDataset(Array.from({ length: 6 }, (_, index) => ({ id: `line-${index}`, xy: [[0, 0], [500, 0], [900, 300]] })));
  async function renderEnergy(data, count, online = false) {
    await page.locator('#file').setInputFiles({ name: 'synthetic.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(data)) });
    await page.waitForFunction(count => document.querySelector('#visible-stat').textContent.includes(`${count} 次`), count);
    if (online) {
      await page.locator('#crs').selectOption('wgs84');
      await page.waitForFunction(() => !document.querySelector('#basemap').disabled);
      await page.locator('#basemap').check();
    }
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    return page.locator('.route-canvas').evaluate(canvas => { const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data; let energy = 0; for (let i = 0; i < pixels.length; i += 4) energy += (pixels[i] + pixels[i + 1] + pixels[i + 2]) * pixels[i + 3] / 255; return energy; });
  }
  const one = await renderEnergy(single, 1), six = await renderEnergy(repeated, 6);
  assert.ok(six > one * 2, `Repeated independent routes must brighten. One=${one}, six=${six}`);
  await page.locator('#file').setInputFiles(fixture); await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  const contrast = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1; const ctx = canvas.getContext('2d');
    const color = token => { ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(token); ctx.fillRect(0, 0, 1, 1); return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); };
    const luminance = rgb => rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    const ratio = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    return { secondary: ratio(luminance(color('--secondary')), luminance(color('--panel'))), primary: ratio(luminance(color('--on-primary')), luminance(color('--primary'))) };
  });
  assert.ok(contrast.secondary >= 4.5, JSON.stringify(contrast)); assert.ok(contrast.primary >= 4.5, JSON.stringify(contrast));
  await page.locator('#theme-toggle').click();
  const lightContrast = await page.evaluate(() => {
    const linear = value => { value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4; };
    const lum = token => { const hex = getComputedStyle(document.documentElement).getPropertyValue(token).trim(); const values = hex.match(/[a-f0-9]{2}/gi).map(value => linear(parseInt(value, 16))); return values[0]*.2126+values[1]*.7152+values[2]*.0722; };
    const a=lum('--secondary'),b=lum('--panel'); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });
  assert.ok(lightContrast >= 4.5);
  await page.locator('#theme-toggle').click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(url + '#title=' + encodeURIComponent('北京骑行地图'));
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole('heading', { name: '北京骑行地图', exact: true }).waitFor();
    const header = await page.locator('.topbar').evaluate(element => {
      const title = element.querySelector('h1'), titleStyle = getComputedStyle(title);
      return { height: element.getBoundingClientRect().height, titleHeight: title.getBoundingClientRect().height, lineHeight: parseFloat(titleStyle.lineHeight), nowrap: titleStyle.whiteSpace, actions: [...element.querySelectorAll('.actions button')].map(button => ({ width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height })) };
    });
    assert.equal(header.height, 52, JSON.stringify({ width, header }));
    assert.equal(header.nowrap, 'nowrap');
    assert.ok(header.titleHeight <= header.lineHeight + 1, JSON.stringify({ width, header }));
    assert.ok(header.actions.every(button => button.width >= 44 && button.height >= 44));
    assert.equal(await page.locator('#local-status').isVisible(), false);
    await page.locator('#date-panel > summary').click();
    const dates = await page.locator('.date-controls').boundingBox();
    assert.ok(dates.x >= 0 && dates.x + dates.width <= width, JSON.stringify({ width, dates }));
    await page.locator('#date-panel > summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  if (await page.locator('#places-panel').isVisible()) await page.locator('#toggle-places').click();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.locator('#toggle-places').click(); assert.equal(await page.locator('#places-panel').isVisible(), true);
  await page.locator('.place-button').first().click();
  assert.equal(await page.locator('#label-form').isVisible(), true);
  if (process.env.MAP_SCREENSHOTS) { await fs.mkdir(process.env.MAP_SCREENSHOTS, { recursive: true }); await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-mobile.png` }); }
  assert.deepEqual(external, []); assert.deepEqual(errors, []);
  await page.setViewportSize({ width: 1440, height: 960 });
  await context.route('https://tile.openstreetmap.org/**', route => route.fulfill({ status: 200, contentType: 'image/png', headers: {'access-control-allow-origin':'*'}, body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGMsAAAAASUVORK5CYII=', 'base64') }));
  await page.locator('#map-options > summary').click();
  await page.locator('#crs').selectOption('wgs84'); await page.waitForFunction(() => document.querySelector('#crs-note').textContent.includes('原始坐标') && !document.querySelector('#basemap').disabled);
  await page.locator('#basemap').check();
  await page.waitForFunction(() => document.querySelectorAll('img.leaflet-tile').length > 0);
  await page.locator('#crs').selectOption('gcj02');
  await page.waitForFunction(() => document.querySelector('#crs-note').textContent.includes('GCJ02') && document.querySelector('#basemap').checked && document.querySelectorAll('img.leaflet-tile').length > 0);
  await page.locator('#basemap').uncheck();
  await page.locator('#theme-toggle').click();
  const lightOne = await renderEnergy(single, 1, true), lightSix = await renderEnergy(repeated, 6, true);
  assert.ok(lightSix > lightOne * 1.2, `Light basemap repeats must brighten. One=${lightOne}, six=${lightSix}`);
  await page.locator('#file').setInputFiles(fixture);
  await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  assert.deepEqual(errors, []);
  assert.equal(await page.locator('#error').isVisible(), false);
  const labelSize = await page.locator('.place-name').first().evaluate(e => parseFloat(getComputedStyle(e).fontSize));
  assert.ok(labelSize >= 14 && labelSize <= 15);
  assert.equal((await page.locator('.destination-marker button').first().textContent()).trim(), '');
  const marker = await page.locator('.destination-marker button').first().evaluate(e => ({hit:e.getBoundingClientRect().width, glyph:e.querySelector('svg').getBoundingClientRect().width}));
  assert.ok(marker.hit >= 40 && marker.glyph <= 19);
  await page.locator('#toggle-places').click();
  await page.locator('.destination-marker button').first().focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#places-panel').isVisible(), true);
  const panelBox = await page.locator('#places-panel').boundingBox();
  assert.equal(panelBox.width, 256);
  assert.ok(panelBox.height <= 960 / 2);


  for (const dpr of [1, 2]) {
    const retinaContext = await browser.newContext({ viewport: {width: 1200, height: 800}, deviceScaleFactor: dpr });
    await retinaContext.route('https://tile.openstreetmap.org/**', route => route.fulfill({status:200, contentType:'image/png', headers: {'access-control-allow-origin':'*'}, body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGMsAAAAASUVORK5CYII=', 'base64')}));
    const retinaPage = await retinaContext.newPage(); retinaPage.setDefaultTimeout(15000);
    await retinaPage.goto(url + '#crs=wgs84&basemap=osm');
    await retinaPage.waitForFunction(() => document.querySelector('img.leaflet-tile-loaded'));
    const scaling = await retinaPage.locator('img.leaflet-tile-loaded').first().evaluate(e => ({width:e.getBoundingClientRect().width, filter:getComputedStyle(e.closest(".basemap-tiles")).filter}));
    assert.equal(scaling.width, dpr === 1 ? 256 : 128, JSON.stringify({dpr, ...scaling}));
    assert.equal(scaling.filter, 'invert(1) hue-rotate(180deg)');
    const tileCount = await retinaPage.locator('img.leaflet-tile').count();
    await retinaPage.locator('#theme-toggle').click();
    assert.equal(await retinaPage.locator('img.leaflet-tile').count(), tileCount);
    assert.equal(await retinaPage.locator('.basemap-tiles').evaluate(e => getComputedStyle(e).filter), 'none');
    for (let step = 0; step < 20; step++) {
      if (await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled') === 'true') break;
      await retinaPage.locator('.leaflet-control-zoom-in').click();
    }
    assert.equal(await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled'), 'true');
    const tileZooms = await retinaPage.locator('img.leaflet-tile').evaluateAll(images => images.map(image => Number(new URL(image.src).pathname.split('/')[1])));
    assert.ok(tileZooms.length > 0 && tileZooms.every(zoom => zoom <= 19));
    if (dpr === 2) {
      await retinaPage.locator('#map-options > summary').click();
      await retinaPage.locator('#basemap').uncheck();
      assert.equal(await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled'), 'false');
      await retinaPage.locator('.leaflet-control-zoom-in').click();
      assert.equal(await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled'), 'true');
    }
    await retinaContext.close();
  }

  const blocked = await browser.newContext();
  await blocked.addInitScript(() => { Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('blocked', 'SecurityError');}}); });
  const blockedPage = await blocked.newPage();
  await blockedPage.goto(url); await blockedPage.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await blockedPage.locator('html').getAttribute('data-theme'), 'dark');
  await blockedPage.locator('#theme-toggle').click();
  assert.equal(await blockedPage.locator('html').getAttribute('data-theme'), 'light');
  await blocked.close();
  console.log(JSON.stringify({ passed: true, checks: ['default-dark', 'theme-persistence-import', 'theme-preserves-view-and-unsaved-label', 'blocked-storage-toggle', 'short-settings-disclosure', 'both-theme-contrast', 'desktop', 'mobile', 'mobile-chinese-hash-title-390-320', 'mobile-date-popover-bounds-390-320', 'counts', 'filter', 'labels-persist', 'malformed-preserves', 'area-hover', 'crs-gating', 'additive-pixels', 'contrast', 'no-external-network', 'no-page-errors', 'online-layer-cleanup', 'coordinate-preview', 'quiet-label-scale', 'tiny-svg-markers', 'marker-opens-panel', 'integer-tile-scaling-dpr1-dpr2', 'online-additive-pixels', 'keyboard-marker-selection'], contrast, overlapBrightnessRatio: +(six / one).toFixed(2) }, null, 2));
} finally {
  try { await browser?.close(); } finally {
    if (server.exitCode === null && server.signalCode === null) await new Promise(resolve => {
      server.once('exit', resolve); server.kill('SIGINT');
      const timer = setTimeout(() => server.kill('SIGKILL'), 5000);
      server.once('exit', () => clearTimeout(timer));
    });
    if (url) {
      const socketClosed = await new Promise(resolve => {
        const socket = net.connect({ host: '127.0.0.1', port: Number(new URL(url).port) });
        socket.once('connect', () => { socket.destroy(); resolve(false); });
        socket.once('error', () => resolve(true));
        socket.setTimeout(1000, () => { socket.destroy(); resolve(false); });
      });
      assert.equal(socketClosed, true, 'Owned map socket must close after cleanup');
    }
  }
}
