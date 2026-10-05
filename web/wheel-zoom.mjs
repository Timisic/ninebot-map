export function installWheelZoom(map) {
  const state = { targetZoom: null, anchorLatLng: null, anchorPoint: null, frame: null, previousTime: null, direction: 0, inputMode: null };
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let ownViewChange = false;
  function reset() {
    cancelAnimationFrame(state.frame);
    Object.assign(state, { targetZoom: null, anchorLatLng: null, anchorPoint: null, frame: null, previousTime: null, direction: 0, inputMode: null });
  }
  function apply(zoom) {
    const center = map.project(state.anchorLatLng, zoom).subtract(state.anchorPoint).add(map.getSize().divideBy(2));
    ownViewChange = true;
    try { map.setView(map.unproject(center, zoom), zoom, { animate: false }); }
    finally { ownViewChange = false; }
  }
  function step(time) {
    state.frame = null;
    const elapsed = state.previousTime === null ? 16 : Math.min(64, time - state.previousTime);
    state.previousTime = time;
    const remaining = state.targetZoom - map.getZoom();
    if (Math.abs(remaining) < .0001) { apply(state.targetZoom); reset(); return; }
    apply(map.getZoom() + remaining * (1 - Math.exp(-elapsed / 55)));
    state.frame = requestAnimationFrame(step);
  }
  function wheel(event) {
    event.preventDefault();
    event.stopPropagation();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? map.getSize().y : 1;
    const delta = Math.max(-.75, Math.min(.75, -event.deltaY * unit / (event.ctrlKey ? 60 : 240)));
    if (!Number.isFinite(delta) || !delta) return;
    const direction = Math.sign(delta), inputMode = event.ctrlKey ? 'pinch' : 'wheel';
    const point = map.mouseEventToContainerPoint(event);
    if (state.targetZoom === null || direction !== state.direction || inputMode !== state.inputMode || point.distanceTo(state.anchorPoint) > 1) {
      reset();
      state.targetZoom = map.getZoom();
      state.anchorPoint = point;
      state.anchorLatLng = map.containerPointToLatLng(point);
    }
    state.direction = direction; state.inputMode = inputMode;
    state.targetZoom = Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), state.targetZoom + delta));
    if (reducedMotion.matches) { apply(state.targetZoom); reset(); }
    else if (state.frame === null) state.frame = requestAnimationFrame(step);
  }
  const externalViewChange = () => { if (!ownViewChange) reset(); };
  const container = map.getContainer();
  container.addEventListener('wheel', wheel, { passive: false });
  map.on('movestart zoomstart dragstart resize zoomlevelschange', externalViewChange);
  reducedMotion.addEventListener('change', reset);
  function destroy() {
    reset(); container.removeEventListener('wheel', wheel);
    map.off('movestart zoomstart dragstart resize zoomlevelschange', externalViewChange);
    reducedMotion.removeEventListener('change', reset);
    map.off('unload', destroy);
  }
  map.on('unload', destroy);
  return destroy;
}
