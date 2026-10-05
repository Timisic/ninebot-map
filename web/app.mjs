import { readRideMap, resolvePlaceLabel } from './model.mjs';
import { createRouteLayer, createBasemap } from './map-layer.mjs';
import { icon } from './icons.mjs';
import { installWheelZoom } from './wheel-zoom.mjs';
const $ = id => document.getElementById(id);
const launch = new URLSearchParams(location.hash.slice(1));
if (launch.get('title')) { $('page-title').textContent = launch.get('title').slice(0, 40); document.title = $('page-title').textContent; }
const map = L.map('map', { scrollWheelZoom: false, zoomControl: false, attributionControl: true, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false, preferCanvas: true, minZoom: 3, maxZoom: 19, zoomSnap: 0, zoomDelta: 1 }).setView([0, 0], 13);
map.attributionControl.setPrefix(false);
L.control.zoom({ position: 'bottomright' }).addTo(map);
installWheelZoom(map);
const routeLayer = createRouteLayer(map), markers = L.layerGroup().addTo(map);
let state = { phase: 'idle', model: null, view: null, selected: null, editing: null, labels: {}, storageKey: null };
let tiles = null, importVersion = 0;
let serverRevision = null, refreshBusy = false;
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
  if (open) { $('map-options').open = false; $('date-panel').open = false; }
  $('workspace').classList.toggle('places-hidden', !open);
  $('toggle-places').setAttribute('aria-expanded', String(open));
  $('toggle-places').textContent = '常去地点';
  $('toggle-places').setAttribute('aria-pressed', String(open));
}
setSidebar(false);
$('map-options').addEventListener('toggle', () => { if ($('map-options').open) setSidebar(false); });
window.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if ($('map-options').open || $('date-panel').open) { $('map-options').open = false; $('date-panel').open = false; }
  else { setSidebar(false); $('toggle-places').focus(); }
});
for (const summary of document.querySelectorAll('#date-panel>summary, #map-options>summary, .place-method>summary')) summary.append(icon('chevron-down'));
function stopTiles() {
  if (tiles) { map.removeLayer(tiles); tiles.off(); tiles = null; }
  map.setMaxZoom(19);
  $('basemap').checked = false; $('map').classList.remove('online-basemap'); render(); $('local-status').textContent = '骑行记录';
}
function fit() {
  if (!state.view?.tracks.length) return;
  const bounds = L.latLngBounds(state.view.tracks.flatMap(t => t.paths.flat()));
  map.fitBounds(bounds, { paddingTopLeft: [32, 100], paddingBottomRight: [64, 64], maxZoom: 16, animate: false });
}
function placeName(place) { return resolvePlaceLabel(place, state.labels); }
function choosePlace(id, fromMarker = false) {
  if (fromMarker) setSidebar(true);
  if (state.selected === id) return;
  state.selected = id; state.editing = null;
  render();
}

