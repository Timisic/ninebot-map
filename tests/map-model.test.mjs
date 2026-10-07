import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { readRideMap, stopDurations, mergeDestinations, mergePlaceGroups, renamePlace, segmentCells, clusterEndpoints, tilesAllowed, displayCoordinate } from '../web/model.mjs';
import { makeDataset } from './map-fixture.mjs';
const cells = result => [...result].sort();
test('grid traversal counts crossed interiors, exact corners, negative cells and duplicate points', () => {
  assert.deepEqual(cells(segmentCells([10, 10], [590, 10])), ['0,0', '1,0', '2,0']);
  assert.deepEqual(cells(segmentCells([0, 0], [400, 400])), ['0,0', '1,1', '2,2']);
  assert.deepEqual(cells(segmentCells([400, 400], [0, 0])), ['0,0', '1,1', '2,2']);
  assert.deepEqual(cells(segmentCells([-390, -10], [-10, -10])), ['-1,-1', '-2,-1']);
  assert.deepEqual(cells(segmentCells([0, 200], [0, 200])), ['0,1']);
  assert.deepEqual(cells(segmentCells([200, 10], [200, 590])), ['1,0', '1,1', '1,2']);
});
test('two rides count once each despite duplicates and loops; filtering fixes grid membership', () => {
  const data = makeDataset([{ id: 'a', xy: [[10, 10], [80, 10], [10, 10], [10, 10]], date: '2026-01-01' }, { id: 'b', xy: [[10, 10], [80, 10]], date: '2026-01-02' }]);
  const model = readRideMap(data);
  assert.deepEqual([...model.select().passages].sort(), [['-1,0', 2], ['0,0', 2]]);
  assert.deepEqual([...model.select({ from: '2026-01-02' }).passages].sort(), [['-1,0', 1], ['0,0', 1]]);
  assert.equal(model.select({ from: '2026-01-02' }).destinations[0].id, model.select().destinations[0].id);
  const reordered = structuredClone(data); reordered.rides.reverse(); reordered.tracks.reverse();
  assert.deepEqual(readRideMap(reordered).select().destinations, model.select().destinations);
  assert.equal(model.totals.ride_count, 2);
  assert.throws(() => model.select({ from: '2026-02-30' }), /日期/);
});
test('long gaps split drawing and leave all intervening cells uncounted', () => {
  const model = readRideMap(makeDataset([{ id: 'gap', xy: [[0, 0], [3000, 0]] }]));
  assert.equal(model.diagnostics.gaps, 1);
  assert.deepEqual(model.select().tracks[0].paths.map(p => p.length), [1, 1]);
  assert.deepEqual([...model.select().passages].sort(), [['-8,0', 1], ['7,0', 1]]);
});
test('fixed-density anchor clusters do not chain, identical endpoints count independently', () => {
  const endpoints = [0, 90, 180, 270, 360].map((x, i) => ({ id: String(i), xy: [x, 0], latlng: [0, x] }));
  assert.deepEqual(clusterEndpoints(endpoints).map(p => [p.id, p.memberIds]), [['1', ['0', '1', '2']], ['3', ['3', '4']]]);
  assert.deepEqual(clusterEndpoints(endpoints.reverse()).map(p => [p.id, p.memberIds]), [['1', ['0', '1', '2']], ['3', ['3', '4']]]);
  assert.deepEqual(clusterEndpoints([{ id: 'b', xy: [0, 0], latlng: [0, 0] }, { id: 'a', xy: [0, 0], latlng: [0, 0] }])[0].memberIds, ['a', 'b']);
});
test('timezone dates, inclusive filters, and unknown distance retain independent all-history totals', () => {
  const data = makeDataset([{ id: 'a', xy: [[0, 0], [10, 0]], date: '2026-01-01' }, { id: 'b', xy: [[0, 0], [10, 0]], date: '2026-01-02' }]);
  const model = readRideMap(data);
  assert.equal(model.select({ from: '2026-01-02', to: '2026-01-02' }).rideCount, 1);
  assert.equal(model.select({ from: '2026-02-01' }).rideCount, 0);
  assert.equal(model.totals.ride_count, 2);
  assert.throws(() => model.select({ from: '2026-03-01', to: '2026-02-01' }), /不能晚于/);
});
test('the public example and synthetic fixture have valid independent totals', () => {
  const example = readRideMap(fs.readFileSync(new URL('../examples/ride-dataset.json', import.meta.url), 'utf8'));
  assert.equal(example.totals.ride_count, 4); assert.equal(example.totals.total_distance_m, null); assert.equal(example.select().rideCount, 1);
  const synthetic = readRideMap(fs.readFileSync(new URL('./fixtures/synthetic-map.json', import.meta.url), 'utf8'));
  assert.deepEqual(synthetic.select().destinations.map(p => p.count), [6, 3, 2, 1]);
  assert.equal(synthetic.select().rideCount, 12);
});
test('external JSON, types, metadata, summary, references, dates, and coordinate guards fail clearly', () => {
  assert.throws(() => readRideMap('{bad'), /JSON/);
  const base = makeDataset([{ id: 'a', xy: [[0, 0], [10, 0]] }]);
  const invalid = [d => { d.format = 'other'; }, d => { d.rides.push(d.rides[0]); }, d => { d.tracks[0].ride_id = 'orphan'; }, d => { d.tracks = []; }, d => { d.tracks[0].points[0].latitude = 91; }, d => { d.rides[0].started_at = '2026-02-30T10:00:00Z'; }, d => { d.rides[0].distance_m = true; }, d => { d.summary.ride_count = 5; }, d => { d.months[0].listed_ride_count = 2; }, d => { d.provenance.snapshot_ids = false; }, d => { d.tracks[0].points[1].sequence = 4; }, d => { d.timezone = 'not/a/zone'; }, d => { d.selection.map_from = 'yesterday'; }, d => { d.tracks[0].points[1].longitude = 179; }];
  for (const mutate of invalid) { const input = structuredClone(base); mutate(input); assert.throws(() => readRideMap(input)); }
});
test('coordinate interpretation never silently enables tiles or mutates the dataset', () => {
  const data = makeDataset([{ id: 'a', xy: [[0, 0], [10, 0]] }]);
  assert.equal(tilesAllowed(readRideMap(data, 'unverified').interpretation), false);
  for (const crs of ['gcj02', 'bd09']) assert.equal(tilesAllowed(readRideMap(data, crs).interpretation), true);
  assert.equal(tilesAllowed(readRideMap(data, 'wgs84').interpretation), true);
  assert.equal(data.coordinate_system, 'unverified');
});

