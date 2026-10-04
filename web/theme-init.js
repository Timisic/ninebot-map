try {
  const theme = localStorage.getItem("ride-map-theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch {}
