import gcoord from './vendor/gcoord/gcoord.mjs';
export const LIMITS = Object.freeze({ bytes: 40 * 1024 * 1024, points: 300000, rides: 25000, cells: 1500000, neighbours: 4000000 });
export const GRID_METERS = 200;
export const GAP_METERS = 1000;
export const DESTINATION_METERS = 100;
const METERS_PER_DEGREE = 6371008.8 * Math.PI / 180;
const fail = message => { throw new Error(message); };
const assert = (condition, message) => { if (!condition) fail(message); };
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const number = (value, nullable = false) => (nullable && value === null) || (typeof value === 'number' && Number.isFinite(value) && value >= 0);
const integer = value => Number.isSafeInteger(value) && value >= 0;
const month = value => typeof value === 'string' && /^20\d{2}(0[1-9]|1[0-2])$/.test(value);
const round = n => Math.round(n * 1e6) / 1e6;
const sumKnown = values => round(values.reduce((total, value) => total + (value ?? 0), 0));
const sum = values => values.includes(null) ? null : sumKnown(values);
function timestamp(value) {
  assert(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(value), '时间必须带时区，使用完整 ISO 8601 格式');
  const [year, month, day] = value.slice(0, 10).split('-').map(Number);
  assert(month >= 1 && month <= 12 && day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate() && Number.isFinite(Date.parse(value)), '无效日期');
  const clock = value.slice(11, 19).split(':').map(Number);
  assert(clock[0] < 24 && clock[1] < 60 && clock[2] < 60, '无效时间');
  return Date.parse(value);
}
function same(actual, expected) {
  if (object(expected)) return object(actual) && Object.keys(actual).length === Object.keys(expected).length && Object.keys(expected).every(key => same(actual[key], expected[key]));
  return actual === expected;
}
function validate(data) {
  assert(object(data) && data.format === 'ride-dataset' && data.schema_version === 1, '请选择 Ride Dataset v1 JSON 数据集');
  assert(typeof data.dataset_id === 'string' && data.dataset_id.length > 0 && data.dataset_id.length <= 500, '数据集标识无效');
  timestamp(data.generated_at);
  assert(typeof data.timezone === 'string', '缺少 IANA 时区');
  try { new Intl.DateTimeFormat('en', { timeZone: data.timezone }).format(); } catch { fail('无效的 IANA 时区'); }
  assert(['unverified', 'wgs84', 'gcj02', 'bd09'].includes(data.coordinate_system), '未知坐标系声明');
  const selection = data.selection;
  assert(object(selection) && selection.statistics_scope === 'all_rides' && selection.map_rule === 'ride_start_at_or_after' && Array.isArray(selection.allowed_track_kinds) && selection.allowed_track_kinds.length === 1 && selection.allowed_track_kinds[0] === 'sampled', '不支持的地图范围约定');
  const since = selection.map_from === null ? null : timestamp(selection.map_from);
  assert(object(data.provenance) && typeof data.provenance.source === 'string' && Array.isArray(data.provenance.snapshot_ids), '缺少来源说明');
  for (const source of data.provenance.snapshot_ids) assert(object(source) && month(source.month) && typeof source.snapshot_id === 'string', '来源快照标识无效');
  for (const key of ['rides', 'tracks', 'months']) assert(Array.isArray(data[key]), `${key} 必须是数组`);
  assert(data.months.length <= 1200, '月份超过 1,200 条上限');
  assert(data.rides.length <= LIMITS.rides, '超过 25,000 条行程上限，请缩小数据集');
  const rides = new Map();
  for (const ride of data.rides) {
    assert(object(ride) && typeof ride.id === 'string' && ride.id.length > 0 && !rides.has(ride.id), '行程标识为空或重复');
    assert(month(ride.source_month), '行程月份无效');
    const start = ride.started_at === null ? null : timestamp(ride.started_at);
    const end = ride.ended_at === null ? null : timestamp(ride.ended_at);
    assert(start === null || end === null || end >= start, '行程结束早于开始');
    for (const key of ['distance_m', 'duration_s', 'energy_wh']) assert(number(ride[key], true), '行程数值必须为非负有限数或 null');
    assert(integer(ride.source_point_count) && ['sampled', 'simplified', 'single_point', 'missing'].includes(ride.track_kind), '行程点数或质量无效');
    const expected = start === null ? 'unknown_start_time' : since !== null && start < since ? 'before_map_start' : ride.track_kind === 'simplified' ? 'simplified' : ride.track_kind !== 'sampled' || ride.source_point_count < 2 ? 'insufficient_points' : 'included';
    assert(ride.map_status === expected, '地图状态与日期或轨迹质量不一致');
    rides.set(ride.id, ride);
  }
  const trackIds = new Set();
  let pointCount = 0;
  for (const track of data.tracks) {
    assert(object(track) && rides.has(track.ride_id) && !trackIds.has(track.ride_id) && rides.get(track.ride_id).map_status === 'included', '地图轨迹重复、无对应行程或超出范围');
    assert(Array.isArray(track.points) && track.points.length >= 2 && track.points.length === rides.get(track.ride_id).source_point_count, '轨迹点数与行程不一致');
    pointCount += track.points.length;
    assert(pointCount <= LIMITS.points, '超过 300,000 个轨迹点上限，请缩小地图范围');
    for (const [index, point] of track.points.entries()) {
      assert(object(point) && point.sequence === index, '轨迹顺序必须从 0 连续编号');
      assert(typeof point.longitude === 'number' && Number.isFinite(point.longitude) && Math.abs(point.longitude) <= 180 && typeof point.latitude === 'number' && Number.isFinite(point.latitude) && Math.abs(point.latitude) <= 90, '无效经纬度');
      if (point.recorded_at !== null) timestamp(point.recorded_at);
      assert(number(point.speed_mps, true), '速度必须为非负有限数或 null');
    }
    trackIds.add(track.ride_id);
  }
  assert([...rides.values()].filter(r => r.map_status === 'included').length === trackIds.size, '缺少应导出的地图轨迹');
  const months = new Set();
  for (const row of data.months) {
    assert(object(row) && month(row.month) && !months.has(row.month), '月份无效或重复');
    assert((row.reported_ride_count === null || integer(row.reported_ride_count)) && integer(row.listed_ride_count), '月份计数无效');
    assert(number(row.reported_distance_m, true) && number(row.listed_distance_m, true) && [null, true, false].includes(row.list_complete), '月份统计无效');
    const items = data.rides.filter(r => r.source_month === row.month);
    assert(row.listed_ride_count === items.length && row.listed_distance_m === sum(items.map(r => r.distance_m)), '月份统计与行程不一致');
    assert(row.list_complete !== true || row.reported_ride_count === row.listed_ride_count, '月份完整性声明不一致');
    months.add(row.month);
  }
  assert(data.rides.every(r => months.has(r.source_month)), '行程缺少对应月份');
  const selected = data.rides.filter(r => r.map_status === 'included');
  const exclusions = {};
  for (const ride of data.rides) if (ride.map_status !== 'included') exclusions[ride.map_status] = (exclusions[ride.map_status] || 0) + 1;
  const computed = { ride_count: rides.size, total_distance_m: sum(data.rides.map(r => r.distance_m)), known_distance_m: sumKnown(data.rides.map(r => r.distance_m)), missing_distance_count: data.rides.filter(r => r.distance_m === null).length, reported_month_distance_m: sum(data.months.map(m => m.reported_distance_m)), map_ride_count: selected.length, map_distance_m: sum(selected.map(r => r.distance_m)), map_point_count: pointCount, map_exclusions: exclusions };
  assert(same(data.summary, computed), '汇总与数据内容不一致');
  return computed;
}

