'use strict';
// Run before styles load so a saved dark theme never flashes light on reload.
(() => {
 const key = 'tonie-studio-theme';
 const system = window.matchMedia('(prefers-color-scheme: dark)');
 let preference = null;
 try { preference = localStorage.getItem(key); } catch { /* Storage may be disabled. */ }
 if (preference !== 'dark' && preference !== 'light') preference = null;
 function apply(theme) {
  const dark = theme === 'dark';
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#101d1a' : '#192d2c';
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
   toggle.setAttribute('aria-pressed', String(dark));
    const locale = window.tonieLocales?.[document.documentElement.lang];
    toggle.title = locale?.[dark ? 'switch_to_light_mode' : 'switch_to_dark_mode'] || (dark ? 'Switch to light mode' : 'Switch to dark mode');
    toggle.setAttribute('aria-label', locale?.dark_mode || 'Dark mode');
   document.getElementById('theme-icon').textContent = dark ? '☀' : '☾';
  }
 }
 const currentTheme = () => preference || (system.matches ? 'dark' : 'light');
 apply(currentTheme());
 document.addEventListener('DOMContentLoaded', () => {
  apply(currentTheme());
  document.getElementById('theme-toggle').addEventListener('click', () => {
   preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
   try { localStorage.setItem(key, preference); } catch { /* Keep the toggle usable. */ }
   apply(preference);
  });
 });
 system.addEventListener('change', () => { if (!preference) apply(currentTheme()); });
 window.addEventListener('storage', event => {
  if (event.key !== key && event.key !== null) return;
  preference = event.newValue === 'dark' || event.newValue === 'light' ? event.newValue : null;
  apply(currentTheme());
 });
})();
