export function createRouteLayer(map) {
  const Layer = L.Layer.extend({
    onAdd() {
      this.canvas = L.DomUtil.create('canvas', 'route-canvas');
      this.canvas.setAttribute('aria-hidden', 'true');
      map.getPanes().overlayPane.appendChild(this.canvas);
      this.schedule = () => { if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = null; this.draw(); }); };
      map.on('move zoom resize', this.schedule);
      this.schedule();
    },
    onRemove() { map.off('move zoom resize', this.schedule); cancelAnimationFrame(this.frame); this.canvas.remove(); },
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
      if (this.lightSurface) {
        for (const track of this.view.tracks) for (const path of track.paths) {
          const points = path.map(point => map.latLngToContainerPoint(point));
          ctx.strokeStyle = `rgba(8,42,46,${!this.selectedIds || this.selectedIds.has(track.id) ? .75 : .15})`; ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 4;
          ctx.beginPath(); points.forEach((p, index) => index ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
          if (points.length === 1) { ctx.arc(points[0].x, points[0].y, 2, 0, Math.PI * 2); ctx.fill(); } else ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = 'lighter';
      for (const track of this.view.tracks) {
        const selected = !this.selectedIds || this.selectedIds.has(track.id);
        for (const path of track.paths) {
          const points = path.map(point => map.latLngToContainerPoint(point));
          for (const [width, opacity] of [[7, .055], [2.2, .29]]) {
            ctx.strokeStyle = `rgba(43,188,198,${opacity * (selected ? 1 : .18)})`; ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = width;
            ctx.beginPath(); points.forEach((p, index) => index ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
            if (points.length === 1) { ctx.arc(points[0].x, points[0].y, width / 2, 0, Math.PI * 2); ctx.fill(); } else ctx.stroke();
          }
        }
      }
      ctx.globalCompositeOperation = 'source-over';
    }
  });
  return new Layer().addTo(map);
}
