import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { chromium } from 'playwright';
import { makeDataset } from '../tests/map-fixture.mjs';
async function selectTheme(page, preference) {
  await page.locator('#theme-toggle').click();
  await page.locator(`button[data-theme-preference=${preference}]`).click();
}
async function toggleTheme(page) { await selectTheme(page, await page.locator('html').getAttribute('data-theme') === 'dark' ? 'light' : 'dark'); }
async function themeGeometry(page, width) {
  await page.setViewportSize({ width, height: 960 });
  const measurements = [];
  for (const preference of ['system', 'light', 'dark']) {
    await selectTheme(page, preference);
    await page.locator('#theme-toggle').click();
    const measurement = await page.locator('#theme-options').evaluate(element => {
      const toggle = element.querySelector('summary'), icon = toggle.querySelector('svg');
      const box = toggle.getBoundingClientRect(), glyph = icon.getBoundingClientRect(), panel = element.querySelector('.theme-menu').getBoundingClientRect();
      const selected = element.querySelector('[aria-pressed=true]').getBoundingClientRect();
      return { preference: document.documentElement.dataset.themePreference, dx: glyph.x + glyph.width / 2 - box.x - box.width / 2, dy: glyph.y + glyph.height / 2 - box.y - box.height / 2, hit: { width: box.width, height: box.height }, selectedInset: { left: selected.left - panel.left, right: panel.right - selected.right }, rowsFit: [...element.querySelectorAll('button')].every(button => { const row = button.getBoundingClientRect(); return row.left >= panel.left && row.right <= panel.right && row.top >= panel.top && row.bottom <= panel.bottom && row.height >= 44; }), hitCentered: toggle.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)), pageFits: document.documentElement.scrollWidth <= innerWidth };
    });
    assert.ok(Math.abs(measurement.dx) < .1 && Math.abs(measurement.dy) < .1, JSON.stringify({ width, ...measurement }));
    assert.deepEqual(measurement.hit, { width: 44, height: 44 });
    assert.deepEqual(measurement.selectedInset, { left: 6, right: 6 });
    assert.equal(measurement.rowsFit && measurement.hitCentered && measurement.pageFits, true);
    measurements.push({ width, ...measurement });
    await page.locator('#theme-toggle').click();
  }
  return measurements;
}
const root = fileURLToPath(new URL('../', import.meta.url));
const fixture = fileURLToPath(new URL('../tests/fixtures/synthetic-map.json', import.meta.url));
await fs.mkdir(path.join(root, 'work'), { recursive: true });
const scratch = await fs.mkdtemp(path.join(root, 'work/map-view-'));
const datasetPath = path.join(scratch, 'dataset.json');
await fs.copyFile(fixture, datasetPath);
const server = spawn('./run', ['map', '--dataset', datasetPath, '--port', '0', '--no-open'], { cwd: root });
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
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce', colorScheme: 'dark' });
  const external = [], errors = [], fonts = [];
  await context.route('**/*', route => { if (!route.request().url().startsWith(url) && !route.request().url().startsWith('data:')) { external.push(route.request().url()); route.abort(); } else route.continue(); });
  const page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.url().endsWith('.woff2')) fonts.push({ url: response.url(), status: response.status(), type: response.headers()['content-type'] }); });
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  const font = await page.evaluate(async () => {
    await document.fonts.load('400 14px "Smiley Sans"'); await document.fonts.ready;
    return { loaded: [...document.fonts].some(face => face.family.includes('Smiley Sans') && face.status === 'loaded'), family: getComputedStyle(document.documentElement).fontFamily, synthesis: getComputedStyle(document.documentElement).fontSynthesis, samples: ['#running', '.metrics', '.leaflet-container', '#place-label'].map(selector => getComputedStyle(document.querySelector(selector)).fontFamily) };
  });
  assert.equal(font.loaded, true, JSON.stringify(font));
  assert.match(await page.locator('#nature-total').getAttribute('aria-label'), /停车停留推算/);
  const toolbarGeometry = [];
  for (const width of [1440, 390, 320, 640, 844]) {
    await page.setViewportSize({ width, height: width === 640 ? 360 : 960 });
    const result = await page.evaluate(() => {
      const ids = ['update-map', 'nature-total', 'badminton-stat'];
      const boxes = ids.map(id => { const b = document.getElementById(id).getBoundingClientRect(); return { id, left: b.left, right: b.right, top: b.top, bottom: b.bottom }; });
      return { boxes, fits: boxes.every(b => b.left >= 0 && b.right <= innerWidth && b.bottom <= innerHeight), ordered: boxes[0].bottom <= boxes[1].top && boxes[1].bottom <= boxes[2].top, noOverflow: document.documentElement.scrollWidth <= innerWidth };
    });
    assert.ok(result.fits && result.ordered && result.noOverflow, JSON.stringify({ width, ...result }));
    toolbarGeometry.push({ width, ...result });
  }
  await page.setViewportSize({ width: 1440, height: 960 });
  if (process.env.VERIFICATION_OUTPUT) await fs.writeFile(path.join(process.env.VERIFICATION_OUTPUT, 'nature-toolbar.json'), JSON.stringify(toolbarGeometry, null, 2));
  assert.equal(font.synthesis, 'none');
  assert.ok(font.samples.every(family => family.startsWith('"Smiley Sans"')));
  assert.ok(fonts.some(response => response.status === 200 && response.type === 'font/woff2' && /\/assets\/[a-f0-9]{64}\/fonts\/smiley-sans\//.test(response.url)), JSON.stringify(fonts));
  const themeMeasurements = [];
  for (const width of [1440, 390, 320]) themeMeasurements.push(...await themeGeometry(page, width));
  await page.setViewportSize({ width: 1440, height: 960 }); await selectTheme(page, 'system');
  for (const selector of ['.leaflet-control-zoom-in', '.leaflet-control-zoom-out', '#fit', '#update-map']) {
    const control = await page.locator(selector).evaluate(element => ({ size: element.getBoundingClientRect().height, icon: !!element.querySelector('svg'), rounded: element.querySelector('svg')?.getAttribute('stroke-linecap') }));
    assert.ok(control.size >= 44 && control.icon && control.rounded === 'round', JSON.stringify({ selector, control }));
  }
  assert.equal(await page.locator('#places li').count(), 4);
  assert.equal(await page.locator('#places-panel').isVisible(), false);
  assert.deepEqual(await page.locator('.place-count').allTextContents(), ['6次', '3次', '2次', '1次']);
  await page.locator('#map').evaluate(element => { window.originalMapElement = element; });
  assert.equal(await page.title(), 'Along');
  assert.equal(await page.locator('#date-panel, #from, #to, #page-title').count(), 0);
  assert.equal(await page.locator('.route-legend').evaluate(element => getComputedStyle(element).fontSize), '11px');
  assert.equal(await page.locator('.metrics').evaluate(element => getComputedStyle(element).fontSize), '11px');
  assert.equal(await page.locator('html').getAttribute('data-theme-preference'), 'system');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  await page.locator('#running').click();
  assert.equal(await page.locator('#inline-hint').textContent(), '正在running中...');
  await page.keyboard.press('Escape');
  assert.equal((await page.locator('#map-options > summary').textContent()).trim(), '图层');
  await page.locator('#map-options > summary').click();
  assert.equal(await page.locator('#crs, #crs-note, #data-notes').count(), 0);
  assert.equal(await page.locator('.settings-content input[type=checkbox]').count(), 2);
  assert.equal(await page.locator('#basemap').isEnabled(), true);
  assert.equal(await page.locator('#basemap').isChecked(), false);
  await page.locator('#map-options > summary').click();
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  const cueId = await page.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id');
  const cueSelector = `.destination-marker.is-cued button[data-place-id="${cueId}"]`;
  assert.equal(await page.locator(cueSelector).count(), 1);
  assert.equal(await page.locator(cueSelector + ' .place-cue-name').textContent(), '地点 1');
  const cueName = await page.locator(cueSelector + ' .place-cue-name').evaluate(element => ({ width: element.getBoundingClientRect().width, pointer: getComputedStyle(element).pointerEvents, hidden: element.getAttribute('aria-hidden') }));
  assert.ok(cueName.width <= 180 && cueName.pointer === 'none' && cueName.hidden === 'true', JSON.stringify(cueName));
  const initialCueDeadline = Number(await page.locator(cueSelector).getAttribute('data-cue-expires-at'));
  const cueView = await page.locator('.leaflet-map-pane').getAttribute('style');
  await page.locator('#edit-place').click(); await page.locator('#place-label').fill('尚未保存的名称');
  assert.equal(Number(await page.locator(cueSelector).getAttribute('data-cue-expires-at')), initialCueDeadline, 'Editing must preserve the cue deadline.');
  assert.equal(await page.locator(cueSelector).evaluate(element => getComputedStyle(element, '::after').animationName), 'none', 'Reduced motion keeps a static cue.');
  await page.waitForTimeout(350);
  await page.locator('.place-button').first().click();
  const renewedCueDeadline = Number(await page.locator(cueSelector).getAttribute('data-cue-expires-at'));
  assert.ok(renewedCueDeadline > initialCueDeadline + 300);
  assert.equal(await page.locator('#place-label').inputValue(), '尚未保存的名称');
  assert.equal(await page.locator('#label-form').isVisible(), true);
  const selectedPin = await page.locator('.destination-marker button[aria-pressed=true]').evaluate(element => ({ disk: getComputedStyle(element, '::before').backgroundColor, pin: getComputedStyle(element.querySelector('svg')).color }));
  await page.waitForFunction(() => !document.querySelector('.destination-marker.is-cued'), null, { timeout: 3500 });
  const expiredAt = await page.evaluate(() => performance.now());
  assert.ok(expiredAt >= renewedCueDeadline && expiredAt < renewedCueDeadline + 600, JSON.stringify({ renewedCueDeadline, expiredAt }));
  assert.equal(await page.locator('.destination-marker button').count(), 0, 'Unnamed places lose their temporary pin when the cue expires.');
  assert.equal(await page.locator('.leaflet-map-pane').getAttribute('style'), cueView);
  assert.deepEqual(selectedPin, { disk: 'rgb(234, 245, 239)', pin: 'rgb(23, 75, 78)' });
  const viewBeforeTheme = await page.locator('.leaflet-map-pane').getAttribute('style');
  await toggleTheme(page);
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.emulateMedia({ colorScheme: 'dark' });
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  assert.equal(await page.locator('#place-label').inputValue(), '尚未保存的名称');
  assert.equal(await page.locator('.leaflet-map-pane').getAttribute('style'), viewBeforeTheme);
  assert.equal(await page.locator('.destination-marker button').count(), 0);
  await selectTheme(page, 'system');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await selectTheme(page, 'light');
  await page.reload(); await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await fs.copyFile(fixture, datasetPath); await page.reload(); await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await toggleTheme(page);
  await page.locator('#map').evaluate(element => { window.originalMapElement = element; });
  assert.equal(await page.locator('#map').evaluate(element => element === window.originalMapElement), true);
  await page.locator('#toggle-places').click();
  await page.locator('.place-button').first().click();
  await page.locator('#edit-place').click(); await page.locator('#place-label').fill('合成终点 A'); await page.locator('#label-form button[type=submit]').click();
  assert.equal(await page.locator('.place-name').first().textContent(), '合成终点 A');
  await page.reload(); await page.waitForFunction(() => document.querySelector('.place-name')?.textContent === '合成终点 A');
  await fs.writeFile(datasetPath, '{broken');
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  assert.equal(await page.locator('input[type=file], #import-button').count(), 0);
  assert.match(await page.locator('#visible-stat').textContent(), /12 次/);
  await page.locator('#map-options > summary').click();
  await page.locator('#show-grid').check();
  await page.locator('#map-options > summary').click();
  const mapBox = await page.locator('#map').boundingBox(); await page.mouse.move(mapBox.x + 500, mapBox.y + 400);
  await page.waitForFunction(() => !document.querySelector('#cell-info').hidden);
  assert.match(await page.locator('#cell-info').textContent(), /次行程经过这个区域/);
  await page.mouse.move(mapBox.x + 700, mapBox.y + 400);
  await page.mouse.down(); await page.mouse.move(mapBox.x + 750, mapBox.y + 430, { steps: 6 }); await page.mouse.up();
  await page.waitForTimeout(350);
  const rawMarkerBeforePreview = await page.locator('.destination-marker').first().boundingBox();
  await context.route('https://tile.openstreetmap.org/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGMsAAAAASUVORK5CYII=', 'base64') }));
  await page.locator('#map-options > summary').click();
  await page.locator('#basemap').check();
  await page.locator('img.leaflet-tile-loaded').first().waitFor();
  assert.deepEqual(await page.locator('.destination-marker').first().boundingBox(), rawMarkerBeforePreview);
  await page.locator('#basemap').uncheck();
  assert.equal(await page.locator('img.leaflet-tile').count(), 0);
  assert.deepEqual(await page.locator('.destination-marker').first().boundingBox(), rawMarkerBeforePreview);
  await page.locator('#show-grid').uncheck();
  await page.locator('#map-options > summary').click();
  const single = makeDataset([{ id: 'line', xy: [[0, 0], [500, 0], [900, 300]] }]);
  const repeated = makeDataset(Array.from({ length: 6 }, (_, index) => ({ id: `line-${index}`, xy: [[0, 0], [500, 0], [900, 300]] })));
  async function renderEnergy(data, count, online = false) {
    await fs.writeFile(datasetPath, JSON.stringify(data)); await page.reload();
    await page.waitForFunction(count => document.querySelector('#visible-stat').textContent.includes(`${count} 次`), count);
    if (online) {
      await page.locator('#map-options > summary').click();
      await page.waitForFunction(() => !document.querySelector('#basemap').disabled);
      await page.locator('#basemap').check();
    }
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    return page.locator('.route-canvas').evaluate(canvas => {
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      let energy = 0, darkestCore = Infinity;
      for (let i = 0; i < pixels.length; i += 4) {
        energy += (pixels[i] + pixels[i + 1] + pixels[i + 2]) * pixels[i + 3] / 255;
        if (pixels[i + 3] > 250 && pixels[i + 1] > pixels[i] + 10 && pixels[i + 2] > pixels[i] + 10) {
          const channels = [pixels[i], pixels[i + 1], pixels[i + 2]].map(value => { value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4; });
          darkestCore = Math.min(darkestCore, channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722);
        }
      }
      return { energy, darkestCore };
    });
  }
  const one = (await renderEnergy(single, 1)).energy, six = (await renderEnergy(repeated, 6)).energy;
  assert.ok(six > one * 1.15, `Repeated independent routes must brighten. One=${one}, six=${six}`);
  await fs.copyFile(fixture, datasetPath); await page.reload(); await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  const contrast = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1; const ctx = canvas.getContext('2d');
    const color = token => { ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(token); ctx.fillRect(0, 0, 1, 1); return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); };
    const luminance = rgb => rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    const ratio = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    return { secondary: ratio(luminance(color('--secondary')), luminance(color('--panel'))), primary: ratio(luminance(color('--on-primary')), luminance(color('--primary'))) };
  });
  assert.ok(contrast.secondary >= 4.5, JSON.stringify(contrast)); assert.ok(contrast.primary >= 4.5, JSON.stringify(contrast));
  await toggleTheme(page);
  const lightContrast = await page.evaluate(() => {
    const linear = value => { value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4; };
    const lum = token => { const hex = getComputedStyle(document.documentElement).getPropertyValue(token).trim(); const values = hex.match(/[a-f0-9]{2}/gi).map(value => linear(parseInt(value, 16))); return values[0]*.2126+values[1]*.7152+values[2]*.0722; };
    const a=lum('--secondary'),b=lum('--panel'); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });
  assert.ok(lightContrast >= 4.5);
  await toggleTheme(page);
  if (process.env.MAP_SCREENSHOTS) {
    await fs.mkdir(process.env.MAP_SCREENSHOTS, { recursive: true });
    await page.locator('#toggle-places').click();
    await page.locator('.place-button').first().click();
    await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-desktop-dark.png` });
    await toggleTheme(page);
    await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-desktop-light.png` });
    await toggleTheme(page);
    await page.locator('#theme-toggle').click();
    await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-theme-dark.png` });
    await page.locator('#theme-toggle').click();
    await page.locator('#toggle-places').click();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(url);
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.locator('.activity-nav').textContent(), 'Riding｜Running');
    const header = await page.locator('.topbar').evaluate(element => {
      const title = element.querySelector('.activity-nav [aria-current]'), titleStyle = getComputedStyle(title);
      return { height: element.getBoundingClientRect().height, titleHeight: title.getBoundingClientRect().height, lineHeight: parseFloat(titleStyle.lineHeight), nowrap: titleStyle.whiteSpace, actions: [...element.querySelectorAll('#theme-toggle, #toggle-places')].map(button => ({ width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height })) };
    });
    assert.equal(header.height, 56, JSON.stringify({ width, header }));
    assert.equal(header.nowrap, 'nowrap');
    assert.ok(header.titleHeight <= header.lineHeight + 1, JSON.stringify({ width, header }));
    assert.ok(header.actions.every(button => button.width >= 44 && button.height >= 44));
    assert.equal(await page.locator('#local-status').evaluate(element => element.getBoundingClientRect().width), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#map-options > summary').click();
    const settings = await page.locator('.settings-content').boundingBox();
    assert.ok(settings.x >= 0 && settings.x + settings.width <= width);
    assert.equal(await page.locator('.settings-content input[type=checkbox]').count(), 2);
    assert.equal(await page.locator('.settings-content').evaluate(element => { const r = element.getBoundingClientRect(); return element.contains(document.elementFromPoint(r.right - 24, r.bottom - 24)); }), true);
    if (process.env.MAP_SCREENSHOTS) await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-settings-${width}.png` });
    await page.locator('#map-options > summary').click();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  if (await page.locator('#places-panel').isVisible()) await page.locator('#toggle-places').click();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.locator('#toggle-places').click(); assert.equal(await page.locator('#places-panel').isVisible(), true);
  await page.locator('.place-button').first().click();
  assert.equal(await page.locator('#selection-summary').isVisible(), true);
  const mobileCue = await page.locator('.place-cue-name').evaluate(element => {
    const label = element.getBoundingClientRect(), zoom = document.querySelector('.leaflet-control-zoom').getBoundingClientRect();
    return { width: label.width, aboveZoom: label.bottom <= zoom.top };
  });
  assert.ok(mobileCue.width <= 180 && mobileCue.aboveZoom, JSON.stringify(mobileCue));
  if (process.env.MAP_SCREENSHOTS) {
    await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-mobile-dark.png` });
    await toggleTheme(page);
    await page.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-mobile-light.png` });
    await toggleTheme(page);
  }
  assert.deepEqual(external, []); assert.deepEqual(errors, []);
  await page.setViewportSize({ width: 1440, height: 960 });
  await context.route('https://tile.openstreetmap.org/**', route => route.fulfill({ status: 200, contentType: 'image/png', headers: {'access-control-allow-origin':'*'}, body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGMsAAAAASUVORK5CYII=', 'base64') }));
  await page.locator('#map-options > summary').click();
  await page.locator('#basemap').check();
  await page.waitForFunction(() => document.querySelectorAll('img.leaflet-tile').length > 0);
  await page.locator('#basemap').uncheck();
  await toggleTheme(page);
  const lightOne = await renderEnergy(single, 1, true), lightSix = await renderEnergy(repeated, 6, true);
  assert.ok(Number.isFinite(lightOne.darkestCore) && lightSix.darkestCore < lightOne.darkestCore, `Light route cores must deepen. One=${JSON.stringify(lightOne)}, six=${JSON.stringify(lightSix)}`);
  await fs.copyFile(fixture, datasetPath); await page.reload();
  await page.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  if (await page.locator('#map-options').getAttribute('open') !== null) await page.locator('#map-options > summary').click();
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
  assert.equal(panelBox.width, 320);
  assert.ok(panelBox.height <= 960 && panelBox.height > 600);


  for (const dpr of [1, 2]) {
    const retinaContext = await browser.newContext({ viewport: {width: 1200, height: 800}, deviceScaleFactor: dpr, colorScheme: 'dark' });
    await retinaContext.route('https://tile.openstreetmap.org/**', route => route.fulfill({status:200, contentType:'image/png', headers: {'access-control-allow-origin':'*'}, body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGMsAAAAASUVORK5CYII=', 'base64')}));
    const retinaPage = await retinaContext.newPage(); retinaPage.setDefaultTimeout(15000);
    await retinaPage.goto(url + '#basemap=osm');
    await retinaPage.waitForFunction(() => document.querySelector('img.leaflet-tile-loaded'));
    const scaling = await retinaPage.locator('img.leaflet-tile-loaded').first().evaluate(e => ({width:e.getBoundingClientRect().width, nativeWidth:parseFloat(e.style.width), filter:getComputedStyle(e.closest(".basemap-tiles")).filter}));
    assert.equal(scaling.nativeWidth, dpr === 1 ? 256 : 128);
    assert.ok(scaling.width / scaling.nativeWidth >= .70 && scaling.width / scaling.nativeWidth <= 1.42, JSON.stringify({ dpr, ...scaling }));
    assert.equal(scaling.filter, 'invert(1) hue-rotate(180deg)');
    const tileCount = await retinaPage.locator('img.leaflet-tile').count();
    await toggleTheme(retinaPage);
    assert.equal(await retinaPage.locator('img.leaflet-tile').count(), tileCount);
    assert.equal(await retinaPage.locator('.basemap-tiles').evaluate(e => getComputedStyle(e).filter), 'none');
    for (let step = 0; step < 20; step++) {
      if (await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled') === 'true') break;
      await retinaPage.locator('.leaflet-control-zoom-in').click();
    }
    assert.equal(await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled'), 'true');
    await retinaPage.waitForFunction(() => document.querySelector('img.leaflet-tile-loaded'));
    const tileZooms = await retinaPage.locator('img.leaflet-tile').evaluateAll(images => images.map(image => Number(new URL(image.src).pathname.split('/')[1])));
    assert.ok(tileZooms.length > 0 && tileZooms.every(zoom => zoom <= 19));
    if (dpr === 2) {
      await retinaPage.locator('#map-options > summary').click();
      await retinaPage.locator('#basemap').uncheck();
      await retinaPage.locator('#map-options > summary').click();
      assert.equal(await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled'), 'false');
      await retinaPage.locator('.leaflet-control-zoom-in').click();
      assert.equal(await retinaPage.locator('.leaflet-control-zoom-in').getAttribute('aria-disabled'), 'true');
    }
    await retinaContext.close();
  }

  const continuity = await browser.newContext({ viewport: { width: 628, height: 667 }, colorScheme: 'dark' });
  const tileRequests = [];
  await continuity.route('https://tile.openstreetmap.org/**', async route => {
    tileRequests.push(route.request().url());
    await new Promise(resolve => setTimeout(resolve, 160));
    await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8efea"/><path d="M0 128H256M128 0V256" stroke="#b6c5bc" stroke-width="5"/></svg>' }).catch(() => {});
  });
  const motion = await continuity.newPage();
  const motionErrors = []; motion.on('pageerror', error => motionErrors.push(error.message));
  await motion.goto(url + '#basemap=osm');
  await motion.locator('img.leaflet-tile-loaded').first().waitFor();
  await motion.waitForTimeout(200);
  await motion.mouse.move(420, 270);
  const loadedDuringZoom = [];
  for (let step = 0; step < 24; step++) {
    await motion.mouse.wheel(0, step < 12 ? -45 : 45);
    await motion.waitForTimeout(24);
    const coverage = await motion.evaluate(() => {
      const box = document.querySelector('#map').getBoundingClientRect();
      const x = box.x + box.width / 2, y = box.y + box.height / 2;
      const images = [...document.querySelectorAll('img.leaflet-tile-loaded')];
      return { count: images.length, center: images.some(image => { const r = image.getBoundingClientRect(); return r.left <= x && r.right >= x && r.top <= y && r.bottom >= y; }) };
    });
    loadedDuringZoom.push(coverage);
    assert.ok(coverage.count > 0 && coverage.center, `Zoom discarded the visible basemap: ${JSON.stringify(coverage)}`);
  }
  await motion.waitForTimeout(700);
  await motion.mouse.down(); await motion.mouse.move(460, 300, { steps: 5 }); await motion.mouse.up();
  await motion.waitForTimeout(300);
  assert.ok(await motion.locator('img.leaflet-tile-loaded').count() > 0);
  await motion.locator('#toggle-places').click();
  await motion.waitForTimeout(100);
  const initialList = await motion.locator('#places').boundingBox();
  const beforeSelectionView = await motion.locator('.leaflet-map-pane').getAttribute('style');
  await motion.locator('.place-button').first().click();
  const firstMotionDeadline = Number(await motion.locator('.destination-marker.is-cued button').getAttribute('data-cue-expires-at'));
  assert.equal(await motion.locator('.destination-marker.is-cued button').evaluate(element => getComputedStyle(element, '::after').animationName), 'place-cue');
  await motion.waitForTimeout(650);
  await motion.locator('.place-button').nth(1).click();
  const rapidId = await motion.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id');
  assert.equal(await motion.locator('.destination-marker.is-cued button').getAttribute('data-place-id'), rapidId);
  assert.equal(await motion.locator('.destination-marker.is-cued').count(), 1);
  assert.equal(await motion.locator('.leaflet-map-pane').getAttribute('style'), beforeSelectionView, 'List selection must not move the map.');
  const untilOldDeadline = await motion.evaluate(deadline => deadline - performance.now() + 100, firstMotionDeadline);
  await motion.waitForTimeout(Math.max(0, untilOldDeadline));
  assert.equal(await motion.locator('.destination-marker.is-cued button').getAttribute('data-place-id'), rapidId, 'An old cue timeout must not clear the latest cue.');
  await motion.waitForFunction(() => !document.querySelector('.destination-marker.is-cued'), null, { timeout: 1500 });
  assert.equal(await motion.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id'), rapidId);
  await motion.locator('#locate-place').click();
  assert.equal(await motion.locator('.destination-marker.is-cued button').getAttribute('data-place-id'), rapidId, 'Locate must renew the selected place cue.');
  await motion.locator('#clear-selection').click();
  assert.equal(await motion.locator('.destination-marker.is-cued, .place-button[aria-pressed=true]').count(), 0);
  await motion.locator('.place-button').first().click();
  await motion.locator('.place-button').first().click();
  assert.equal(await motion.locator('.place-button[aria-pressed=true]').count(), 1);
  assert.equal(await motion.locator('#selection-summary').isVisible(), true);
  assert.equal(await motion.locator('#label-form').isVisible(), false);
  const selectedList = await motion.locator('#places').boundingBox();
  assert.ok(Math.abs(initialList.height - selectedList.height) < 1);
  await motion.locator('#edit-place').click();
  await motion.locator('#place-label').fill('未保存的合成名称');
  await motion.locator('#close-places').click();
  assert.equal(await motion.locator('#toggle-places').evaluate(element => element === document.activeElement), true, await motion.evaluate(() => document.activeElement.outerHTML));
  await motion.locator('#toggle-places').click();
  assert.equal(await motion.locator('#place-label').inputValue(), '未保存的合成名称');
  assert.equal(await motion.locator('#label-form').isVisible(), true);
  await motion.locator('#cancel-edit').click();
  const selectedId = await motion.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id');
  await motion.locator('#map').click({ position: { x: 250, y: 130 } });
  await motion.mouse.wheel(0, -30); await motion.waitForTimeout(600);
  assert.equal(await motion.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id'), selectedId);
  if (process.env.MAP_SCREENSHOTS) {
    await motion.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-628-places-dark.png` });
    await toggleTheme(motion);
    await motion.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/synthetic-628-places-light.png` });
    await fs.writeFile(`${process.env.MAP_SCREENSHOTS}/continuity.json`, JSON.stringify({ synthetic: true, delayMs: 160, loadedDuringZoom, initialList, selectedList, requests: tileRequests.length, draftPreserved: true, selectionPreserved: true }, null, 2));
  }
  assert.deepEqual(motionErrors, []);
  await continuity.close();

  const legacy = await browser.newContext();
  const legacyPage = await legacy.newPage();
  await legacyPage.goto(url + '#crs=gcj02');
  await legacyPage.locator('.place-button').first().waitFor({ state: 'attached' });
  await legacyPage.evaluate(async () => {
    const id = document.querySelector('.place-button').dataset.placeId;
    const data = await (await fetch('/dataset.json')).json();
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${data.dataset_id}|wgs84|destinations-fixed-anchor-100m-v1`));
    const key = 'ride-map-labels:' + [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join('');
    localStorage.setItem(key, JSON.stringify({ [id]: '原道路预览名称' }));
  });
  await legacyPage.reload();
  await legacyPage.waitForFunction(() => document.querySelector('.place-name')?.textContent === '原道路预览名称');
  assert.equal(await legacyPage.locator('#crs').count(), 0);
  assert.deepEqual(await legacyPage.locator('.place-count').allTextContents(), ['6次', '3次', '2次', '1次']);
  await legacyPage.locator('#toggle-places').click();
  await legacyPage.locator('.place-button').first().click();
  await legacyPage.locator('#edit-place').click();
  await legacyPage.locator('#place-label').fill('');
  await legacyPage.locator('#label-form button[type=submit]').click();
  assert.equal(await legacyPage.locator('.place-name').first().textContent(), '地点 1');
  await legacyPage.reload();
  await legacyPage.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await legacyPage.locator('.place-name').first().textContent(), '地点 1');
  await legacy.close();

  const blocked = await browser.newContext({ colorScheme: 'dark' });
  await blocked.addInitScript(() => { Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('blocked', 'SecurityError');}}); });
  const blockedPage = await blocked.newPage();
  await blockedPage.goto(url); await blockedPage.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('12 次'));
  assert.equal(await blockedPage.locator('html').getAttribute('data-theme'), 'dark');
  await toggleTheme(blockedPage);
  assert.equal(await blockedPage.locator('html').getAttribute('data-theme'), 'light');
  await blockedPage.locator('#toggle-places').click();
  await blockedPage.locator('.place-button').first().click();
  await blockedPage.locator('#edit-place').click();
  await blockedPage.locator('#place-label').fill('仅本次名称');
  await blockedPage.locator('#label-form button[type=submit]').click();
  assert.equal(await blockedPage.locator('#label-form').isVisible(), true);
  assert.equal(await blockedPage.locator('#label-note').isVisible(), true);
  assert.match(await blockedPage.locator('#label-note').textContent(), /无法保存.*仅本次/);
  await blocked.close();

  await context.close();
  const placeData = makeDataset(Array.from({ length: 104 }, (_, i) => ({ id: `place-${String(i).padStart(3, '0')}`, xy: [[i * 300 - 300, 0], [i * 300, 0]] })));
  for (const [i, ride] of placeData.rides.entries()) {
    ride.started_at = new Date(Date.UTC(2026, 0, 1) + i * 645000).toISOString();
    ride.ended_at = new Date(Date.UTC(2026, 0, 1) + i * 645000 + 600000).toISOString();
  }
  placeData.rides.find(ride => ride.id === 'place-090').ended_at = null;
  await fs.writeFile(datasetPath, JSON.stringify(placeData));
  const placesContext = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const placesPage = await placesContext.newPage();
  const placeErrors = [];
  placesPage.on('pageerror', error => placeErrors.push(error.message));
  await placesPage.goto(url);
  await placesPage.waitForFunction(() => document.querySelector('#visible-stat').textContent.includes('104 次'));
  assert.equal(await placesPage.locator('.destination-marker').count(), 0);
  await placesPage.evaluate(async () => {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('synthetic-map|unverified|destinations-fixed-anchor-100m-v1'));
    const key = 'ride-map-labels:' + [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join('');
    localStorage.setItem(key, JSON.stringify({ 'place-103': '列表外的命名地点' }));
  });
  await placesPage.reload();
  await placesPage.waitForFunction(() => document.querySelector('.destination-marker button')?.dataset.placeId === 'place-103');
  assert.equal(await placesPage.locator('.place-button[data-place-id="place-103"]').count(), 0);
  await placesPage.locator('#toggle-places').click();
  assert.equal(await placesPage.locator('.place-detail').isVisible(), false);
  const namePlace = async (id, label) => {
    await placesPage.locator(`.place-button[data-place-id="${id}"]`).click();
    await placesPage.locator('#edit-place').click();
    await placesPage.locator('#place-label').fill(label);
    await placesPage.locator('#label-form button[type=submit]').click();
  };
  await namePlace('place-000', '合成球馆🏸');
  await namePlace('place-001', '合成球馆🏸');
  assert.equal(await placesPage.locator('#place-total').textContent(), '104 处 · 展示前 100');
  assert.equal((await placesPage.locator('#badminton-stat').textContent()).trim(), '1 次');
  assert.equal(await placesPage.locator('.destination-marker svg.badminton-icon').count(), 2);
  await placesPage.locator('#merge-place').click();
  await placesPage.locator('#merge-target').selectOption('place-000');
  await placesPage.locator('#merge-form button[type=submit]').click();
  assert.equal(await placesPage.locator('#selection-count').textContent(), '2 次行程终点 · 1 个骑行日');
  assert.equal(await placesPage.locator('.place-count').first().textContent(), '1次');
  assert.equal(await placesPage.locator('#place-total').textContent(), '103 处 · 展示前 100');
  await namePlace('place-000', '改名后的球馆🏸');
  await placesPage.reload();
  await placesPage.waitForFunction(() => document.querySelector('.place-name')?.textContent === '改名后的球馆🏸');
  await placesPage.locator('#toggle-places').click();
  await namePlace('place-000', '');
  await placesPage.waitForFunction(() => !document.querySelector('.destination-marker.is-cued'));
  assert.equal(await placesPage.locator('.destination-marker svg.badminton-icon').count(), 0);
  assert.equal(await placesPage.locator('.destination-marker').count(), 1);
  assert.equal(await placesPage.locator('.place-count').first().textContent(), '2次');
  assert.equal((await placesPage.locator('#badminton-stat').textContent()).trim(), '0 次');
  await namePlace('place-000', '奥森南门');
  assert.match(await placesPage.locator('.nature-stat').textContent(), /出门放风感受自然[\s\S]*0 h 1 min/);
  assert.match(await placesPage.locator('.nature-stat').getAttribute('aria-label'), /车辆停放/);
  for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 720 }, { width: 640, height: 360 }, { width: 844, height: 390 }]) {
    await placesPage.setViewportSize(viewport);
    const geometry = await placesPage.evaluate(() => {
      const panel = document.querySelector('#places-panel').getBoundingClientRect();
      const list = document.querySelector('#places').getBoundingClientRect();
      const nature = document.querySelector('.nature-stat').getBoundingClientRect();
      const actions = document.querySelector('.detail-actions').getBoundingClientRect();
      return { panel: { x: panel.x, y: panel.y, width: panel.width, height: panel.height }, listHeight: list.height, actionsVisible: actions.bottom <= innerHeight, natureVisible: nature.top >= list.top && nature.bottom <= list.bottom, noOverflow: document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight };
    });
    assert.equal(geometry.actionsVisible, true, JSON.stringify({ viewport, geometry }));
    assert.equal(geometry.noOverflow, true, JSON.stringify({ viewport, geometry }));
    assert.equal(geometry.natureVisible, true, JSON.stringify({ viewport, geometry }));
    if (viewport.width <= 700) assert.ok(geometry.panel.height <= Math.min(260, viewport.height * .34) + 1, JSON.stringify({ viewport, geometry }));
    if (process.env.MAP_SCREENSHOTS) await placesPage.screenshot({ path: `${process.env.MAP_SCREENSHOTS}/places-nature-${viewport.width}x${viewport.height}.png` });
  }
  await placesPage.setViewportSize({ width: 390, height: 844 });
  await placesPage.locator('#edit-place').click();
  await placesPage.locator('#place-label').fill('保留草稿');
  await placesPage.locator('#close-places').click();
  await toggleTheme(placesPage);
  await placesPage.locator('#toggle-places').click();
  assert.equal(await placesPage.locator('#place-label').inputValue(), '保留草稿');
  assert.equal(await placesPage.locator('.place-button[aria-pressed=true]').getAttribute('data-place-id'), 'place-000');
  await placesPage.locator('#cancel-edit').click();
  await namePlace('place-000', '合成合并地点');
  await namePlace('place-090', '奥森南门');
  assert.match(await placesPage.locator('.nature-stat').textContent(), /暂无停留数据/);
  await placesPage.locator('#clear-selection').click();
  await placesPage.locator('#places').evaluate(element => { element.scrollTop = 0; });
  await placesPage.locator('.place-button[data-place-id="place-090"]').click();
  assert.equal(await placesPage.locator('.nature-stat').evaluate(element => {
    const row = element.getBoundingClientRect(), list = document.querySelector('#places').getBoundingClientRect();
    return row.top >= list.top && row.bottom <= list.bottom;
  }), true, 'Selecting a scrolled nature row must reveal its full statistic after the detail opens.');
  await placesPage.locator('.place-method > summary').click();
  assert.equal(await placesPage.locator('.place-method p').isVisible(), true);
  assert.match(await placesPage.locator('.place-method p').textContent(), /车辆停放/);
  assert.equal(await placesPage.locator('.place-method p').evaluate(element => { const box = element.getBoundingClientRect(); return box.top >= 56 && box.bottom <= innerHeight && box.left >= 0 && box.right <= innerWidth; }), true);
  assert.deepEqual(placeErrors, []);
  await placesContext.close();
  console.log(JSON.stringify({ passed: true, checks: ['named-marker-beyond-list-100', 'explicit-merge-rename-reload-clear', 'same-label-separate', 'badminton-day-dedup', 'nature-exact-seconds-display', 'bounded-mobile-panel-four-viewports', 'local-smiley-font', 'theme-icon-centered-three-widths', 'menu-selected-row-contained', 'rounded-svg-controls', 'cue-monotonic-expiry', 'cue-renewal-preserves-edit', 'cue-rapid-selection', 'cue-locate-renewal', 'cue-reduced-motion', 'temporary-unnamed-selected-pin', 'default-system', 'theme-persistence-reload', 'theme-preserves-view-and-unsaved-label', 'blocked-storage-toggle', 'short-settings-disclosure', 'both-theme-contrast', 'desktop', 'mobile', 'mobile-activity-navigation-390-320', 'counts', 'no-date-filter', 'labels-persist', 'invalid-source-preserves', 'area-hover', 'raw-coordinates-basemap-toggle', 'visible-base-and-repeat-contrast', 'contrast', 'no-external-network', 'no-page-errors', 'online-layer-cleanup', 'two-layer-switches-only', 'quiet-label-scale', 'tiny-svg-markers', 'marker-opens-panel', 'fractional-tile-rendering-dpr1-dpr2', 'light-repeat-deepening', 'keyboard-marker-selection', 'delayed-tile-continuity', 'stable-place-reselection', 'drawer-draft-and-focus', 'route-contrast-two-themes-multiple-zooms'], font, fonts, themeMeasurements, cue: { cueId, initialCueDeadline, renewedCueDeadline, expiredAt, selectedPin }, contrast, overlapBrightnessRatio: +(six / one).toFixed(2) }, null, 2));
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
    await fs.rm(scratch, { recursive: true, force: true });
  }
}