function render() {
  const focusPlace = document.activeElement?.dataset?.placeId;
  const focusMarker = document.activeElement?.closest('.destination-marker');
  const listScroll = $('places').scrollTop;
  const { model, view } = state;
  if (!model || !view) return;
  const selectedPlace = view.destinations.find(p => p.id === state.selected);
  if (!selectedPlace) { state.selected = null; state.editing = null; }
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
    const markerButton = document.createElement('button'); markerButton.type = 'button'; markerButton.dataset.placeId = place.id; markerButton.append(icon('map-pin')); markerButton.title = `${placeName(place)} · ${place.count} 次行程终点`;
    markerButton.setAttribute('aria-label', markerButton.title); markerButton.setAttribute('aria-pressed', String(place.id === state.selected));
    markerButton.addEventListener('click', event => { event.stopPropagation(); choosePlace(place.id, true); });
    if (index < 6 || place.id === state.selected) L.marker(place.anchor, { icon: L.divIcon({ className: 'destination-marker', html: markerButton, iconSize: [44, 44], iconAnchor: [22, 22] }), keyboard: false, zIndexOffset: 10000 - index * 100, bubblingMouseEvents: false }).addTo(markers);
  }
  $('places').scrollTop = listScroll;
  if (focusPlace) [...document.querySelectorAll(focusMarker ? '.destination-marker button' : '.place-button')].find(button => button.dataset.placeId === focusPlace)?.focus({ preventScroll: true });
  $('places-empty').hidden = view.destinations.length > 0;
  $('places-empty').textContent = model.totals.map_ride_count ? '当前日期没有可显示的行程终点。' : '数据中没有符合范围的采样轨迹。';
  $('selection-summary').hidden = !selectedPlace || state.editing === state.selected;
  $('selection-empty').hidden = !!selectedPlace;
  $('label-form').hidden = !selectedPlace || state.editing !== state.selected;
  if (selectedPlace) {
    $('selection-name').textContent = placeName(selectedPlace);
    $('selection-count').textContent = `${selectedPlace.count} 次行程终点 · ${selectedPlace.days} 个骑行日`;
    $('place-label').setAttribute('aria-label', `为${selectedPlace.defaultLabel}命名`);
  }
  $('empty').hidden = view.rideCount > 0;
  if (!view.rideCount) { $('empty-title').textContent = model.totals.map_ride_count ? '这段日期暂无轨迹' : '历史已保留，暂无地图轨迹'; $('empty-description').textContent = model.totals.map_ride_count ? '调整日期，或选择全部日期查看当前采样轨迹。' : '缺失、单点与简化轨迹不连线。等待后续可用采样轨迹。';  }

}
function filter() {
  if (!state.model) return;
  try { const view = state.model.select({ from: $('from').value, to: $('to').value }); state = { ...state, view }; showError(''); render(); }
  catch (error) { showError(`${error.message}。保留上一有效范围。`); }
}
async function hashText(text) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join('');
}
async function loadLabels(model) {
  const keys = await Promise.all(['unverified', 'wgs84'].map(async interpretation => {
    return 'ride-map-labels:' + await hashText(`${model.datasetId}|${interpretation}|destinations-fixed-anchor-100m-v1`);
  }));
  const storageKey = keys[0];
  let labels = Object.create(null);
  try {
    for (const key of keys.toReversed()) {
      const saved = JSON.parse(localStorage.getItem(key) || '{}');
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) Object.assign(labels, Object.fromEntries(Object.entries(saved).filter(([, value]) => typeof value === 'string' && value.length <= 40)));
    }
  } catch { $('label-note').textContent = '本地存储不可用，名称仅保留到关闭页面。'; }
  return { storageKey, legacyStorageKey: keys[1], labels };
}
async function loadDataset(text, range = { from: '', to: '' }, fitView = true) {
  const version = ++importVersion;
  state = { ...state, phase: 'loading' }; $('local-status').textContent = '正在读取…'; showError('');
  await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)));
  try {
    const model = readRideMap(text, 'unverified');
    const saved = await loadLabels(model);
    if (version !== importVersion) return;
    stopTiles(); state = { phase: 'ready', model, view: model.select(range), selected: null, editing: null, ...saved };
    for (const id of ['from', 'to', 'clear-dates', 'show-grid', 'basemap', 'fit']) $(id).disabled = false;
    for (const id of ['from', 'to']) { $(id).value = range[id] || ''; $(id).min = model.dateBounds[0]; $(id).max = model.dateBounds[1]; }
    $('updated-at').textContent = '更新于 ' + new Intl.DateTimeFormat('zh-CN', { timeZone: model.timezone, dateStyle: 'short', timeStyle: 'short' }).format(new Date(model.updatedAt));
    render(); if (fitView) fit();
    return true;
  } catch (error) {
    if (version !== importVersion) return;
    state = { ...state, phase: 'error' }; showError(`数据读取失败：${error.message}${state.model ? '。已保留上一份有效地图。' : ''}`);
    if (state.model) render(); else $('local-status').textContent = '等待数据';
  }
}
$('fit').addEventListener('click', fit);
$('toggle-places').addEventListener('click', () => setSidebar($('toggle-places').getAttribute('aria-expanded') !== 'true'));
for (const id of ['from', 'to']) $(id).addEventListener('change', filter);
$('clear-dates').addEventListener('click', () => { $('from').value = ''; $('to').value = ''; filter(); });
$('show-grid').addEventListener('change', () => { $('cell-info').hidden = true; render(); });
$('clear-selection').addEventListener('click', () => { state.selected = null; state.editing = null; render(); });
$('close-places').addEventListener('click', () => { setSidebar(false); $('toggle-places').focus(); });
$('edit-place').addEventListener('click', () => {
  const place = state.view.destinations.find(item => item.id === state.selected);
  if (!place) return;
  state.editing = state.selected; $('place-label').value = placeName(place); $('label-note').textContent = '';
  render(); $('place-label').focus();
});
$('cancel-edit').addEventListener('click', () => { state.editing = null; render(); $('edit-place').focus(); });
$('locate-place').addEventListener('click', () => {
  const place = state.view.destinations.find(item => item.id === state.selected);
  if (place) map.panTo(place.anchor, { animate: false });
});
$('label-form').addEventListener('submit', event => {
  event.preventDefault(); if (!state.selected) return;
  const label = $('place-label').value.trim();
  const place = state.view.destinations.find(p => p.id === state.selected);
  for (const id of place.memberIds) delete state.labels[id];
  if (label) Object.defineProperty(state.labels, state.selected, { value: label, enumerable: true, writable: true, configurable: true });
  try { localStorage.setItem(state.storageKey, JSON.stringify(state.labels)); localStorage.removeItem(state.legacyStorageKey); $('label-note').textContent = '已保存在此浏览器。'; } catch { $('label-note').textContent = '无法保存到浏览器，名称仅本次有效。'; render(); return; }
  state.editing = null; render(); $('edit-place').focus();
});
function updateBasemap() {
  const enabled = $('basemap').checked;
  if (!enabled) { stopTiles(); return; }
  if (!state.model) { stopTiles(); return; }
  tiles = createBasemap('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { className: 'basemap-tiles', detectRetina: true, maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors', crossOrigin: true }).addTo(map);
  map.setMaxZoom(tiles.options.maxZoom);
  tiles.on('tileerror', () => showError('在线底图未能加载。轨迹仍可使用，也可关闭底图恢复离线。'));
  $('map').classList.add('online-basemap'); render();
  $('local-status').textContent = '道路预览';
}
$('basemap').addEventListener('change', updateBasemap);
function showCell(event) {
  if (!state.model || !$('show-grid').checked) return;
  const key = state.model.cellAt(event.latlng.lat, event.latlng.lng), count = state.view.passages.get(key) || 0;
  $('cell-info').hidden = false; $('cell-info').replaceChildren(Object.assign(document.createElement('strong'), {textContent: count}), '次行程经过这个区域');
}
map.on('mousemove click', showCell); map.on('mouseout', () => { $('cell-info').hidden = true; });
const observer = new ResizeObserver(() => map.invalidateSize({ animate: false })); observer.observe($('map'));
window.addEventListener('pagehide', () => { clearInterval(refreshTimer); observer.disconnect(); stopTiles(); routeLayer.remove(); map.remove(); }, { once: true });
try {
  const response = await fetch('./dataset.json', { cache: 'no-store' });
  if (response.ok) {
    const text = await response.text();
    serverRevision = response.headers.get('ETag') || await hashText(text);
    await loadDataset(text);
    if (launch.get('basemap') === 'osm' && state.model) { $('basemap').checked = true; updateBasemap(); }
  }
  else if (response.status !== 404) showError('地图数据暂不可用，请稍后刷新。');
} catch { showError('地图服务暂时无法连接，请稍后刷新。'); }