function validatePublic(data) {
  assert(data.schema_version === 1 && data.dataset_id === 'ninebot-public-map', '公开地图格式无效');
  timestamp(data.updated_at);
  assert(typeof data.timezone === 'string', '缺少 IANA 时区');
  try { new Intl.DateTimeFormat('en', { timeZone: data.timezone }).format(); } catch { fail('无效的 IANA 时区'); }
  assert(['unverified', 'wgs84', 'gcj02', 'bd09'].includes(data.coordinate_system), '未知坐标系声明');
  assert(Array.isArray(data.tracks) && data.tracks.length <= LIMITS.rides, '公开轨迹超限');
  const ids = new Set(); let points = 0;
  for (const track of data.tracks) {
    assert(object(track) && /^r_[a-f0-9]{24}$/.test(track.id) && !ids.has(track.id), '公开轨迹标识无效');
    ids.add(track.id);
    assert(typeof track.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(track.date), '公开轨迹日期无效');
    timestamp(`${track.date}T00:00:00Z`);
    assert(number(track.distance_m, true), '公开轨迹里程无效');
    assert(!Object.hasOwn(track, 'stop_duration_s') || (number(track.stop_duration_s, true) && (track.stop_duration_s === null || track.stop_duration_s <= 86400)), '公开停留时长无效');
    assert(Array.isArray(track.points) && track.points.length >= 2, '公开轨迹点无效');
    points += track.points.length;
    assert(points <= LIMITS.points, '公开轨迹点超限');
    for (const point of track.points) assert(Array.isArray(point) && point.length === 2 && point.every(Number.isFinite) && Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90, '无效经纬度');
  }
  const summary = data.summary;
  assert(object(summary), '缺少公开汇总');
  for (const key of ['ride_count', 'map_ride_count', 'map_point_count', 'missing_distance_count']) assert(integer(summary[key]), '公开计数无效');
  for (const key of ['total_distance_m', 'known_distance_m', 'reported_month_distance_m', 'map_distance_m']) assert(number(summary[key], true), '公开里程无效');
  assert(object(summary.map_exclusions) && Object.entries(summary.map_exclusions).every(([key, value]) => ['before_map_start', 'unknown_start_time', 'simplified', 'insufficient_points'].includes(key) && integer(value)), '公开排除计数无效');
  assert(summary.map_ride_count === ids.size && summary.map_point_count === points && summary.map_distance_m === sum(data.tracks.map(track => track.distance_m)), '公开轨迹与汇总不一致');
  assert(summary.ride_count === ids.size + Object.values(summary.map_exclusions).reduce((a, b) => a + b, 0), '公开历史与范围不一致');
  const missing = data.tracks.filter(track => track.distance_m === null).length;
  const known = sumKnown(data.tracks.map(track => track.distance_m));
  const excluded = summary.ride_count - ids.size;
  assert(summary.missing_distance_count >= missing && summary.missing_distance_count <= missing + excluded, '公开缺失里程计数不一致');
  assert(number(summary.known_distance_m) && summary.known_distance_m >= known && (excluded !== 0 || summary.known_distance_m === known), '公开已知里程不一致');
  assert(summary.missing_distance_count > 0 ? summary.total_distance_m === null : summary.total_distance_m === summary.known_distance_m, '公开总里程与缺失状态不一致');
  return summary;
}

