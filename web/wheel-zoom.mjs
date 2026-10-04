export function installWheelZoom(map) {
  const state = { accumulated: 0, direction: 0, latched: false, timer: null, inputMode: null };
  let ownViewChange = false;
  function reset() {
    clearTimeout(state.timer);
    Object.assign(state, { accumulated: 0, direction: 0, latched: false, timer: null, inputMode: null });
  }
  function wheel(event) {
    event.preventDefault();
    event.stopPropagation();
    clearTimeout(state.timer);
    state.timer = setTimeout(reset, 100);
    if (state.latched) return;
    const delta = L.DomEvent.getWheelDelta(event), direction = Math.sign(delta);
    if (!direction) return;
    const inputMode = event.ctrlKey ? 'pinch' : 'wheel', threshold = event.ctrlKey ? 12 : 40;
    if (state.direction !== direction || state.inputMode !== inputMode) state.accumulated = 0;
    state.direction = direction; state.inputMode = inputMode;
    state.accumulated = Math.max(-threshold, Math.min(threshold, state.accumulated + delta));
    if (Math.abs(state.accumulated) < threshold) return;
    state.latched = true;
    ownViewChange = true;
    try {
      map.setZoomAround(map.mouseEventToContainerPoint(event), Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), map.getZoom() + direction)));
    } finally { ownViewChange = false; }
  }
  const externalViewChange = () => { if (!ownViewChange) reset(); };
  const container = map.getContainer();
  container.addEventListener('wheel', wheel, { passive: false });
  map.on('movestart zoomstart', externalViewChange);
  function destroy() {
    reset(); container.removeEventListener('wheel', wheel);
    map.off('movestart zoomstart', externalViewChange); map.off('unload', destroy);
  }
  map.on('unload', destroy);
  return destroy;
}