test('documented GCJ02 conversion is local and leaves input coordinates untouched', () => {
  const converted = displayCoordinate(123, 45, 'gcj02');
  assert.ok(Math.abs(converted[0] - 122.99395597) < 1e-7);
  assert.ok(Math.abs(converted[1] - 44.99804071) < 1e-7);
  const data = makeDataset([{id:'a',xy:[[0,0],[10,0]]}]);
  const before = JSON.stringify(data); readRideMap(data,'gcj02');
  assert.equal(JSON.stringify(data), before);
  assert.deepEqual(displayCoordinate(123,45,'wgs84'), [123,45]);
});

test('dense repeated destinations remain usable for multi-year commuting', () => {
  const data = makeDataset(Array.from({length:2500}, (_, i) => ({id:`commute-${i}`,xy:[[0,0],[10,0]]})));
  const view = readRideMap(data).select();
  assert.equal(view.rideCount, 2500);
  assert.deepEqual(view.destinations.map(p => p.count), [2500]);
  const jittered = Array.from({length:5000}, (_, i) => ({id:String(i),xy:[i%20,Math.floor(i/20)%20],latlng:[0,0]}));
  assert.deepEqual(clusterEndpoints(jittered).map(p => p.memberIds.length), [5000]);
});

test('a user label follows its historical member when the density anchor changes', async () => {
  const {resolvePlaceLabel} = await import('../web/model.mjs');
  const before = clusterEndpoints([{id:'a',xy:[0,0],latlng:[0,0]},{id:'b',xy:[90,0],latlng:[0,0]}]);
  const after = clusterEndpoints([{id:'a',xy:[0,0],latlng:[0,0]},{id:'b',xy:[90,0],latlng:[0,0]},{id:'c',xy:[180,0],latlng:[0,0]}]);
  assert.equal(before[0].id, 'a'); assert.equal(after[0].id, 'b');
  assert.equal(resolvePlaceLabel(after[0], {a:'示例工位'}), '示例工位');
  assert.equal(resolvePlaceLabel(after[0], {a:'示例工位',c:'另一地点'}), after[0].defaultLabel);
});