// Half-open cells own their lower/left boundaries; corner crossings add no side cells.
export function segmentCells(a, b, size = GRID_METERS) {
  const cuts = [0, 1];
  for (const axis of [0, 1]) {
    const delta = b[axis] - a[axis];
    if (delta === 0) continue;
    const low = Math.floor(Math.min(a[axis], b[axis]) / size) + 1;
    const high = Math.floor(Math.max(a[axis], b[axis]) / size);
    assert(high - low < 100, '线段跨越网格过多');
    for (let boundary = low; boundary <= high; boundary++) {
      const t = (boundary * size - a[axis]) / delta;
      if (t > 0 && t < 1) cuts.push(t);
    }
  }
  cuts.sort((x, y) => x - y);
  const result = new Set();
  const add = t => result.add(`${Math.floor((a[0] + (b[0] - a[0]) * t) / size)},${Math.floor((a[1] + (b[1] - a[1]) * t) / size)}`);
  add(0); add(1);
  for (let i = 1; i < cuts.length; i++) if (cuts[i] - cuts[i - 1] > 1e-12) add((cuts[i] + cuts[i - 1]) / 2);
  return result;
}

export function clusterEndpoints(endpoints, radius = DESTINATION_METERS) {
  const items = endpoints.slice().sort((a, b) => a.id.localeCompare(b.id, 'en'));
  const buckets = new Map(), size = radius / 4, squared = radius * radius;
  const key = (x, y) => `${x},${y}`;
  for (const point of items) {
    const k = key(Math.floor(point.xy[0] / size), Math.floor(point.xy[1] / size));
    if (!buckets.has(k)) buckets.set(k, { items: [], minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity });
    const bucket = buckets.get(k); bucket.items.push(point);
    bucket.minX = Math.min(bucket.minX, point.xy[0]); bucket.maxX = Math.max(bucket.maxX, point.xy[0]);
    bucket.minY = Math.min(bucket.minY, point.xy[1]); bucket.maxY = Math.max(bucket.maxY, point.xy[1]);
  }
  let operations = 0;
  function scan(point, collect = false) {
    const [x, y] = point.xy, result = [];
    let count = 0;
    for (let bx = Math.floor((x - radius) / size); bx <= Math.floor((x + radius) / size); bx++) {
      for (let by = Math.floor((y - radius) / size); by <= Math.floor((y + radius) / size); by++) {
        const bucket = buckets.get(key(bx, by)); if (!bucket) continue;
        assert(++operations <= LIMITS.neighbours, '终点分布超出安全计算上限，请缩小数据集');
        const dx = Math.max(bucket.minX - x, 0, x - bucket.maxX), dy = Math.max(bucket.minY - y, 0, y - bucket.maxY);
        if (dx * dx + dy * dy > squared) continue;
        const farX = Math.max(Math.abs(x - bucket.minX), Math.abs(x - bucket.maxX));
        const farY = Math.max(Math.abs(y - bucket.minY), Math.abs(y - bucket.maxY));
        if (farX * farX + farY * farY <= squared) {
          count += bucket.items.length;
          if (collect) for (const other of bucket.items) result.push(other);
          continue;
        }
        for (const other of bucket.items) {
          assert(++operations <= LIMITS.neighbours, '终点分布超出安全计算上限，请缩小数据集');
          if (Math.hypot(x - other.xy[0], y - other.xy[1]) <= radius) { count++; if (collect) result.push(other); }
        }
      }
    }
    return collect ? result : count;
  }
  const density = new Map(), coordinateDensity = new Map();
  for (const point of items) {
    const k = key(...point.xy);
    if (!coordinateDensity.has(k)) coordinateDensity.set(k, scan(point));
    density.set(point.id, coordinateDensity.get(k));
  }
  items.sort((a, b) => density.get(b.id) - density.get(a.id) || a.id.localeCompare(b.id, 'en'));
  const assigned = new Set(), clusters = [];
  for (const anchor of items) {
    if (assigned.has(anchor.id)) continue;
    const members = scan(anchor, true).filter(p => !assigned.has(p.id));
    for (const point of members) assigned.add(point.id);
    clusters.push(Object.freeze({ id: anchor.id, anchor: Object.freeze(anchor.latlng.slice()), memberIds: Object.freeze(members.map(p => p.id).sort()) }));
  }
  return Object.freeze(clusters.sort((a, b) => b.memberIds.length - a.memberIds.length || a.id.localeCompare(b.id, 'en')).map((c, index) => Object.freeze({ ...c, defaultLabel: `地点 ${index + 1}` })));
}

