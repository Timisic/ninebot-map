(() => {
  let preference = 'system';
  try {
    const saved = localStorage.getItem('ride-map-theme');
    if (saved === 'light' || saved === 'dark') preference = saved;
  } catch {}
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.dataset.theme = preference === 'system'
    ? matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    : preference;

  const controller = new AbortController();
  let closed = false;
  window.addEventListener('pagehide', () => { closed = true; controller.abort(); }, { once: true });
  const dataset = (async () => {
    try {
      const response = await fetch(new URL('./dataset.json', document.baseURI), { cache: 'no-store', signal: controller.signal });
      if (closed) return { kind: 'closed' };
      if (response.status === 404) return { kind: 'missing' };
      if (!response.ok) return { kind: 'failed', message: '地图数据暂不可用，请稍后刷新。' };
      const text = await response.text();
      return closed ? { kind: 'closed' } : { kind: 'available', text, etag: response.headers.get('ETag') };
    } catch {
      return closed ? { kind: 'closed' } : { kind: 'failed', message: '地图服务暂时无法连接，请稍后刷新。' };
    }
  })();
  window.alongStartup = { dataset, get closed() { return closed; } };
})();
