// Apply the saved palette before Alpine renders the dashboard.
try {
  document.documentElement.classList.toggle('dark', localStorage.getItem('sitepulse-theme') === 'dark');
} catch (_) {
  document.documentElement.classList.remove('dark');
}
