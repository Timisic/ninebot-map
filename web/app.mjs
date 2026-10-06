import { readRideMap, resolvePlaceLabel } from './model.mjs';
import { createRouteLayer, createBasemap } from './map-layer.mjs';
import { icon } from './icons.mjs';
import { installWheelZoom } from './wheel-zoom.mjs';
const $ = id => document.getElementById(id);
if (!window.alongStartup) {
  $('error').textContent = '地图页面未能加载，请稍后刷新。'; $('error').hidden = false;
  $('local-status').textContent = '页面加载失败'; $('update-status').hidden = true;
  for (const id of ['visible-stat', 'history-stat']) $(id).querySelector('strong').textContent = '未能读取';
} else if (!window.alongStartup.closed) {
const launch = new URLSearchParams(location.hash.slice(1));
const map = L.map('map', { scrollWheelZoom: false, zoomControl: false, attributionControl: true, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false, preferCanvas: true, minZoom: 3, maxZoom: 19, zoomSnap: 0, zoomDelta: 1 }).setView([0, 0], 13);
map.attributionControl.setPrefix(false);
L.control.zoom({ position: 'bottomright' }).addTo(map);
for (const [selector, name] of [['.leaflet-control-zoom-in', 'plus'], ['.leaflet-control-zoom-out', 'minus']]) document.querySelector(selector).replaceChildren(icon(name));
$('fit').replaceChildren(icon('expand'));
$('fit').title = '查看全部路线';
$('update-map').replaceChildren(icon('refresh'), Object.assign(document.createElement('span'), { textContent: '更新' }));
installWheelZoom(map);
const routeLayer = createRouteLayer(map), markers = L.layerGroup().addTo(map);
let state = { phase: 'loading', model: null, view: null, selected: null, editing: null, labels: {}, storageKey: null, placeCue: null };
const lifecycle = new AbortController();
const placeCueDuration = 3000;
let placeCueTimer = null;
let tiles = null, importVersion = 0;
let datasetFrame = null, datasetTimer = null, datasetResume = null;
let serverRevision = null, refreshBusy = false, refreshTimer = null;
let themePreference = document.documentElement.dataset.themePreference || 'system';
const systemTheme = matchMedia('(prefers-color-scheme: dark)');
let theme;
function applyTheme() {
  theme = themePreference === 'system' ? systemTheme.matches ? 'dark' : 'light' : themePreference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.themePreference = themePreference;
  const label = { system: '跟随系统', light: '浅色', dark: '深色' }[themePreference];
  $('theme-toggle').replaceChildren(icon(theme === 'dark' ? 'moon' : 'sun'));
  $('theme-toggle').setAttribute('aria-label', `外观，${label}`);
  $('theme-toggle').title = `外观，${label}`;
  for (const button of document.querySelectorAll('button[data-theme-preference]')) button.setAttribute('aria-pressed', String(button.dataset.themePreference === themePreference));
  if (state.model && state.view) {
    const selected = state.view.destinations.find(place => place.id === state.selected);
    routeLayer.setView(state.model, state.view, $('show-grid').checked, selected ? new Set(selected.visibleMemberIds) : null, theme === 'light');
  }
}
for (const button of document.querySelectorAll('button[data-theme-preference]')) button.addEventListener('click', () => {
  themePreference = button.dataset.themePreference;
  try { localStorage.setItem('ride-map-theme', themePreference); } catch {}
  $('theme-options').open = false;
  applyTheme(); $('theme-toggle').focus();
});
systemTheme.addEventListener('change', () => { if (themePreference === 'system') applyTheme(); });
applyTheme();
for (const element of document.querySelectorAll('.map-settings, .toolbar, #places-panel')) {
  L.DomEvent.disableClickPropagation(element);
  L.DomEvent.disableScrollPropagation(element);
}
const km = value => value === null ? '里程不完整' : `${(value / 1000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} km`;
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
function setSidebar(open) {
  if (open) $('map-options').open = false;
  $('workspace').classList.toggle('places-hidden', !open);
  $('toggle-places').setAttribute('aria-expanded', String(open));
  $('toggle-places').textContent = '常去地点';
  $('toggle-places').setAttribute('aria-pressed', String(open));
}
setSidebar(false);
$('map-options').addEventListener('toggle', () => { if ($('map-options').open) setSidebar(false); });
window.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (!$('inline-hint').hidden) hideHint();
  else if ($('theme-options').open) { $('theme-options').open = false; $('theme-toggle').focus(); }
  else if ($('map-options').open) $('map-options').open = false;
  else { setSidebar(false); $('toggle-places').focus(); }
});
for (const summary of document.querySelectorAll('#map-options>summary, .place-method>summary')) summary.append(icon('chevron-down'));
function stopTiles() {
  if (tiles) { map.removeLayer(tiles); tiles.off(); tiles = null; }
  map.setMaxZoom(19);
  $('basemap').checked = false; $('map').classList.remove('online-basemap'); render(); $('local-status').textContent = '路线已就绪';
}
function fit() {
  if (!state.view?.tracks.length) return;
  const bounds = L.latLngBounds(state.view.tracks.flatMap(t => t.paths.flat()));
  map.fitBounds(bounds, { paddingTopLeft: [32, 100], paddingBottomRight: [64, 64], maxZoom: 16, animate: false });
}
function placeName(place) { return resolvePlaceLabel(place, state.labels); }
function clearPlaceCue() {
  clearTimeout(placeCueTimer); placeCueTimer = null; state.placeCue = null;
}
function cuePlace(id) {
  clearPlaceCue();
  const cue = { datasetId: state.model.datasetId, id, expiresAt: performance.now() + placeCueDuration };
  state.placeCue = cue;
  placeCueTimer = setTimeout(() => {
    if (state.placeCue !== cue || state.phase === 'closed') return;
    clearPlaceCue(); render();
  }, placeCueDuration);
}
function choosePlace(id, fromMarker = false) {
  if (!state.view?.destinations.some(place => place.id === id)) return;
  if (fromMarker) setSidebar(true);
  cuePlace(id);
  if (state.selected === id) { render(); return; }
  state.selected = id; state.editing = null;
  render();
}