test('date filters preserve place labels while limiting counts and highlighted rides', async () => {
  const { resolvePlaceLabel } = await import('../web/model.mjs');
  const model = readRideMap(makeDataset([
    {id:'a',xy:[[0,0],[10,0]],date:'2026-01-01'},
    {id:'b',xy:[[0,0],[10,0]],date:'2026-01-02'},
  ]));
  const place = model.select({from:'2026-01-02'}).destinations[0];
  assert.equal(place.count, 1);
  assert.deepEqual(place.visibleMemberIds, ['b']);
  assert.deepEqual(place.memberIds, ['a','b']);
  assert.equal(resolvePlaceLabel(place, {a:'示例工位'}), '示例工位');
  const labels = {[place.id]:'新名称'};
  assert.equal(resolvePlaceLabel(place, labels), '新名称');
  assert.equal(resolvePlaceLabel(model.select().destinations[0], labels), '新名称');
});

test('public map keeps aggregates separate and rejects unreadable update timestamps and totals', () => {
  const local = makeDataset([{ id: 'one', xy: [[0, 0], [100, 0]] }]);
  const data = { format: 'public-ride-map', schema_version: 1, dataset_id: 'ninebot-public-map', updated_at: local.generated_at, timezone: local.timezone, coordinate_system: local.coordinate_system, summary: local.summary, tracks: [{ id: 'r_' + 'a'.repeat(24), date: '2026-01-01', distance_m: 1000, points: [[0, 0], [local.tracks[0].points[1].longitude, 0]] }] };
  assert.equal(readRideMap(data).select().rideCount, 1);
  assert.deepEqual(readRideMap(data).totals, local.summary);
  assert.throws(() => readRideMap({ ...data, updated_at: '2026-10-05 08:00:00+00:00' }), /时间/);
  assert.throws(() => readRideMap({ ...data, summary: { ...data.summary, total_distance_m: 0, known_distance_m: 0, missing_distance_count: 999 } }), /里程/);
});


test('parking duration matches shared exact-seconds cases without skipping rides', () => {
  const cases = JSON.parse(fs.readFileSync(new URL('./fixtures/stop-duration-cases.json', import.meta.url)));
  for (const { name, data, expected } of cases) {
    assert.deepEqual(Object.fromEntries(stopDurations(data)), expected, name);
    data.rides.reverse();
    assert.deepEqual(Object.fromEntries(stopDurations(data)), expected, `${name} reordered`);
  }
});

test('explicit merge groups preserve identity, distinct equal names and day unions before filtering', () => {
  const model = readRideMap(makeDataset([
    { id: 'a', xy: [[0, 0], [10, 0]], date: '2026-01-01' },
    { id: 'b', xy: [[0, 0], [300, 0]], date: '2026-01-01' },
    { id: 'c', xy: [[0, 0], [600, 0]], date: '2026-01-02' },
    { id: 'd', xy: [[0, 0], [900, 0]], date: '2026-01-02' },
  ]));
  const labels = { a: '球馆🏸', b: '球馆🏸', c: '球馆🏸', d: '地点 4' };
  assert.equal(model.select({ labels }).destinations.length, 4);
  assert.equal(model.select({ labels }).badmintonDays, 2);
  assert.equal(model.select({ labels }).destinations.find(p => p.id === 'd').named, true);
  const merges = [{ anchorId: 'b', memberIds: ['a', 'b'] }, { anchorId: 'c', memberIds: ['b', 'c'] }];
  const merged = model.select({ labels, merges });
  assert.equal(merged.destinations.length, 2);
  assert.equal(merged.destinations[0].id, 'c');
  assert.deepEqual(merged.destinations[0].memberIds, ['a', 'b', 'c']);
  assert.equal(merged.destinations[0].days, 2);
  assert.equal(merged.destinations[0].count, 3);
  const filtered = model.select({ labels, merges, from: '2026-01-02' });
  assert.deepEqual(filtered.destinations.find(p => p.id === 'c').visibleMemberIds, ['c']);
  assert.equal(filtered.badmintonDays, 1);
  assert.deepEqual(model.select({ merges }).destinations[0].memberIds, ['a', 'b', 'c']);
  assert.equal(model.select({ merges }).destinations[0].named, false);
  const reanchored = [{ id: 'new', anchor: [0, 0], memberIds: ['a', 'b', 'c', 'new'], defaultLabel: '地点 1' }];
  assert.equal(mergeDestinations(reanchored, merges)[0].id, 'c');
});