function customPlaceLabel(place, labels) {
  const names = new Set(place.memberIds.filter(id => Object.hasOwn(labels, id)).map(id => labels[id]).filter(value => typeof value === 'string' && value.length));
  return names.size === 1 ? [...names][0] : null;
}
export function resolvePlaceLabel(place, labels) { return customPlaceLabel(place, labels) ?? place.defaultLabel; }

function mergedMemberIds(merges, memberIds) {
  const members = new Set(memberIds);
  let changed = true;
  while (changed) {
    changed = false;
    for (const group of merges) {
      if (!group.memberIds.some(id => members.has(id))) continue;
      for (const id of group.memberIds) if (!members.has(id)) { members.add(id); changed = true; }
    }
  }
  return [...members].sort();
}

export function mergePlaceGroups(merges, source, target) {
  const memberIds = mergedMemberIds(merges, [...source.memberIds, ...target.memberIds]);
  const members = new Set(memberIds);
  return [...merges.filter(group => !group.memberIds.some(id => members.has(id))), { anchorId: target.id, memberIds }];
}

export function renamePlace(place, label, labels, merges) {
  const renamed = { ...labels };
  for (const id of mergedMemberIds(merges, place.memberIds)) {
    delete renamed[id];
    if (label) Object.defineProperty(renamed, id, { value: label, enumerable: true, writable: true, configurable: true });
  }
  return renamed;
}

