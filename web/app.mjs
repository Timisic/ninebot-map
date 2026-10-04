import { readRideMap, LIMITS, tilesAllowed, resolvePlaceLabel } from './model.mjs';
import { createRouteLayer } from './map-layer.mjs';
import { icon } from './icons.mjs';
import { installWheelZoom } from './wheel-zoom.mjs';
const $ = id => document.getElementById(id);
const launch = new URLSearchParams(location.hash.slice(1));
if (launch.get('title')) { $('page-title').textContent = launch.get('title').slice(0, 40); document.title = $('page-title').textContent; }
const map = L.map('map', { scrollWheelZoom: false, zoomControl: true, attributionControl: true, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false, preferCanvas: true, minZoom: 3, maxZoom: 19, zoomSnap: 1, zoomDelta: 1 }).setView([0, 0], 13);
map.attributionControl.setPrefix(false);
installWheelZoom(map);
const routeLayer = createRouteLayer(map), markers = L.layerGroup().addTo(map);
let state = { phase: 'idle', model: null, source: null, view: null, selected: null, labels: {}, storageKey: null };
let tiles = null, importVersion = 0;
let followServer = true, serverRevision = null, refreshBusy = false;
/** @typedef {'light' | 'dark'} Theme */
/** @type {Theme} */
let theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
function applyTheme() {
  document.documentElement.dataset.theme = theme;
  const target = theme === 'dark' ? '浅色' : '深色';
  $('theme-toggle').replaceChildren(icon(theme === 'dark' ? 'sun' : 'moon'));
  $('theme-toggle').setAttribute('aria-label', `切换为${target}`);
  $('theme-toggle').title = `切换为${target}`;
  if (state.model && state.view) {
    const selected = state.view.destinations.find(place => place.id === state.selected);
    routeLayer.setView(state.model, state.view, $('show-grid').checked, selected ? new Set(selected.visibleMemberIds) : null, theme === 'light');
  }
}
$('theme-toggle').addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('ride-map-theme', theme); } catch {}
  applyTheme();
});
applyTheme();
for (const element of document.querySelectorAll('.map-settings, .toolbar, #places-panel')) {
  L.DomEvent.disableClickPropagation(element);
  L.DomEvent.disableScrollPropagation(element);
}
const km = value => value === null ? '里程不完整' : `${(value / 1000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} km`;
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
function setSidebar(open) {
  $('workspace').classList.toggle('places-hidden', !open);
  $('toggle-places').setAttribute('aria-expanded', String(open));
  $('toggle-places').textContent = open ? '收起地点' : '常去地点';
}
setSidebar(false);
$('import-button').prepend(icon('upload'));
for (const id of ['date-panel', 'map-options']) $(id).querySelector('summary').append(icon('chevron-down'));
function stopTiles() {
  if (tiles) { map.removeLayer(tiles); tiles.off(); tiles = null; }
  map.setMaxZoom(19);
  $('basemap').checked = false; $('map').classList.remove('online-basemap'); render(); $('local-status').textContent = '本地数据';
}
function coordinateNote() {
  const model = state.model;
  if (!model) return;
  const manual = model.interpretation !== model.declaredCrs ? '手动解释，未修改文件声明。' : '';
  $('crs-note').textContent = model.interpretation === 'unverified' ? '坐标系尚未核实，当前只显示相对位置。' : model.interpretation === 'wgs84' ? `${manual}原始坐标直接叠加道路底图，尚未核实的来源仍需对照。` : `${manual}在本机将 ${model.interpretation.toUpperCase()} 转为 WGS84。校准是近似转换，不改动原始数据。`;
  $('basemap').disabled = !tilesAllowed(model.interpretation);
  $('basemap-gate').hidden = !$('basemap').disabled;
}
function fit() {
  if (!state.view?.tracks.length) return;
  const bounds = L.latLngBounds(state.view.tracks.flatMap(t => t.paths.flat()));
  const panelOpen = $('toggle-places').getAttribute('aria-expanded') === 'true' && innerWidth > 700;
  map.fitBounds(bounds, { paddingTopLeft: [60, 105], paddingBottomRight: [panelOpen ? 300 : 60, 95], maxZoom: 16, animate: false });
}
function placeName(place) { return resolvePlaceLabel(place, state.labels); }
function choosePlace(id, fromMarker = false) {
  state.selected = state.selected === id ? null : id;
  if (fromMarker && state.selected) setSidebar(true);
  render();
  if (state.selected) {
    const place = state.view.destinations.find(p => p.id === id);
    const panelOffset = innerWidth > 700 && $('toggle-places').getAttribute('aria-expanded') === 'true' ? 140 : 0;
    map.panTo(place.anchor, { animate: false });
    if (panelOffset) map.panBy([panelOffset, 0], { animate: false });
    else if (innerWidth <= 700) map.panBy([0, 120], { animate: false });
  }
}
function render() {
  const focusPlace = document.activeElement?.dataset?.placeId;
  const listScroll = $('places').scrollTop;
  const { model, view } = state;
  if (!model || !view) return;
  const selectedPlace = view.destinations.find(p => p.id === state.selected);
  if (!selectedPlace) state.selected = null;
  routeLayer.setView(model, view, $('show-grid').checked, selectedPlace ? new Set(selectedPlace.visibleMemberIds) : null, theme === 'light');
  $('history-stat').replaceChildren('全部历史 ', Object.assign(document.createElement('strong'), { textContent: `${model.totals.ride_count} 次 · ${km(model.totals.total_distance_m)}` }));
  $('visible-stat').replaceChildren('当前地图 ', Object.assign(document.createElement('strong'), { textContent: `${view.rideCount} 次 · ${km(view.distance)}` }));
  $('place-total').textContent = `${view.destinations.length} 处${view.destinations.length > 100 ? ' · 展示前 100' : ''}`;
  $('places').replaceChildren(); markers.clearLayers();
  for (const [index, place] of view.destinations.slice(0, 100).entries()) {
    const button = document.createElement('button'); button.className = 'place-button'; button.type = 'button';
    button.setAttribute('aria-pressed', String(place.id === state.selected)); button.setAttribute('aria-label', `${placeName(place)}，${place.count} 次行程终点`); button.dataset.placeId = place.id;
    const glyph = icon('map-pin');
    const copy = Object.assign(document.createElement('span'), { className: 'place-copy' });
    copy.append(Object.assign(document.createElement('span'), { className: 'place-name', textContent: placeName(place) }), Object.assign(document.createElement('span'), { className: 'place-days', textContent: `${place.days} 个骑行日` }));
    const count = Object.assign(document.createElement('span'), { className: 'place-count', textContent: place.count }); count.append(Object.assign(document.createElement('small'), { textContent: '次' }));
    button.append(glyph, copy, count); button.addEventListener('click', () => choosePlace(place.id));
    const li = document.createElement('li'); li.append(button); $('places').append(li);
    const markerButton = document.createElement('button'); markerButton.type = 'button'; markerButton.append(icon('map-pin')); markerButton.title = `${placeName(place)} · ${place.count} 次行程终点`;
    markerButton.setAttribute('aria-label', markerButton.title); markerButton.setAttribute('aria-pressed', String(place.id === state.selected));
    markerButton.addEventListener('click', event => { event.stopPropagation(); choosePlace(place.id, true); });
    if (index < 6 || place.id === state.selected) L.marker(place.anchor, { icon: L.divIcon({ className: 'destination-marker', html: markerButton, iconSize: [44, 44], iconAnchor: [22, 22] }), keyboard: false, zIndexOffset: 10000 - index * 100, bubblingMouseEvents: false }).addTo(markers);
  }
  $('places').scrollTop = listScroll;
  if (focusPlace) [...$('places').querySelectorAll('button')].find(button => button.dataset.placeId === focusPlace)?.focus({ preventScroll: true });
  $('places-empty').hidden = view.destinations.length > 0;
  $('places-empty').textContent = model.totals.map_ride_count ? '当前日期没有可显示的行程终点。' : '数据中没有符合范围的采样轨迹。';
  $('label-form').hidden = !selectedPlace;
  if (selectedPlace) { $('place-label').value = placeName(selectedPlace); $('place-label').setAttribute('aria-label', `为${selectedPlace.defaultLabel}命名`); }
  $('empty').hidden = view.rideCount > 0;
  if (!view.rideCount) { $('empty-title').textContent = model.totals.map_ride_count ? '这段日期暂无轨迹' : '历史已保留，暂无地图轨迹'; $('empty-description').textContent = model.totals.map_ride_count ? '调整日期，或选择全部日期查看已导入的采样轨迹。' : '缺失、单点与简化轨迹不连线。可导入包含采样轨迹的数据集。'; $('empty-import').hidden = model.totals.map_ride_count > 0; }
  const scope = $('from').value || $('to').value ? '已按日期筛选' : '全部地图日期';
  $('status').textContent = `${scope} · ${model.timezone} · ${model.diagnostics.excluded} 次未纳入地图 · ${model.diagnostics.gaps} 处超过 1 km 的断点已分开${model.interpretation !== 'wgs84' ? ' · 坐标相对预览，区域近似' : ''}`;
}
function filter() {
  if (!state.model) return;
  try { const view = state.model.select({ from: $('from').value, to: $('to').value }); state = { ...state, view }; showError(''); render(); }
  catch (error) { showError(`${error.message}。保留上一有效范围。`); }
}
async function loadLabels(model) {
  const bytes = new TextEncoder().encode(`${model.datasetId}|${model.interpretation}|destinations-fixed-anchor-100m-v1`);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const storageKey = 'ride-map-labels:' + [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join('');
  let labels = Object.create(null);
  try { const saved = JSON.parse(localStorage.getItem(storageKey) || '{}'); if (saved && typeof saved === 'object' && !Array.isArray(saved)) labels = Object.fromEntries(Object.entries(saved).filter(([key, value]) => typeof value === 'string' && value.length <= 40)); }
  catch { $('label-note').textContent = '本地存储不可用，名称仅保留到关闭页面。'; }
  return { storageKey, labels };
}
async function importText(text, interpretation, range = { from: '', to: '' }, fitView = true) {
  const version = ++importVersion;
  state = { ...state, phase: 'loading' }; $('status').textContent = '正在本机校验与绘制…'; showError('');
  await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)));
  try {
    const model = readRideMap(text, interpretation);
    const saved = await loadLabels(model);
    if (version !== importVersion) return;
    stopTiles(); state = { phase: 'ready', model, source: text, view: model.select(range), selected: null, ...saved };
    for (const id of ['from', 'to', 'clear-dates', 'show-grid', 'crs', 'fit']) $(id).disabled = false;
    for (const id of ['from', 'to']) { $(id).value = range[id] || ''; $(id).min = model.dateBounds[0]; $(id).max = model.dateBounds[1]; }
    $('crs').value = model.interpretation; $('empty-import').hidden = false; coordinateNote(); render(); if (fitView) fit();
    return true;
  } catch (error) {
    if (version !== importVersion) return;
    state = { ...state, phase: 'error' }; showError(`导入失败：${error.message}${state.model ? '。已保留上一份有效地图。' : ''}`);
    if (state.model) { $('crs').value = state.model.interpretation; render(); } else $('status').textContent = '文件未载入，请选择有效的 Ride Dataset v1 数据集';
  }
}
async function importFile(file) {
  if (!file) return;
  if (file.size > LIMITS.bytes) { showError('文件超过 40 MB 上限，请缩小数据集。上一份地图保持不变。'); return; }
  try { if (await importText(await file.text())) followServer = false; } catch { showError('无法读取文件，请重新选择。'); }
}
$('import-button').addEventListener('click', () => $('file').click()); $('empty-import').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', async event => { await importFile(event.target.files[0]); event.target.value = ''; });
$('fit').addEventListener('click', fit);
$('toggle-places').addEventListener('click', () => setSidebar($('toggle-places').getAttribute('aria-expanded') !== 'true'));
for (const id of ['from', 'to']) $(id).addEventListener('change', filter);
$('clear-dates').addEventListener('click', () => { $('from').value = ''; $('to').value = ''; filter(); });
$('show-grid').addEventListener('change', () => { $('cell-info').hidden = true; render(); });
$('crs').addEventListener('change', async event => {
  const wasOnline = $('basemap').checked;
  await importText(state.source, event.target.value, { from: $('from').value, to: $('to').value });
  if (wasOnline && state.model && tilesAllowed(state.model.interpretation)) { $('basemap').checked = true; updateBasemap(); }
});
$('clear-selection').addEventListener('click', () => { state.selected = null; render(); });
$('label-form').addEventListener('submit', event => {
  event.preventDefault(); if (!state.selected) return;
  const label = $('place-label').value.trim();
  const place = state.view.destinations.find(p => p.id === state.selected);
  for (const id of place.memberIds) delete state.labels[id];
  if (label) Object.defineProperty(state.labels, state.selected, { value: label, enumerable: true, writable: true, configurable: true });
  try { localStorage.setItem(state.storageKey, JSON.stringify(state.labels)); $('label-note').textContent = '已保存在此浏览器。'; } catch { $('label-note').textContent = '无法保存到浏览器，名称仅本次有效。'; }
  render();
});
function updateBasemap() {
  const enabled = $('basemap').checked;
  if (!enabled) { stopTiles(); return; }
  if (!state.model || !tilesAllowed(state.model.interpretation)) { stopTiles(); return; }
  tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { className: 'basemap-tiles', detectRetina: true, maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors', crossOrigin: true }).addTo(map);
  map.setMaxZoom(tiles.options.maxZoom);
  tiles.on('tileerror', () => showError('在线底图未能加载。轨迹仍可使用，也可关闭底图恢复离线。'));
  $('map').classList.add('online-basemap'); render();
  $('local-status').textContent = '道路底图 · 本地轨迹';
}
$('basemap').addEventListener('change', updateBasemap);
function showCell(event) {
  if (!state.model || !$('show-grid').checked) return;
  const key = state.model.cellAt(event.latlng.lat, event.latlng.lng), count = state.view.passages.get(key) || 0;
  $('cell-info').hidden = false; $('cell-info').replaceChildren(Object.assign(document.createElement('strong'), {textContent: count}), '次行程经过这个区域');
}
map.on('mousemove click', showCell); map.on('mouseout', () => { $('cell-info').hidden = true; });
let dragDepth = 0;
window.addEventListener('dragenter', event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); dragDepth++; $('workspace').classList.add('dragging-file'); } });
window.addEventListener('dragover', event => { event.preventDefault(); });
window.addEventListener('dragleave', () => { if (--dragDepth <= 0) $('workspace').classList.remove('dragging-file'); });
window.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; $('workspace').classList.remove('dragging-file'); importFile(event.dataTransfer.files[0]); });
const observer = new ResizeObserver(() => map.invalidateSize({ animate: false })); observer.observe($('map'));
window.addEventListener('pagehide', () => { clearInterval(refreshTimer); observer.disconnect(); stopTiles(); routeLayer.remove(); map.remove(); }, { once: true });
try {
  const response = await fetch('/dataset.json', { cache: 'no-store' });
  if (response.ok) {
    serverRevision = response.headers.get('ETag');
    const requested = launch.get('crs');
    await importText(await response.text(), ['wgs84','gcj02','bd09'].includes(requested) ? requested : undefined);
    if (launch.get('basemap') === 'osm' && state.model && tilesAllowed(state.model.interpretation)) { $('basemap').checked = true; updateBasemap(); }
  }
  else if (response.status !== 404) showError('启动数据未能读取，请使用导入按钮。');
} catch { showError('本地服务未连接，仍可通过文件按钮导入数据。'); }

async function refreshServer() {
  if (!followServer || refreshBusy || document.hidden || state.phase === 'loading') return;
  refreshBusy = true;
  const requestVersion = importVersion;
  try {
    const head = await fetch('/dataset.json', { method: 'HEAD', cache: 'no-store' });
    const revision = head.headers.get('ETag');
    if (!head.ok || !revision || revision === serverRevision) return;
    const response = await fetch('/dataset.json', { cache: 'no-store' });
    const text = await response.text();
    if (!response.ok || !followServer || state.phase === 'loading' || requestVersion !== importVersion) return;
    const wasOnline = $('basemap').checked;
    const interpretation = state.model?.interpretation;
    const range = { from: $('from').value, to: $('to').value };
    if (await importText(text, interpretation, range, false)) {
      serverRevision = response.headers.get('ETag');
      if (wasOnline && state.model && tilesAllowed(state.model.interpretation)) { $('basemap').checked = true; updateBasemap(); }
      $('local-status').textContent = '本地数据已更新';
    }
  } catch { /* A temporary offline server leaves the visible map intact. */ }
  finally { refreshBusy = false; }
}
const refreshTimer = setInterval(refreshServer, 60000);
window.addEventListener('focus', refreshServer);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshServer(); });
