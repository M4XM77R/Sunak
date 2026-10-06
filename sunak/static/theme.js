'use strict';
/* Loaded in <head> before the page is drawn: applies the saved theme and accent, so nothing flickers. */
function sunakAccentText(hex) {
  // black or white text on the accent color, whichever is easier to read
  const m = /^#([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return null;
  const lin = (i) => { const c = parseInt(m[1].slice(i, i + 2), 16) / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const L = 0.2126 * lin(0) + 0.7152 * lin(2) + 0.0722 * lin(4);
  return (L + 0.05) / 0.05 >= 1.05 / (L + 0.05) ? '#000' : '#fff';
}
function sunakApplyTheme(theme, accent) {
  const root = document.documentElement;
  if (theme) root.dataset.theme = theme;
  if (accent) {
    root.style.setProperty('--accent', accent);
    root.style.setProperty('--accent-text', sunakAccentText(accent));
  } else {
    root.style.removeProperty('--accent');
    root.style.removeProperty('--accent-text');
  }
}
try { sunakApplyTheme(localStorage.getItem('sunak-theme'), localStorage.getItem('sunak-accent')); } catch (e) { /* private mode */ }