export function mergeDestinations(destinations, merges = []) {
  const byId = new Map(destinations.map(place => [place.id, place]));
  const parent = new Map(destinations.map(place => [place.id, place.id]));
  const byMember = new Map(destinations.flatMap(place => place.memberIds.map(id => [id, place.id])));
  const root = id => { while (parent.get(id) !== id) id = parent.get(id); return id; };
  for (const merge of merges) {
    const ids = [...new Set(merge.memberIds.map(id => byMember.get(id)).filter(Boolean))];
    const target = byMember.get(merge.anchorId) || ids[0];
    if (!target) continue;
    const anchor = root(target);
    for (const id of ids) parent.set(root(id), anchor);
  }
  const groups = new Map();
  for (const place of destinations) {
    const id = root(place.id);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(place);
  }
  return [...groups].map(([id, places]) => {
    const savedAnchor = merges.findLast(merge => byMember.has(merge.anchorId) && root(byMember.get(merge.anchorId)) === id)?.anchorId;
    return { ...byId.get(id), id: savedAnchor ?? id, memberIds: places.flatMap(place => place.memberIds).sort() };
  });
}

export function stopDurations(data) {
  const result = new Map(data.rides.map(ride => [ride.id, null]));
  const monthsWithIncompleteChronology = new Set(data.months.filter(month => month.list_complete !== true).map(month => month.month));
  for (const month of data.rides.filter(ride => ride.started_at === null).map(ride => ride.source_month)) monthsWithIncompleteChronology.add(month);
  const tracks = new Map(data.tracks.map(track => [track.ride_id, track.points]));
  const rides = data.rides.filter(ride => ride.started_at !== null).slice().sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.id.localeCompare(b.id, 'en'));
  let previousEnd = -Infinity;
  for (let i = 0; i < rides.length - 1; i++) {
    if (i > 0 && rides[i - 1].ended_at) previousEnd = Math.max(previousEnd, Date.parse(rides[i - 1].ended_at));
    const arrival = rides[i], departure = rides[i + 1];
    const arrivingPoints = tracks.get(arrival.id), leavingPoints = tracks.get(departure.id);
    if (!arrival.ended_at || !arrivingPoints || !leavingPoints) continue;
    if (Date.parse(arrival.started_at) < previousEnd || Date.parse(arrival.started_at) === Date.parse(departure.started_at)) continue;
    if (monthsWithIncompleteChronology.has(arrival.source_month) || monthsWithIncompleteChronology.has(departure.source_month)) continue;
    const seconds = (Date.parse(departure.started_at) - Date.parse(arrival.ended_at)) / 1000;
    if (seconds < 0 || seconds > 86400) continue;
    const a = arrivingPoints.at(-1), b = leavingPoints[0];
    const latitude = (a.latitude + b.latitude) * Math.PI / 360;
    const distance = Math.hypot((a.longitude - b.longitude) * Math.cos(latitude), a.latitude - b.latitude) * METERS_PER_DEGREE;
    if (distance <= DESTINATION_METERS) result.set(arrival.id, seconds);
  }
  return result;
}

