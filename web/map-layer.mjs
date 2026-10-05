export function createBasemap(url, options) {
  const RetainedTiles = L.TileLayer.extend({
    getEvents() {
      const events = L.TileLayer.prototype.getEvents.call(this);
      // Leaflet setView resets every frame; native tile pruning retains loaded fallback levels.
      delete events.viewprereset;
      return events;
    }
  });
  return new RetainedTiles(url, options);
}

export function createRouteLayer(map) {
  const Layer = L.Layer.extend({
    onAdd() {
      this.canvas = L.DomUtil.create('canvas', 'route-canvas');
      this.canvas.setAttribute('aria-hidden', 'true');
      map.getPanes().overlayPane.appendChild(this.canvas);
      this.schedule = () => { if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = null; this.draw(); }); };
      this.zoom = () => { cancelAnimationFrame(this.frame); this.frame = null; this.draw(); };
      map.on('move resize', this.schedule);
      map.on('zoom', this.zoom);
      this.schedule();
    },
    onRemove() { map.off('move resize', this.schedule); map.off('zoom', this.zoom); cancelAnimationFrame(this.frame); this.canvas.remove(); },
    setView(model, view, grid, selectedIds, lightSurface = false) { this.model = model; this.view = view; this.grid = grid; this.selectedIds = selectedIds; this.lightSurface = lightSurface; this.schedule(); },
    draw() {
      const size = map.getSize(), ratio = Math.min(devicePixelRatio || 1, 2);
      this.canvas.width = size.x * ratio; this.canvas.height = size.y * ratio;
      this.canvas.style.width = `${size.x}px`; this.canvas.style.height = `${size.y}px`;
      L.DomUtil.setPosition(this.canvas, map.containerPointToLayerPoint([0, 0]));
      const ctx = this.canvas.getContext('2d'); ctx.scale(ratio, ratio);
      if (!this.view) return;
      if (this.grid) {
        let max = 1;
        for (const count of this.view.passages.values()) max = Math.max(max, count);
        for (const [key, count] of this.view.passages) {
          const [southwest, northeast] = this.model.cellBounds(key).map(p => map.latLngToContainerPoint(p));
          const x = southwest.x, y = northeast.y, w = northeast.x - southwest.x, h = southwest.y - northeast.y;
          if (x > size.x || x + w < 0 || y > size.y || y + h < 0) continue;
          ctx.fillStyle = `rgba(58,181,175,${.035 + .19 * count / max})`; ctx.fillRect(x, y, w, h);
          ctx.strokeStyle = this.lightSurface ? 'rgba(23,96,88,.3)' : 'rgba(117,193,187,.15)'; ctx.lineWidth = .6; ctx.strokeRect(x, y, w, h);
        }
      }
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      const paths = this.view.tracks.flatMap(track => track.paths.map(path => ({
        points: path.map(point => map.latLngToContainerPoint(point)),
        selected: !this.selectedIds || this.selectedIds.has(track.id)
      })));
      const width = Math.max(1.8, Math.min(2.8, 2.2 + (map.getZoom() - 13) * .12));
      function stroke(points, color, lineWidth, alpha) {
        ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = lineWidth;
        ctx.beginPath(); points.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
        if (points.length === 1) { ctx.arc(points[0].x, points[0].y, lineWidth / 2, 0, Math.PI * 2); ctx.fill(); }
        else ctx.stroke();
      }
      for (const { points, selected } of paths) stroke(points, this.lightSurface ? '#ffffff' : '#0e2429', width + 1.8, selected ? .9 : .25);
      for (const { points, selected } of paths) stroke(points, this.lightSurface ? '#167e87' : '#36b9bf', width, selected ? 1 : .3);
      ctx.globalCompositeOperation = this.lightSurface ? 'source-over' : 'lighter';
      for (const { points, selected } of paths) stroke(points, this.lightSurface ? '#053d48' : '#53b9bb', width, selected ? .16 : .025);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
    }
  });
  return new Layer().addTo(map);
}
