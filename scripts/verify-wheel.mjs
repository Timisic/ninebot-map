import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? {} : { channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }), headless: true });
try {
  const source = await fs.readFile(new URL('web/wheel-zoom.mjs', root), 'utf8');
  const layerSource = await fs.readFile(new URL('web/map-layer.mjs', root), 'utf8');
  const traces = [];
  for (const deviceScaleFactor of [1, 2]) {
    const page = await browser.newPage({ viewport: { width: 800, height: 600 }, deviceScaleFactor });
    await page.setContent('<div id="map" style="width:800px;height:600px"></div>');
    await page.addStyleTag({ path: new URL('web/vendor/leaflet/leaflet.css', root).pathname });
    await page.addScriptTag({ path: new URL('web/vendor/leaflet/leaflet.js', root).pathname });
    await page.addScriptTag({ content: source.replace('export function installWheelZoom(map)', 'window.installWheelZoom = function(map)') });
    await page.addScriptTag({ content: layerSource.replace('export function createBasemap', 'function createBasemap').replace('export function createRouteLayer(map)', 'window.createRouteLayer = function(map)') });
    const trace = await page.evaluate(async () => {
      const map = L.map('map', { scrollWheelZoom: false, zoomAnimation: false, minZoom: 3, maxZoom: 19, zoomSnap: 0 }).setView([31, 121], 13);
      const destroy = installWheelZoom(map);
      const layer = createRouteLayer(map);
      const path = [[31, 121], [31.003, 121.004]];
      layer.setView({}, { tracks: [{ id: 'line', paths: [path] }] }, false, null);
      const marker = L.marker(path[0], { icon: L.divIcon({ html: '', iconSize: [16, 16], iconAnchor: [8, 8] }) }).addTo(map);
      const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
      const point = L.point(320, 260);
      const send = (deltaY, ctrlKey = false, deltaMode = 0) => {
        const bounds = map.getContainer().getBoundingClientRect();
        map.getContainer().dispatchEvent(new WheelEvent('wheel', { deltaY, ctrlKey, deltaMode, clientX: bounds.left + point.x, clientY: bounds.top + point.y, bubbles: true, cancelable: true }));
      };
      const progression = [], alignment = [];
      const capture = () => {
        progression.push(map.getZoom());
        const midpoint = map.latLngToContainerPoint(path[0]).add(map.latLngToContainerPoint(path[1])).divideBy(2);
        const ratio = Math.min(devicePixelRatio, 2), x = Math.round(midpoint.x * ratio), y = Math.round(midpoint.y * ratio);
        if (x < 4 || y < 4 || x >= layer.canvas.width - 4 || y >= layer.canvas.height - 4) return;
        const pixels = layer.canvas.getContext('2d').getImageData(x - 3, y - 3, 7, 7).data;
        const alpha = pixels.filter((_, index) => index % 4 === 3).some(value => value > 0);
        const iconPosition = L.DomUtil.getPosition(marker.getElement()).add(map.layerPointToContainerPoint([0, 0]));
        alignment.push({ alpha, markerError: iconPosition.distanceTo(map.latLngToContainerPoint(path[0])) });
      };
      map.on('zoom', capture);
      const anchor = map.containerPointToLatLng(point);
      send(-60); await wait(35); const first = map.getZoom();
      await wait(700); const settled = map.getZoom(), anchorError = map.latLngToContainerPoint(anchor).distanceTo(point);
      for (let index = 0; index < 10; index++) { send(-24); await wait(18); }
      const sustained = map.getZoom();
      send(60); const reverseStart = map.getZoom(); await wait(35); const reverseNext = map.getZoom();
      await wait(700); const reverseSettled = map.getZoom();
      map.off('zoom', capture);
      const modes = {};
      for (const [name, delta, ctrl, mode] of [['pixel', -60, false, 0], ['line', -3.75, false, 1], ['pinch', -15, true, 0], ['page', -.1, false, 2]]) {
        map.setZoom(10); send(delta, ctrl, mode); await wait(700); modes[name] = map.getZoom();
      }
      map.setZoom(19); send(-3000); await wait(100); const max = map.getZoom(); send(60); await wait(700); const leaveMax = map.getZoom();
      map.setZoom(3); send(3000); await wait(100); const min = map.getZoom(); send(-60); await wait(700); const leaveMin = map.getZoom();
      const cancellation = {};
      for (const action of ['pan', 'fit', 'drag', 'resize']) {
        map.setView([31, 121], 10); send(-240); await wait(30);
        if (action === 'pan') map.panBy([20, 0], { animate: false });
        if (action === 'fit') map.fitBounds(path, { animate: false });
        if (action === 'drag') map.fire('dragstart');
        if (action === 'resize') map.fire('resize');
        const before = map.getZoom(); await wait(200); cancellation[action] = { before, after: map.getZoom() };
      }
      const visibility = [];
      const lum = rgb => rgb.map(value => { value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4; }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
      for (const light of [false, true]) for (const zoom of [10, 13, 16]) {
        map.setView([31, 121], zoom);
        const route = [[200, 300], [600, 300]].map(point => map.containerPointToLatLng(point));
        const background = light ? [237, 242, 239] : [20, 33, 38];
        for (const count of [1, 2, 6]) {
          layer.setView({}, { tracks: Array.from({ length: count }, (_, id) => ({ id, paths: [route] })) }, false, null, light);
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const ratio = Math.min(devicePixelRatio, 2);
          const pixel = Array.from(layer.canvas.getContext('2d').getImageData(400 * ratio, 300 * ratio, 1, 1).data);
          const rendered = pixel.slice(0, 3).map((value, index) => value * pixel[3] / 255 + background[index] * (1 - pixel[3] / 255));
          const a = lum(rendered), b = lum(background);
          visibility.push({ light, zoom, count, contrast: (Math.max(a, b) + .05) / (Math.min(a, b) + .05), luminance: a, pixel });
        }
      }
      send(-240); await wait(25); destroy(); const beforeDestroy = map.getZoom(); send(-240); await wait(200); const afterDestroy = map.getZoom();
      window.wheelTest = { map, send, installWheelZoom };
      return { visibility, dpr: devicePixelRatio, first, settled, anchorError, sustained, reverseStart, reverseNext, reverseSettled, modes, max, leaveMax, min, leaveMin, cancellation, beforeDestroy, afterDestroy, progression, alignment };
    });
    assert.ok(trace.first > 13 && trace.first < 13.25, JSON.stringify(trace));
    assert.equal(trace.settled, 13.25);
    assert.ok(trace.anchorError <= 1.5);
    assert.ok(trace.sustained > trace.settled + .5);
    assert.ok(trace.reverseNext < trace.reverseStart);
    assert.ok(Math.abs(trace.reverseSettled - (trace.reverseStart - .25)) < .00001);
    assert.ok(trace.progression.length > 10 && trace.progression.some(value => value % 1 !== 0));
    assert.ok(trace.alignment.length > 10 && trace.alignment.every(value => value.alpha && value.markerError <= 1.5), JSON.stringify(trace.alignment));
    assert.deepEqual(trace.modes, { pixel: 10.25, line: 10.25, pinch: 10.25, page: 10.25 });
    assert.deepEqual([trace.max, trace.leaveMax, trace.min, trace.leaveMin], [19, 18.75, 3, 3.25]);
    for (const value of Object.values(trace.cancellation)) assert.equal(value.after, value.before);
    assert.equal(trace.afterDestroy, trace.beforeDestroy);
    for (let index = 0; index < trace.visibility.length; index += 3) {
      const [once, twice, frequent] = trace.visibility.slice(index, index + 3);
      assert.ok(once.contrast >= 3 && twice.contrast >= 3 && frequent.contrast >= 3, JSON.stringify([once, twice, frequent]));
      assert.ok(once.light ? frequent.luminance < twice.luminance && twice.luminance < once.luminance : frequent.luminance > twice.luminance && twice.luminance > once.luminance, JSON.stringify([once, twice, frequent]));
    }
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const reduced = await page.evaluate(async () => {
      const { map, send, installWheelZoom } = window.wheelTest;
      installWheelZoom(map); map.setZoom(10); send(-60);
      const immediate = map.getZoom();
      await new Promise(resolve => setTimeout(resolve, 120));
      const settled = map.getZoom();
      map.remove(); send(-60);
      return { immediate, settled, unload: true };
    });
    assert.deepEqual(reduced, { immediate: 10.25, settled: 10.25, unload: true });
    traces.push({ ...trace, alignment: { samples: trace.alignment.length, allAligned: true }, progression: trace.progression.slice(0, 12), reduced });
    await page.close();
  }
  assert.deepEqual(traces[0].modes, traces[1].modes);
  console.log(JSON.stringify({ passed: true, kind: 'Synthetic DOM events through production wheel and Canvas layers. Physical trackpad feel is not tested.', traces }, null, 2));
} finally { await browser.close(); }