async function refreshServer() {
  if (refreshBusy || document.hidden || state.phase === 'loading') return;
  refreshBusy = true;
  const requestVersion = importVersion;
  try {
    const head = await fetch('./dataset.json', { method: 'HEAD', cache: 'no-store' });
    const revision = head.headers.get('ETag');
    if (!head.ok || (revision && revision === serverRevision)) return;
    const response = await fetch('./dataset.json', { cache: 'no-store' });
    const text = await response.text();
    const nextRevision = response.headers.get('ETag') || await hashText(text);
    if (nextRevision === serverRevision) return;
    if (!response.ok || state.phase === 'loading' || requestVersion !== importVersion) return;
    const wasOnline = $('basemap').checked;
    const range = { from: $('from').value, to: $('to').value };
    const selection = { selected: state.selected, editing: state.editing, draft: $('place-label').value, datasetId: state.model?.datasetId };
    if (await loadDataset(text, range, false)) {
      if (state.model.datasetId === selection.datasetId && state.view.destinations.some(place => place.id === selection.selected)) {
        state.selected = selection.selected; state.editing = selection.editing; $('place-label').value = selection.draft; render();
      }
      serverRevision = nextRevision;
      if (wasOnline && state.model) { $('basemap').checked = true; updateBasemap(); }
      $('local-status').textContent = '数据已更新';
    }
  } catch { /* A temporary offline server leaves the visible map intact. */ }
  finally { refreshBusy = false; }
}
const refreshTimer = setInterval(refreshServer, 60000);
window.addEventListener('focus', refreshServer);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshServer(); });