export function tilesAllowed(interpretation) { return ['wgs84', 'gcj02', 'bd09'].includes(interpretation); }

export function displayCoordinate(longitude, latitude, interpretation) {
  const source = [longitude, latitude];
  if (interpretation === 'gcj02') return gcoord.transform(source, gcoord.GCJ02, gcoord.WGS84);
  if (interpretation === 'bd09') return gcoord.transform(source, gcoord.BD09, gcoord.WGS84);
  return source;
}

export function readRideMap(input, interpretation) {
  let data;
  if (typeof input === 'string') {
    assert(new TextEncoder().encode(input).length <= LIMITS.bytes, '文件超过 40 MB 上限');
    try { data = JSON.parse(input); } catch { fail('JSON 格式无效，请选择完整数据集'); }
  } else data = input;
  const publicMap = object(data) && data.format === 'public-ride-map';
  const totals = Object.freeze(publicMap ? validatePublic(data) : validate(data));
  const sourceTracks = publicMap ? data.tracks.map(track => ({ ride_id: track.id, points: track.points.map(([longitude, latitude]) => ({ longitude, latitude })) })) : data.tracks;
  const crs = interpretation ?? data.coordinate_system;
  assert(['unverified', 'wgs84', 'gcj02', 'bd09'].includes(crs), '未知坐标解释');
  const displayTracks = sourceTracks.map(track => ({ ...track, points: track.points.map(point => {
    const [longitude, latitude] = displayCoordinate(point.longitude, point.latitude, crs);
    return { ...point, longitude, latitude };
  }) }));
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const track of displayTracks) for (const point of track.points) {
    minLon = Math.min(minLon, point.longitude); maxLon = Math.max(maxLon, point.longitude);
    minLat = Math.min(minLat, point.latitude); maxLat = Math.max(maxLat, point.latitude);
  }
  if (sourceTracks.length) assert(maxLon - minLon <= 3 && maxLat - minLat <= 3 && Math.max(Math.abs(minLat), Math.abs(maxLat)) <= 75, '此本地网格仅支持经纬跨度各不超过 3°、纬度 ±75° 内的区域；请拆分跨区域或跨日期变更线数据');
  const origin = sourceTracks.length ? [(minLon + maxLon) / 2, (minLat + maxLat) / 2] : [0, 0];
  const xScale = METERS_PER_DEGREE * Math.cos(origin[1] * Math.PI / 180);
  const project = point => [(point.longitude - origin[0]) * xScale, (point.latitude - origin[1]) * METERS_PER_DEGREE];
  const unproject = (x, y) => [origin[1] + y / METERS_PER_DEGREE, origin[0] + x / xScale];
  const dateFormatter = new Intl.DateTimeFormat('en-CA', { timeZone: data.timezone, year: 'numeric', month: '2-digit', day: '2-digit' });
  const dateFor = value => {
    if (value === null) return null;
    const parts = Object.fromEntries(dateFormatter.formatToParts(new Date(value)).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const stops = publicMap ? new Map(data.tracks.map(track => [track.id, track.stop_duration_s ?? null])) : stopDurations(data);
  const ridesById = new Map((publicMap ? data.tracks : data.rides).map(ride => [ride.id, Object.freeze({ id: ride.id, distance: ride.distance_m, date: publicMap ? ride.date : dateFor(ride.started_at), stopDurationS: stops.get(ride.id) })]));
  const tracks = [], endpoints = [];
  let gaps = 0, expansion = 0;
  for (const track of displayTracks.slice().sort((a, b) => a.ride_id.localeCompare(b.ride_id, 'en'))) {
    const paths = [], cells = new Set();
    let path = [];
    for (const [index, point] of track.points.entries()) {
      const xy = project(point), latlng = Object.freeze([point.latitude, point.longitude]);
      if (index > 0) {
        const previous = project(track.points[index - 1]);
        if (Math.hypot(xy[0] - previous[0], xy[1] - previous[1]) > GAP_METERS) {
          paths.push(Object.freeze(path)); path = []; gaps++;
        } else for (const cell of segmentCells(previous, xy)) cells.add(cell);
      }
      cells.add(`${Math.floor(xy[0] / GRID_METERS)},${Math.floor(xy[1] / GRID_METERS)}`);
      path.push(latlng);
    }
    paths.push(Object.freeze(path));
    expansion += cells.size;
    assert(expansion <= LIMITS.cells, '经过区域过多，请缩小地图范围');
    tracks.push(Object.freeze({ id: track.ride_id, paths: Object.freeze(paths), cells: Object.freeze([...cells]), ...ridesById.get(track.ride_id) }));
    const last = track.points.at(-1);
    endpoints.push({ id: track.ride_id, xy: project(last), latlng: [last.latitude, last.longitude] });
  }
  const destinations = clusterEndpoints(endpoints);
  const dates = tracks.map(t => t.date).sort();
  const select = ({ from = '', to = '', labels = {}, merges = [] } = {}) => {
    assert(!from || /^\d{4}-\d{2}-\d{2}$/.test(from), '开始日期无效');
    assert(!to || /^\d{4}-\d{2}-\d{2}$/.test(to), '结束日期无效');
    if (from) timestamp(`${from}T00:00:00Z`);
    if (to) timestamp(`${to}T00:00:00Z`);
    assert(!from || !to || from <= to, '开始日期不能晚于结束日期');
    const visible = tracks.filter(t => (!from || t.date >= from) && (!to || t.date <= to));
    const ids = new Set(visible.map(t => t.id)), passages = new Map();
    for (const track of visible) for (const cell of track.cells) passages.set(cell, (passages.get(cell) || 0) + 1);
    const badmintonDays = new Set();
    const places = mergeDestinations(destinations, merges).map(place => {
      const memberIds = place.memberIds.filter(id => ids.has(id));
      const days = new Set(memberIds.map(id => ridesById.get(id).date));
      const label = customPlaceLabel(place, labels), named = label !== null;
      const activityKind = label?.includes('🏸') ? 'badminton' : label?.replace(/\s/g, '').includes('奥森南门') ? 'nature' : null;
      if (activityKind === 'badminton') for (const day of days) badmintonDays.add(day);
      const stops = memberIds.map(id => ridesById.get(id).stopDurationS);
      const knownStopCount = stops.filter(seconds => seconds !== null).length;
      return { ...place, label: label ?? place.defaultLabel, named, activityKind, visibleMemberIds: memberIds, count: memberIds.length, days: days.size, stopDurationS: knownStopCount ? sumKnown(stops) : null, knownStopCount, unknownStopCount: memberIds.length - knownStopCount };
    }).filter(p => p.count).sort((a, b) => b.count - a.count || a.id.localeCompare(b.id, 'en'));
    return { tracks: visible, passages, destinations: places, badmintonDays: badmintonDays.size, rideCount: visible.length, distance: sum(visible.map(t => t.distance)) };
  };
  return Object.freeze({ datasetId: data.dataset_id, updatedAt: data.updated_at || data.generated_at, declaredCrs: data.coordinate_system, interpretation: crs, timezone: data.timezone, totals, diagnostics: Object.freeze({ gaps, excluded: totals.ride_count - tracks.length }), dateBounds: Object.freeze([dates[0] || '', dates.at(-1) || '']), destinations, select, cellAt(latitude, longitude) { const xy = project({ latitude, longitude }); return `${Math.floor(xy[0] / GRID_METERS)},${Math.floor(xy[1] / GRID_METERS)}`; }, cellBounds(key) { const [x, y] = key.split(',').map(Number); return [unproject(x * GRID_METERS, y * GRID_METERS), unproject((x + 1) * GRID_METERS, (y + 1) * GRID_METERS)]; } });
}