test('public nature totals preserve seconds, distinguish zero and missing, and reject invalid duration', () => {
  const local = makeDataset(Array.from({ length: 4 }, (_, i) => ({ id: String(i), xy: [[0, 0], [10, 0]] })));
  const publicData = { format: 'public-ride-map', schema_version: 1, dataset_id: 'ninebot-public-map', updated_at: local.generated_at, timezone: 'Asia/Shanghai', coordinate_system: local.coordinate_system, summary: local.summary,
    tracks: local.tracks.map((track, i) => ({ id: 'r_' + String(i).repeat(24), date: '2026-01-01', distance_m: 1000, points: track.points.map(p => [p.longitude, p.latitude]), ...i < 3 ? { stop_duration_s: [45, 45, 0][i] } : {} })) };
  const id = publicData.tracks[0].id;
  const place = readRideMap(publicData).select({ labels: { [id]: '奥森 南门' } }).destinations[0];
  assert.equal(place.activityKind, 'nature');
  assert.equal(place.stopDurationS, 90);
  assert.equal(place.knownStopCount, 3);
  assert.equal(place.unknownStopCount, 1);
  assert.equal(Math.floor(place.stopDurationS / 60), 1);
  for (const invalid of [-1, true, 86401, NaN, '30']) {
    const copy = structuredClone(publicData); copy.tracks[0].stop_duration_s = invalid;
    assert.throws(() => readRideMap(copy), /停留/);
  }
  for (const track of publicData.tracks) delete track.stop_duration_s;
  assert.equal(readRideMap(publicData).select({ labels: { [id]: '奥森南门' } }).destinations[0].stopDurationS, null);
});


test('a second merge retains temporarily absent historical members transitively', () => {
  const merges = mergePlaceGroups([{ anchorId: 'b', memberIds: ['a', 'b'] }, { anchorId: 'z', memberIds: ['z', 'a'] }],
    { id: 'b', memberIds: ['b'] }, { id: 'c', memberIds: ['c'] });
  assert.deepEqual(merges, [{ anchorId: 'c', memberIds: ['a', 'b', 'c', 'z'] }]);
  const restored = ['a', 'b', 'c', 'z'].map(id => ({ id, memberIds: [id], anchor: [0, 0], defaultLabel: id }));
  assert.deepEqual(mergeDestinations(restored, merges).map(place => place.memberIds), [['a', 'b', 'c', 'z']]);
});


test('renaming and clearing a partial merged place also update absent historical members', () => {
  const merges = [{ anchorId: 'b', memberIds: ['a', 'b'] }];
  const restored = readRideMap(makeDataset([
    { id: 'a', xy: [[0, 0], [10, 0]] }, { id: 'b', xy: [[0, 0], [300, 0]] },
  ]));
  const partial = { id: 'b', memberIds: ['b'] };
  const labels = renamePlace(partial, '新球馆🏸', { a: '旧球馆🏸', b: '旧球馆🏸' }, merges);
  const renamed = restored.select({ labels, merges });
  assert.equal(renamed.destinations.length, 1);
  assert.equal(renamed.destinations[0].label, '新球馆🏸');
  assert.equal(renamed.destinations[0].named, true);
  assert.equal(renamed.badmintonDays, 1);
  const cleared = restored.select({ labels: renamePlace(partial, '', labels, merges), merges });
  assert.equal(cleared.destinations.length, 1);
  assert.equal(cleared.destinations[0].named, false);
  assert.equal(cleared.badmintonDays, 0);
});