function render() {
  const focusPlace = document.activeElement?.dataset?.placeId;
  const focusMarker = document.activeElement?.closest('.destination-marker');
  const listScroll = $('places').scrollTop;
  const { model, view } = state;
  if (!model || !view) return;
  if (state.placeCue && (state.placeCue.datasetId !== model.datasetId || state.placeCue.expiresAt <= performance.now() || !view.destinations.some(place => place.id === state.placeCue.id))) clearPlaceCue();
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
    const cued = state.placeCue?.id === place.id;
    if (cued) {
      markerButton.style.setProperty('--cue-elapsed', `${state.placeCue.expiresAt - performance.now() - placeCueDuration}ms`);
      markerButton.dataset.cueExpiresAt = state.placeCue.expiresAt;
      markerButton.append(Object.assign(document.createElement('span'), { className: 'place-cue-name', textContent: placeName(place) }));
      markerButton.lastElementChild.setAttribute('aria-hidden', 'true');
    }
    if (index < 6 || place.id === state.selected || cued) L.marker(place.anchor, { icon: L.divIcon({ className: `destination-marker${cued ? ' is-cued' : ''}`, html: markerButton, iconSize: [44, 44], iconAnchor: [22, 22] }), keyboard: false, zIndexOffset: place.id === state.selected ? 20000 : 10000 - index * 100, bubblingMouseEvents: false }).addTo(markers);
  }
  $('places').scrollTop = listScroll;
  if (focusPlace) [...document.querySelectorAll(focusMarker ? '.destination-marker button' : '.place-button')].find(button => button.dataset.placeId === focusPlace)?.focus({ preventScroll: true });
  $('places-empty').hidden = view.destinations.length > 0;
  $('places-empty').textContent = '数据中没有符合范围的行程终点。';
  $('selection-summary').hidden = !selectedPlace || state.editing === state.selected;
  $('selection-empty').hidden = !!selectedPlace;
  $('label-form').hidden = !selectedPlace || state.editing !== state.selected;
  if (selectedPlace) {
    $('selection-name').textContent = placeName(selectedPlace);
    $('selection-count').textContent = `${selectedPlace.count} 次行程终点 · ${selectedPlace.days} 个骑行日`;
    $('place-label').setAttribute('aria-label', `为${selectedPlace.defaultLabel}命名`);
  }
  $('empty').hidden = view.rideCount > 0;
  if (!view.rideCount) { $('empty-title').textContent = '历史已保留，暂无地图轨迹'; $('empty-description').textContent = '缺失、单点与简化轨迹不连线。等待后续可用采样轨迹。'; }
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
  } catch { return { storageKey, legacyStorageKey: keys[1], labels, labelNote: '本地存储不可用，名称仅保留到关闭页面。' }; }
  return { storageKey, legacyStorageKey: keys[1], labels, labelNote: '' };
}
async function loadDataset(text, fitView = true) {
  if (state.phase === 'closed') return;
  const version = ++importVersion;
  state = { ...state, phase: 'loading' }; $('local-status').textContent = '正在读取…'; showError('');
  await new Promise(resolve => {
    datasetResume = resolve;
    datasetFrame = requestAnimationFrame(() => {
      datasetFrame = null;
      datasetTimer = setTimeout(() => { datasetTimer = null; datasetResume = null; resolve(); }, 0);
    });
  });
  if (version !== importVersion) return;
  try {
    const model = readRideMap(text, 'unverified');
    const saved = await loadLabels(model);
    if (version !== importVersion) return;
    stopTiles(); state = { phase: 'ready', model, view: model.select(), selected: null, editing: null, placeCue: state.placeCue, ...saved };
    $('label-note').textContent = saved.labelNote;
    for (const id of ['show-grid', 'basemap', 'fit']) $(id).disabled = false;
    const updatedAt = new Date(model.updatedAt);
    $('updated-at').textContent = '更新于 ' + new Intl.DateTimeFormat('zh-CN', { timeZone: model.timezone, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(updatedAt);
    $('updated-at').dateTime = model.updatedAt;
    $('updated-at').title = new Intl.DateTimeFormat('zh-CN', { timeZone: model.timezone, dateStyle: 'full', timeStyle: 'long' }).format(updatedAt);
    render(); renderUpdate(); if (fitView) fit();
    return true;
  } catch (error) {
    if (version !== importVersion) return;
    state = { ...state, phase: 'error' }; showError(`数据读取失败：${error.message}${state.model ? '。已保留上一份有效地图。' : ''}`);
    if (state.model) render();
    else {
      $('local-status').textContent = '数据读取失败';
      for (const id of ['visible-stat', 'history-stat']) $(id).querySelector('strong').textContent = '未能读取';
    }
    renderUpdate();
  }
}
$('fit').addEventListener('click', fit);
$('toggle-places').addEventListener('click', () => setSidebar($('toggle-places').getAttribute('aria-expanded') !== 'true'));
$('show-grid').addEventListener('change', () => { $('cell-info').hidden = true; render(); });
$('clear-selection').addEventListener('click', () => { clearPlaceCue(); state.selected = null; state.editing = null; render(); });
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
  if (place) { cuePlace(place.id); render(); map.panTo(place.anchor, { animate: false }); }
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

let updateState = { phase: 'unavailable', canRequest: false, requestedAt: null, nextAllowedAt: null, request: 'idle', timer: null };
let hintTimer;
function hideHint() { clearTimeout(hintTimer); $('inline-hint').hidden = true; }
function showHint(anchor, message) {
  hideHint();
  const hint = $('inline-hint'); hint.textContent = message; hint.hidden = false;
  const box = anchor.getBoundingClientRect();
  hint.style.top = `${box.bottom + 6}px`;
  hint.style.left = `${Math.max(12, Math.min(box.left, innerWidth - hint.offsetWidth - 12))}px`;
  hintTimer = setTimeout(hideHint, 3500);
}
$('running').addEventListener('click', () => showHint($('running'), '正在running中...'));
window.addEventListener('resize', hideHint);
function updatedDatasetObserved() {
  return !!state.model && !!updateState.requestedAt && new Date(state.model.updatedAt) >= new Date(updateState.requestedAt);
}
function renderUpdate() {
  const button = $('update-map');
  button.disabled = updateState.phase === 'unavailable' || updateState.request === 'dispatching';
  button.querySelector('span').textContent = updateState.request === 'dispatching' ? '提交中' : '更新';
  button.setAttribute('aria-label', updateState.request === 'dispatching' ? '正在提交更新请求' : '获取最新骑行数据');
  button.title = updateState.phase === 'unavailable' ? '当前站点暂不支持在线更新。' : '获取最新骑行数据，所有访客共用 12 小时间隔。';
  const text = state.phase === 'loading' && !state.model ? '正在加载路线…' : {
    idle: '', queued: '等待更新', running: '更新中', unknown: '正在确认更新状态', unavailable: '', failed: '更新未完成，请稍后重试。',
    succeeded: updatedDatasetObserved() ? '地图已更新' : '等待地图更新'
  }[updateState.phase];
  $('update-status').textContent = text; $('update-status').hidden = !text;
  $('update-status').classList.toggle('visually-hidden', updateState.phase === 'succeeded' && updatedDatasetObserved());
}
function parseUpdate(value) {
  const phases = ['idle', 'queued', 'running', 'succeeded', 'failed', 'unknown', 'unavailable'];
  const validTime = time => time === null || typeof time === 'string' && Number.isFinite(Date.parse(time));
  if (!value || !phases.includes(value.phase) || typeof value.can_request !== 'boolean' || !validTime(value.requested_at) || !validTime(value.next_allowed_at)) throw new Error('Invalid update status');
  return { phase: value.phase, canRequest: value.can_request, requestedAt: value.requested_at, nextAllowedAt: value.next_allowed_at };
}
function scheduleUpdateStatus() {
  clearTimeout(updateState.timer);
  if (state.phase === 'closed') return;
  const pending = ['queued', 'running', 'unknown'].includes(updateState.phase) || updateState.phase === 'succeeded' && !updatedDatasetObserved();
  updateState.timer = pending ? setTimeout(async () => {
    if (!document.hidden) {
      await readUpdateStatus();
      if (state.phase === 'closed') return;
      await refreshServer();
      if (state.phase === 'closed') return;
      renderUpdate();
    }
    scheduleUpdateStatus();
  }, 5000) : null;
}
async function readUpdateStatus() {
  if (updateState.request !== 'idle' || state.phase === 'closed') return;
  updateState.request = 'reading';
  try {
    const response = await fetch('./api/update', { cache: 'no-store', signal: AbortSignal.any([lifecycle.signal, AbortSignal.timeout(10000)]) });
    if (state.phase === 'closed') return;
    if (response.status === 404) updateState = { ...updateState, phase: 'unavailable', canRequest: false };
    else {
      const status = parseUpdate(await response.json());
      if (state.phase === 'closed') return;
      updateState = { ...updateState, ...status };
    }
  } catch {
    if (state.phase === 'closed') return;
    updateState = { ...updateState, phase: updateState.phase === 'unavailable' ? 'unavailable' : 'unknown', canRequest: false };
  } finally {
    updateState.request = 'idle';
    if (state.phase !== 'closed') { renderUpdate(); scheduleUpdateStatus(); }
  }
}
$('update-map').addEventListener('click', async () => {
  if (updateState.request !== 'idle') return;
  if (!updateState.canRequest && updateState.nextAllowedAt && Date.parse(updateState.nextAllowedAt) <= Date.now()) await readUpdateStatus();
  if (!updateState.canRequest) { showHint($('update-map'), '正在Riding中...'); return; }
  updateState.request = 'dispatching'; renderUpdate();
  try {
    const response = await fetch('./api/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal: AbortSignal.timeout(10000) });
    if (response.status === 403) {
      showHint($('update-map'), '更新请求被拒绝，请刷新页面后重试。');
      updateState = { ...updateState, phase: 'unavailable', canRequest: false };
    } else {
      updateState = { ...updateState, ...parseUpdate(await response.json()) };
      if (response.status === 429) showHint($('update-map'), '正在Riding中...');
      else if (response.status === 503) showHint($('update-map'), '更新服务暂不可用，请稍后重试。');
      else if (response.status === 502) showHint($('update-map'), '更新未能开始，请稍后重试。');
    }
  } catch { updateState = { ...updateState, phase: 'unknown', canRequest: false }; }
  finally { updateState.request = 'idle'; renderUpdate(); scheduleUpdateStatus(); }
});

const observer = new ResizeObserver(() => { if (state.phase !== 'closed') map.invalidateSize({ animate: false }); }); observer.observe($('map'));
window.addEventListener('pagehide', () => { state.phase = 'closed'; importVersion++; lifecycle.abort(); cancelAnimationFrame(datasetFrame); clearTimeout(datasetTimer); datasetResume?.(); datasetResume = null; clearPlaceCue(); clearInterval(refreshTimer); clearTimeout(updateState.timer); clearTimeout(hintTimer); observer.disconnect(); if (tiles) { map.removeLayer(tiles); tiles.off(); } routeLayer.remove(); map.remove(); }, { once: true });
let initial = await window.alongStartup.dataset;
delete window.alongStartup.dataset;
if (state.phase !== 'closed') {
  if (initial.kind === 'available') {
    if (await loadDataset(initial.text)) {
      const revision = initial.etag || await hashText(initial.text);
      if (state.phase !== 'closed') {
        serverRevision = revision;
        if (launch.get('basemap') === 'osm') { $('basemap').checked = true; updateBasemap(); }
      }
    }
  } else if (initial.kind === 'missing' || initial.kind === 'failed') {
    state.phase = initial.kind === 'missing' ? 'empty' : 'error';
    $('local-status').textContent = initial.kind === 'missing' ? '等待地图数据' : '地图服务暂不可用';
    for (const id of ['visible-stat', 'history-stat']) $(id).querySelector('strong').textContent = initial.kind === 'missing' ? '暂无数据' : '未能读取';
    $('empty').hidden = initial.kind !== 'missing';
    if (initial.kind === 'failed') showError(initial.message);
    renderUpdate();
  }
}
initial = null;
await readUpdateStatus();

async function refreshServer() {
  if (refreshBusy || document.hidden || ['loading', 'closed'].includes(state.phase)) return;
  refreshBusy = true;
  const requestVersion = importVersion;
  try {
    const head = await fetch('./dataset.json', { method: 'HEAD', cache: 'no-store', signal: lifecycle.signal });
    if (state.phase === 'closed') return;
    const revision = head.headers.get('ETag');
    if (!head.ok || (revision && revision === serverRevision)) return;
    const response = await fetch('./dataset.json', { cache: 'no-store', signal: lifecycle.signal });
    const text = await response.text();
    const nextRevision = response.headers.get('ETag') || await hashText(text);
    if (nextRevision === serverRevision) return;
    if (!response.ok || state.phase === 'loading' || requestVersion !== importVersion) return;
    const wasOnline = $('basemap').checked;
    const selection = { selected: state.selected, editing: state.editing, draft: $('place-label').value, datasetId: state.model?.datasetId };
    if (await loadDataset(text, false)) {
      if (state.model.datasetId === selection.datasetId && state.view.destinations.some(place => place.id === selection.selected)) {
        state.selected = selection.selected; state.editing = selection.editing; $('place-label').value = selection.draft; render();
      }
      serverRevision = nextRevision;
      if (wasOnline && state.model) { $('basemap').checked = true; updateBasemap(); }
      $('local-status').textContent = '数据已更新'; renderUpdate();
    }
  } catch { /* A temporary offline server leaves the visible map intact. */ }
  finally { refreshBusy = false; }
}
if (state.phase !== 'closed') refreshTimer = setInterval(refreshServer, 60000);
window.addEventListener('focus', refreshServer);
window.addEventListener('focus', readUpdateStatus);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { refreshServer(); readUpdateStatus(); } });
}
