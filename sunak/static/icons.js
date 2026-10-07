'use strict';
/* Sunak's own icons: line drawings on a 24×24 grid, drawn in the text color (currentColor), so they follow
   every theme. icon('mail') makes one for app.js; <i data-i="mail"></i> in index.html becomes one when this
   file runs (it is loaded right before app.js). An icon is decoration: the button's text, title or
   aria-label says what it does. */
const SUNAK_ICONS = {
  alert: '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.5M12 17.2v.1"/>',
  ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  bell: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  bolt: '<path d="M13 2.5 4.5 13.5h7l-1 8 8.5-11h-7z"/>',
  book: '<path d="M5 19.5v-15A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5 1.5 1.5 0 0 0 6.5 21H19v-3"/><path d="M9 7.5h6"/>',
  box: '<path d="m12 2.5 8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z"/><path d="m3.5 7.25 8.5 4.75 8.5-4.75M12 12v9.5"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  chat: '<path d="M20.5 12a8.5 8.5 0 0 1-12.3 7.6L3.5 21l1.4-4.5A8.5 8.5 0 1 1 20.5 12z"/>',
  check: '<path d="m4.5 12.5 5 5 10-11"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.8 2.8L16.2 9"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
  'chevron-left': '<path d="m15 5-7 7 7 7"/>',
  'chevron-right': '<path d="m9 5 7 7-7 7"/>',
  columns: '<rect x="3" y="4" width="7.5" height="16" rx="1.5"/><rect x="13.5" y="4" width="7.5" height="16" rx="1.5"/>',
  cpu: '<rect x="3" y="4" width="18" height="12.5" rx="2"/><path d="M8 20.5h8M12 16.5v4"/>',
  dot: '<circle cx="12" cy="12" r="4.5" fill="currentColor"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  download: '<path d="M12 3.5v11.5M7 10l5 5 5-5M5 20h14"/>',
  edit: '<path d="M4 20l1.2-4.4L16 4.8a2.1 2.1 0 0 1 3 3L8.3 18.6z"/><path d="m14 6.8 3 3"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  forward: '<path d="m14 7 5 5-5 5"/><path d="M19 12h-9a5 5 0 0 0-5 5v2"/>',
  gear: '<path d="M19 10.4 21.4 10.7 21.4 13.3 19 13.6 18.1 15.9 19.6 17.7 17.7 19.6 15.9 18.1 13.6 19 13.3 21.4 10.7 21.4 10.4 19 8.1 18.1 6.3 19.6 4.4 17.7 5.9 15.9 5 13.6 2.6 13.3 2.6 10.7 5 10.4 5.9 8.1 4.4 6.3 6.3 4.4 8.1 5.9 10.4 5 10.7 2.6 13.3 2.6 13.6 5 15.9 5.9 17.7 4.4 19.6 6.3 18.1 8.1z"/><circle cx="12" cy="12" r="3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v7.5a7 7 0 0 1-7 7h-.4a6 6 0 0 1-4.6-2.2L2.8 15.5a1.5 1.5 0 0 1 2.3-1.9L8 16"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.6 2.6 0 1 1 3.6 2.4c-.7.3-1.1.9-1.1 1.6v.5M12 16.8v.1"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 15.5-5-5L6.5 20"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.1"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 6 8.5-6"/>',
  menu: '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  note: '<path d="M15 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10z"/><path d="M15 21v-4a2 2 0 0 1 2-2h4M7.5 8h9M7.5 12h5"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-.5-.2-.9-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1 .8-1.7 1.8-1.7H16a5 5 0 0 0 5-5c0-4-4-7.1-9-7.1z"/><circle cx="7.5" cy="11" r="1.1"/><circle cx="10" cy="7.3" r="1.1"/><circle cx="14.5" cy="7.3" r="1.1"/>',
  paperclip: '<path d="m20 11.5-8.2 8.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4L15 7"/>',
  pin: '<path d="M12 21s-7-6.1-7-11.4a7 7 0 0 1 14 0C19 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  play: '<path d="M7 4.5v15l12.5-7.5z"/>',
  plug: '<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  power: '<path d="M12 3v8.5M6.3 6.6a8 8 0 1 0 11.4 0"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5M4 3.5v4h4M4 13a8 8 0 0 0 14.6 4.5M20 20.5v-4h-4"/>',
  reply: '<path d="m10 7-5 5 5 5"/><path d="M5 12h9a5 5 0 0 1 5 5v2"/>',
  'reply-all': '<path d="m8 7-5 5 5 5M13 7l-5 5 5 5"/><path d="M8 12h6a5 5 0 0 1 5 5v2"/>',
  sail: '<path d="M11 2.5 4 15.5h7zM13.5 6l6 9.5h-6zM3 18h18l-2.5 3.5h-13z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5"/>',
  sparkles: '<path d="M10 3.5 11.8 8.2 16.5 10l-4.7 1.8L10 16.5l-1.8-4.7L3.5 10l4.7-1.8zM18 14.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"/>',
  star: '<path d="m12 3 2.8 5.8 6.2.8-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  swap: '<path d="M7 4 3 8l4 4M3 8h14M17 12l4 4-4 4M21 16H7"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M12.5 15H17"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  volume: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
};
const SUNAK_SVG = 'http://www.w3.org/2000/svg';
function icon(name, cls = '') {
  const svg = document.createElementNS(SUNAK_SVG, 'svg');
  svg.setAttribute('class', `ic${cls ? ` ${cls}` : ''}`);
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.innerHTML = SUNAK_ICONS[name] || SUNAK_ICONS.help;
  return svg;
}
function sunakIcons(root = document) {
  for (const i of root.querySelectorAll('i[data-i]')) i.replaceWith(icon(i.dataset.i, i.className));
}
sunakIcons();
