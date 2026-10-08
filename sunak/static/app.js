'use strict';
/* Sunak – single-file frontend, no build step. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ACCENTS = ['#ff4fa3', '#ff2d7a', '#f472b6', '#e879f9', '#c084fc', '#38bdf8', '#34d399', '#fcee0a', '#f97316'];
// keep in sync with the [data-theme] blocks in app.css and THEMES in sunak/server.py
const THEMES = [
  { id: 'dark', name: 'Sunak Dark', sub: 'Pink on night' },
  { id: 'light', name: 'Sunak Light', sub: 'Pink on white' },
  { id: 'retro', name: 'Retro', sub: 'Green terminal' },
  { id: 'cyberpunk', name: 'Cyberpunk', sub: 'Neon on night' },
  { id: 'ocean', name: 'Ocean', sub: 'Deep blue' },
  { id: 'forest', name: 'Forest', sub: 'Calm green' },
  { id: 'sunset', name: 'Sunset', sub: 'Warm and light' },
  { id: 'corporate', name: '80s Corporate', sub: 'Beige office, navy, burgundy' },
];
const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};

const state = { settings: null, models: [], modelErrors: [], sessions: [], session: null, view: 'chat',
  busy: null, attachments: [], doc: null, docUndo: null, status: null, ollama: null, pulls: {}, catType: 'all', catFits: true, catMax: 0, local: null, imgPulls: {}, online: null,
  kb: { files: [], chars: 0 } };

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: { 'X-Requested-With': 'sunak' } };
  if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  if (opts.signal) init.signal = opts.signal;
  const r = await fetch(path, init);
  if (r.status === 401) { location.reload(); throw new Error('Login required'); }
  const data = await r.json().catch(() => ({}));
  if (r.status === 409 && data.error === 'Choose a profile') { showProfilePicker(); throw new Error(data.error); }
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

async function stream(path, body, onEvent, signal) {
  const r = await fetch(path, { method: 'POST', signal, body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'sunak' } });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    const err = new Error(d.error || `HTTP ${r.status}`);
    err.refused = r.status === 400; // nothing was stored
    throw err;
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (line) onEvent(JSON.parse(line));
      }
    }
    if (buf.trim()) onEvent(JSON.parse(buf));
  } finally { usageSoon(); }
}

/* ---------------- Token counter (sunak/usage.py) ---------------- */
const nf = (n) => (n == null ? '–' : Number(n).toLocaleString());
const nfShort = (n) => new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n || 0);
let usageTimers = [];
function usageSoon() {  // after a model request: look again right away and once more for the requests Sunak makes afterwards
  usageTimers.forEach(clearTimeout);
  usageTimers = [setTimeout(loadUsage, 400), setTimeout(loadUsage, 5000)];
}
async function loadUsage() {
  try { state.usage = await api('/api/usage'); } catch (e) { return; }  // the counter is never worth an error message
  renderUsage();
}
function renderUsage() {
  const u = state.usage;
  if (!u) return;
  const last = u.last, sum = (r) => (r.input_tokens || 0) + (r.output_tokens || 0) + (r.cache_read_tokens || 0) + (r.cache_creation_tokens || 0);
  const rate = last?.tokens_per_second == null ? '–' : last.tokens_per_second.toFixed(1);
  const line = $('#usageLine');
  line.classList.toggle('hidden', !u.total.requests);
  const known = last && ['input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens'].some((k) => last[k] != null);
  line.textContent = `${last ? `${known ? nf(sum(last)) : '–'} ${tr('tokens')} · ${rate} tok/s · ` : ''}${tr('Total')} ${nfShort(u.total.all)}`;
  if (!$('#usageLast')) return;
  $('#usageLast').textContent = last
    ? `${tr('Last request')}: ${tr('Input')} ${nf(last.input_tokens)} · ${tr('Output')} ${nf(last.output_tokens)} · ${tr('Cache read')} ${nf(last.cache_read_tokens)} · ${rate} tok/s · ${last.seconds == null ? '–' : last.seconds.toFixed(1)} s · ${last.model}`
    : tr('No request counted yet.');
  $('#usageTotal').textContent = `${tr('Total')} ${nf(u.total.all)} ${tr('tokens')} · ${nf(u.total.requests)} ${tr('requests')}`;
  $('#usageDetail').textContent = `${tr('Input')} ${nf(u.total.input_tokens)} · ${tr('Output')} ${nf(u.total.output_tokens)} · ${tr('Cache read')} ${nf(u.total.cache_read_tokens)} · ${tr('Cache write')} ${nf(u.total.cache_creation_tokens)} · ${tr('made by Sunak itself')} ${nf(u.background.all)}`;
  const all = $('#usageAll');
  all.classList.toggle('hidden', u.installation == null);
  if (u.installation != null) all.textContent = `${tr('All profiles together')}: ${nf(u.installation)} ${tr('tokens')}`;
}
$('#usageLine').onclick = () => { show('settings'); $('#usageLast').scrollIntoView({ block: 'center' }); };

function toast(msg, action) {
  const t = $('#toast');
  t.innerHTML = '';
  t.append(document.createTextNode(msg));
  if (action) {
    const b = document.createElement('button');
    b.className = 'btn'; b.style.marginLeft = '10px'; b.textContent = action.label;
    b.onclick = () => { action.fn(); t.classList.remove('show'); };
    t.append(b);
  }
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), action ? 7000 : 2600);
}

// a clickable div that also works with the keyboard (Tab, then Enter or Space)
const KEY_BUTTON = { tabindex: '0', role: 'button',
  onkeydown: (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); e.currentTarget.click(); } } };
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'html') e.innerHTML = v;
    else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid);
  return e;
}

/* ---------------- Markdown (safe: escapes everything first) ---------------- */
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function inline(s) {
  const codes = [], links = [];
  // code spans and links are swapped out, so emphasis and [1] citations never touch a URL
  const keep = (html) => { links.push(html); return `\u0001${links.length - 1}\u0001`; };
  s = esc(s.replace(/[\u0000\u0001]/g, '')).replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => keep(`<a href="${u}" target="_blank" rel="noopener">${t}</a>`))
    .replace(/(^|[\s(])(https?:\/\/[^\s<)\u0001]+)/g, (_, p, u) => p + keep(`<a href="${u}" target="_blank" rel="noopener">${u}</a>`))
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<em>$2</em>')
    .replace(/(^|[^_\w])_([^_\s][^_]*?)_(?!\w)/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(/\[(\d{1,2})\](?!\()/g, '<sup class="cite">[$1]</sup>');
  return s.replace(/\u0001(\d+)\u0001/g, (_, i) => links[+i]).replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

function blocks(text) {
  const lines = text.split('\n');
  const out = [];
  let para = [];
  const flush = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { flush(); const n = Math.min(m[1].length, 4); out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push('<hr>'); continue; }
    if (/^\s*>/.test(line)) {
      flush();
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''));
      i--; out.push(`<blockquote>${blocks(q.join('\n'))}</blockquote>`); continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      flush();
      const ordered = /^\s*\d/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        let item = lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '');
        const box = item.match(/^\[([ xX])\]\s+/);
        if (box) item = item.slice(box[0].length);
        const check = box ? `<input type="checkbox" disabled${box[1] === ' ' ? '' : ' checked'}> ` : '';
        items.push(`<li>${check}${inline(item)}</li>`); i++;
      }
      i--; out.push(ordered ? `<ol>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`); continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flush();
      const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      i--;
      out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${
        rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    para.push(line);
  }
  flush();
  return out.join('');
}

function md(text) {
  let html = '';
  // reasoning of thinking models
  text = text.replace(/<think>([\s\S]*?)(<\/think>|$)/g, (_, t, closed) => {
    if (!t.trim()) return '';
    html += `<details class="think"${closed ? '' : ' open'}><summary>${closed ? tr('Thought process') : tr('Thinking…')}</summary>${blocks(t.trim())}</details>`;
    return '';
  });
  const parts = text.split(/^```/m);
  parts.forEach((part, idx) => {
    if (idx % 2 === 0) { html += blocks(part); return; }
    const nl = part.indexOf('\n');
    const lang = nl >= 0 ? part.slice(0, nl).trim() : '';
    const code = nl >= 0 ? part.slice(nl + 1).replace(/\n$/, '') : part;
    html += `<pre>${lang ? `<span class="lang">${esc(lang)}</span>` : ''}<button class="copy" type="button">${tr('Copy')}</button><code>${esc(code)}</code></pre>`;
  });
  return html;
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('pre .copy');
  if (!b) return;
  navigator.clipboard.writeText(b.parentElement.querySelector('code').textContent).then(() => {
    b.textContent = 'Copied'; setTimeout(() => (b.textContent = 'Copy'), 1200);
  });
});

/* ---------------- Theme ---------------- */
function applyLook() {
  const s = state.settings;
  const theme = THEMES.some((t) => t.id === s?.theme) ? s.theme : store.get('sunak-theme', 'dark');
  const accent = s ? s.accent : store.get('sunak-accent', '');
  sunakApplyTheme(theme, accent); // from theme.js, which applies the stored values on the next page load
  store.set('sunak-theme', theme);
  store.set('sunak-accent', accent || '');
  $('meta[name="theme-color"]').content = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#ff4fa3';
}
async function saveLook(body) {
  try { await api('/api/settings', { method: 'PUT', body }); } catch (e) { toast(e.message); }
}
function setTheme(id) {
  Object.assign(state.settings, { theme: id, accent: '' }); // each theme brings its own accent
  applyLook();
  renderLook();
  saveLook({ theme: id, accent: '' });
}
function setAccent(color) {
  state.settings.accent = color;
  applyLook();
  renderLook();
  saveLook({ accent: color });
}
function renderLook() {
  const s = state.settings;
  if (!s) return;
  const menu = $('#themeMenu');
  menu.innerHTML = '';
  const cards = $('#themes');
  cards.innerHTML = '';
  for (const t of THEMES) {
    const on = s.theme === t.id;
    menu.append(el('button', { type: 'button', class: `theme-opt${on ? ' on' : ''}`, onclick: () => setTheme(t.id) },
      el('span', { class: 'theme-dot', 'data-theme': t.id }), t.name));
    cards.append(el('button', { type: 'button', class: `theme-card${on ? ' on' : ''}`, 'data-theme': t.id, 'aria-pressed': String(on),
      title: t.name, onclick: () => setTheme(t.id) },
      el('span', { class: 'tc-bar' }, el('span', { class: 'tc-panel' }), el('span', { class: 'tc-btn' }, 'Aa')),
      el('span', { class: 'tc-name' }, t.name), el('span', { class: 'tc-sub' }, t.sub)));
  }
  const sw = $('#swatches');
  sw.innerHTML = '';
  sw.append(el('button', { class: s.accent ? '' : 'on', 'data-theme': s.theme, style: 'background:var(--accent)', title: 'Theme color',
    'aria-label': 'Theme color', onclick: () => setAccent('') }));
  ACCENTS.forEach((c) => sw.append(el('button', { class: c === s.accent ? 'on' : '', style: `background:${c}`, title: c, 'aria-label': c,
    onclick: () => setAccent(c) })));
  const ls = $('#language'); // languages: i18n.js and the lang-*.js files
  ls.replaceChildren(el('option', { value: '' }, tr('Automatic (browser language)')),
    ...Object.entries(SUNAK_LANG_NAMES).map(([code, name]) => el('option', { value: code, 'data-no-i18n': '' }, name)));
  ls.value = s.language || '';
}
$('#language').onchange = async (e) => {
  const lang = e.target.value;
  try { await api('/api/settings', { method: 'PUT', body: { language: lang } }); }
  catch (err) { toast(err.message); e.target.value = state.settings.language || ''; return; }
  store.set('sunak-lang', lang);
  location.reload(); // the page is drawn again in the new language
};
$('#themeBtn').onclick = (e) => { e.stopPropagation(); $('#themeMenu').classList.toggle('hidden'); };
$('#themeMenu').onclick = () => $('#themeMenu').classList.add('hidden');
document.addEventListener('click', (e) => { if (!$('#themeWrap').contains(e.target)) $('#themeMenu').classList.add('hidden'); });

/* ---------------- Navigation ---------------- */
const TITLES = { chat: 'Chat', compare: 'Compare models', research: 'Deep Research', documents: 'Documents', knowledge: 'Knowledge', mail: 'Mail', calendar: 'Calendar', notes: 'Notes & Memory', models: 'Models', settings: 'Settings' };
function show(view) {
  state.view = view;
  document.body.dataset.view = view;
  $$('.nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
  $('#viewTitle').textContent = view === 'chat' && state.session ? state.session.title : tr(TITLES[view]);
  $('#modelSelect').classList.toggle('hidden', ['notes', 'settings', 'compare', 'models', 'knowledge'].includes(view));
  $('#personaSelect').classList.toggle('hidden', view !== 'chat');
  syncExport();
  closeSidebar();
  if (view === 'documents') loadDocs();
  if (view === 'notes') loadNotes();
  if (view === 'knowledge') loadKb();
  if (view === 'mail') loadMailView();
  if (view === 'calendar') loadCalendar();
  if (view === 'settings') renderSettings();
  if (view === 'compare') renderCompareModels();
  if (view === 'models') { renderModelsView(); loadOllama(); loadLocalImages(); }
  if (view === 'chat') $('#prompt').focus();
}
$$('.nav button').forEach((b) => (b.onclick = () => show(b.dataset.view)));
const closeSidebar = () => { $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('open'); };
$('#menuBtn').onclick = () => { $('#sidebar').classList.add('open'); $('#scrim').classList.add('open'); };
$('#scrim').onclick = closeSidebar;

/* ---------------- Models ---------------- */
async function loadModels() {
  const r = await api('/api/models');
  state.models = r.models;
  state.modelErrors = r.errors;
  const sel = $('#modelSelect');
  sel.innerHTML = '';
  if (!state.models.length) sel.append(el('option', { value: '' }, tr('No model installed')));
  const groups = {};
  for (const m of state.models) (groups[m.provider_name] ||= []).push(m);
  for (const [name, ms] of Object.entries(groups)) {
    sel.append(el('optgroup', { label: name }, ms.map((m) => el('option', { value: m.id }, m.name))));
  }
  syncModelSelect();
}
function currentModel() {
  const ids = state.models.map((m) => m.id);
  for (const c of [state.session?.model, store.get('sunak-model'), state.settings?.default_model]) if (c && ids.includes(c)) return c;
  return ids[0] || '';
}
function syncModelSelect() { $('#modelSelect').value = currentModel(); }
$('#modelSelect').onchange = async (e) => {
  store.set('sunak-model', e.target.value);
  if (state.session) { state.session.model = e.target.value; await api(`/api/sessions/${state.session.id}`, { method: 'PATCH', body: { model: e.target.value } }); }
};

/* ---------------- Personas ---------------- */
function currentPersona() {
  const ids = (state.settings?.personas || []).map((p) => p.id);
  for (const c of [state.session?.persona, state.session ? null : store.get('sunak-persona')]) if (c && ids.includes(c)) return c;
  return ids[0] || '';
}
function renderPersonaSelect() {
  const sel = $('#personaSelect');
  sel.innerHTML = '';
  for (const p of state.settings?.personas || []) sel.append(el('option', { value: p.id }, p.name));
  sel.value = currentPersona();
}
$('#personaSelect').onchange = async (e) => {
  store.set('sunak-persona', e.target.value);
  if (state.session?.id) { state.session.persona = e.target.value; await api(`/api/sessions/${state.session.id}`, { method: 'PATCH', body: { persona: e.target.value } }); }
  const p = state.settings.personas.find((x) => x.id === e.target.value);
  toast(`${p.name}${p.prompt ? '' : ` ${tr('(no extra instructions)')}`}`);
};

/* ---------------- Sessions ---------------- */
async function loadSessions() {
  state.sessions = await api('/api/sessions');
  renderSessions();
}
function renderSessions() {
  if ($('#sessionFilter').value.trim().length >= 2) { searchChats(); return; }
  const box = $('#sessions');
  box.innerHTML = '';
  for (const s of state.sessions) {
    box.append(el('div', { class: `session${state.session?.id === s.id ? ' active' : ''}`, onclick: () => openSession(s.id), ...KEY_BUTTON },
      el('span', { class: 't', title: s.title }, s.title),
      el('button', { class: 'x', title: 'Delete', onclick: async (e) => {
        e.stopPropagation();
        if (!confirm(tr('Delete “{title}”?', { title: s.title }))) return;
        await api(`/api/sessions/${s.id}`, { method: 'DELETE' });
        if (state.session?.id === s.id) newChat();
        loadSessions();
      } }, icon('x'))));
  }
}
// search in all chats (titles and messages); results show where the words occur
let searchTimer = null;
$('#sessionFilter').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderSessions, 200); };
async function searchChats() {
  const q = $('#sessionFilter').value.trim();
  const hits = await api(`/api/search?q=${encodeURIComponent(q)}`);
  if ($('#sessionFilter').value.trim() !== q) return; // a newer search is on its way
  const box = $('#sessions');
  box.innerHTML = '';
  if (!hits.length) box.append(el('p', { class: 'muted small', style: 'padding:4px 10px' }, 'No chats found.'));
  for (const h of hits) {
    box.append(el('div', { class: `session hit${state.session?.id === h.session_id ? ' active' : ''}`, onclick: () => openSession(h.session_id, h.message_id), ...KEY_BUTTON },
      el('span', { class: 't', title: h.title }, h.title), h.snippet && h.snippet !== h.title ? el('span', { class: 'snip' }, h.snippet) : null));
  }
}

let openSeq = 0;
async function openSession(id, messageId) {
  stopBusy(); // the partial answer is saved by the server
  const seq = ++openSeq;
  const session = await api(`/api/sessions/${id}`);
  if (seq !== openSeq) return; // another chat was clicked meanwhile
  state.session = session;
  syncModelSelect();
  renderKbToggle(); renderWebToggle();
  renderPersonaSelect();
  renderMessages();
  renderSessions();
  show('chat');
  if (messageId) {
    const m = $(`#messages .msg[data-id="${messageId}"]`);
    if (m) { m.scrollIntoView({ block: 'center' }); m.classList.add('flash'); setTimeout(() => m.classList.remove('flash'), 1800); }
  }
}
function newChat() {
  stopBusy();
  openSeq++;
  state.session = null;
  state.attachments = [];
  renderAttachments();
  renderKbToggle(); renderWebToggle();
  renderPersonaSelect();
  renderMessages();
  renderSessions();
  show('chat');
}
$('#newChat').onclick = newChat;

/* ---------------- Chat rendering ---------------- */
function welcome() {
  const box = el('div', { class: 'welcome' }, el('img', { src: '/icon.svg', alt: '' }), el('h2', {}, 'Hi, I am Sunak.'),
    el('p', { class: 'muted' }, 'Your private AI workspace. Everything stays on your machine.'));
  if (!state.models.length) box.append(setupCard());
  else {
    const ideas = ['Explain how a transformer model works, simply', 'Write a polite email declining a meeting',
      'Plan a 3-day trip to Stockholm', 'Give me 5 dinner ideas with pasta and spinach'].map((x) => tr(x));
    box.append(el('div', { class: 'suggestions' }, ideas.map((t) => el('button', { onclick: () => { $('#prompt').value = t; send(); } }, t))));
  }
  return box;
}

function setupCard() {
  const o = state.ollama;
  if (!o || !o.running) {
    return el('div', { class: 'card' }, el('h3', {}, 'Let’s get a model running'), ollamaBanner(),
      el('p', { class: 'muted small' }, 'Prefer the cloud? ', el('a', { href: '#', onclick: (e) => { e.preventDefault(); connectClaude(); } }, 'Use Claude with an API key'),
        ' or ', el('a', { href: '#', onclick: (e) => { e.preventDefault(); show('settings'); } }, 'another provider'), '.'));
  }
  const rec = state.status?.recommended || { model: 'qwen3:4b', size: '2.6 GB' };
  const ram = state.status?.ram_gb ? `${tr('{gb} GB RAM detected.', { gb: state.status.ram_gb })} ` : '';
  return el('div', { class: 'card' }, el('h3', {}, 'Download your first model'),
    el('p', { class: 'muted' }, `${ram}${tr('Recommended for your computer:')} `, el('b', {}, rec.model), ` (${rec.size}).`),
    el('div', { class: 'row' }, pullButton(rec.model, tr('Download {model}', { model: rec.model })),
      el('button', { class: 'btn', onclick: () => show('models') }, 'Browse models')));
}

function messageEl(m, i, msgs) {
  const isUser = m.role === 'user';
  const body = el('div', { class: 'body' });
  if (isUser) body.append(userBubble(m.content, m.localImages || (m.meta?.images || []).map((n) => `/api/images/${n}`)));
  else {
    if (m.meta?.sources) body.append(sourcesEl(m.meta.sources));
    if (m.meta?.web) body.append(webSourcesEl(m.meta.web));
    if (m.meta?.assist) body.append(assistEl(m));
    else if (m.meta?.tools || m.meta?.agent) body.append(toolsEl(m.meta.tools || m.meta.agent)); // `agent`: chats stored before 0.13.0
    else if (m.meta?.imagegen || m.meta?.pending) body.append(genFigure(m));
    else body.append(el('div', { class: 'md', html: mdChat(m.content) }));
  }
  if (!isUser) { const cards = actionCards(m, i === msgs.length - 1); if (cards) body.append(cards); }
  const meta = el('div', { class: 'meta' });
  const gen = m.meta?.imagegen;
  const copyText = gen ? gen.prompt : m.content.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').trim();
  meta.append(el('button', { onclick: () => navigator.clipboard.writeText(copyText).then(() => toast('Copied')) }, gen ? 'Copy description' : 'Copy'));
  if (gen) {
    meta.append(el('a', { href: `/api/images/${m.meta.images[0]}`, download: `sunak-${gen.seed}.${m.meta.images[0].split('.')[1]}` }, icon('download'), 'Download'));
    if (!state.busy) meta.append(el('button', { title: 'Same description, new picture', onclick: () => {
      const asked = msgs.slice(0, i).reverse().find((x) => x.role === 'user');
      runImagine({ prompt: gen.prompt, negative: gen.negative || '', aspect: asked?.meta?.imagine?.aspect || 'square' });
    } }, icon('refresh'), 'Again'));
  } else if (!state.busy && m.id && !m.meta?.imagine) {
    if (isUser) meta.append(el('button', { onclick: () => editMessage(m) }, 'Edit'));
    if (!isUser && i === msgs.length - 1) meta.append(el('button', { onclick: () => regenerate(m) }, 'Regenerate'));
  }
  if (!isUser && tts && m.content && !gen && !m.meta?.pending) meta.append(speakButton(m));
  if (!isUser && m.model) meta.append(el('span', {}, m.model.split('::')[1] || m.model));
  body.append(meta);
  return el('div', { class: `msg ${m.role}`, 'data-id': m.id }, el('div', { class: 'avatar' }, icon(isUser ? 'user' : 'sail')), body);
}

// attached files (File `name`: ``` text ```) are shown folded, the question as text
const ATTACHED_RE = /File `([^`\n]+)`:\n```\n([\s\S]*?)\n```\s*/g;
function userBubble(content, images = []) {
  const files = [...content.matchAll(ATTACHED_RE)];
  const rest = content.replace(ATTACHED_RE, '').trim();
  return el('div', { class: 'bubble' },
    images.length ? el('div', { class: 'msg-images' }, images.map((src) =>
      el('a', { href: src, target: '_blank', rel: 'noopener' }, el('img', { src, alt: tr('Attached image'), loading: 'lazy' })))) : '',
    files.map((f) => el('details', { class: 'attached' }, el('summary', {}, icon('file'), f[1]), el('pre', { class: 'kb-text' }, f[2]))),
    rest);
}

function renderMessages() {
  const box = $('#messages');
  box.innerHTML = '';
  const msgs = state.session?.messages || [];
  syncExport();
  if (!msgs.length) { box.append(welcome()); return; }
  msgs.forEach((m, i) => box.append(messageEl(m, i, msgs)));
  box.scrollTop = box.scrollHeight;
}

/* ---------------- Export ---------------- */
function syncExport() {
  const s = state.session;
  $('#exportWrap').classList.toggle('hidden', !(state.view === 'chat' && s?.id && s.messages?.length));
  $('#exportMenu').classList.add('hidden');
  if (s?.id) {
    $('#exportMd').href = `/api/sessions/${s.id}/export?format=md`;
    $('#exportJson').href = `/api/sessions/${s.id}/export?format=json`;
  }
}
$('#exportBtn').onclick = (e) => { e.stopPropagation(); $('#exportMenu').classList.toggle('hidden'); };
$('#exportMenu').onclick = () => $('#exportMenu').classList.add('hidden');
$('#exportPrint').onclick = () => window.print();
document.addEventListener('click', (e) => { if (!$('#exportWrap').contains(e.target)) $('#exportMenu').classList.add('hidden'); });

/* ---------------- Sending ---------------- */
const promptEl = $('#prompt');
function autosize() { promptEl.style.height = 'auto'; promptEl.style.height = `${Math.min(promptEl.scrollHeight, 240)}px`; }
promptEl.addEventListener('input', autosize);
promptEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
$('#composer').onsubmit = (e) => { e.preventDefault(); state.busy ? stopBusy() : send(); };
function stopBusy() {
  if (state.toolRun) api('/api/tools/cancel', { method: 'POST', body: { run: state.toolRun } }).catch(() => {});
  if (state.busy) state.busy.abort();
}

// a request waits for the model while others are served first (sunak/jobqueue.py): say its place
const queueText = (n) => tr('Waiting in the queue: place {n}', { n });
let sending = false;
async function send(skipAssist) {  // skipAssist: a normal chat message, even if it reads like an event or e-mail request
  if (state.busy || sending) return;
  sending = true;
  try { await sendNow(skipAssist); } finally { sending = false; }
}
async function sendNow(skipAssist) {
  let text = promptEl.value.trim();
  if (!text && !state.attachments.length) return;
  if (!state.attachments.length) {
    const act = skipAssist ? null : await assistantIntent(text);
    if (act && await assistantRequest(act, text)) return;
    const ask = await pictureIntent(text, false, 'chat');
    if (ask && await pictureRequest(text, ask.subject)) return;
  }
  if (!currentModel()) { toast('Install or connect a model first'); show('settings'); return; }
  if (state.attachments.some((a) => a.loading)) { toast('Still reading your files…'); return; }
  const pics = state.attachments.filter((a) => a.image);
  if (pics.length && mcpOn()) { toast('Tools (MCP) cannot look at images yet. Switch them off to ask about the image.'); return; }
  const files = state.attachments.filter((a) => !a.image);
  if (files.length) {
    text = files.map((a) => `File \`${a.name}\`:\n\`\`\`\n${a.text}\n\`\`\``).join('\n\n') + (text ? `\n\n${text}` : '');
  }
  if (!state.session) {
    try {
      state.session = await api('/api/sessions', { method: 'POST', body: { model: currentModel(), use_kb: kbOn(), use_web: webOn(), persona: currentPersona() } });
    } catch (e) { toast(e.message); return; } // keep the typed text and the files
    state.session.messages = [];
  }
  const kept = { text: promptEl.value, attachments: state.attachments };
  promptEl.value = ''; autosize();
  state.attachments = []; renderAttachments();
  sending = false; // from here on state.busy guards against a second send
  const payload = { content: text };
  if (pics.length) payload.images = pics.map((a) => ({ name: a.name, data: a.data }));
  const result = await runChat(payload, { role: 'user', content: text, localImages: pics.map((a) => a.url) });
  // the server refused before storing anything (e.g. a model without vision): give the message back
  if (result === 'refused' && !promptEl.value && !state.attachments.length) {
    promptEl.value = kept.text; autosize();
    state.attachments = kept.attachments; renderAttachments();
  }
}

async function runChat(payload, localUserMsg) {
  if (mcpOn()) return runTools(payload, localUserMsg);
  const s = state.session;
  if (localUserMsg) s.messages.push(localUserMsg);
  const ans = { role: 'assistant', content: '', model: currentModel() };
  s.messages.push(ans);
  const ctrl = new AbortController();
  state.busy = ctrl;
  $('#sendBtn').textContent = 'Stop';
  renderMessages();
  const box = $('#messages');
  const target = box.lastElementChild.querySelector('.md');
  target.classList.add('typing');
  const status = el('div', { class: 'muted small web-status', role: 'status' });
  target.before(status);
  let raw = '', thinking = false, pending = false, error = null, stopped = false, thinkOpen = null, refused = false;
  // the user may fold the thinking block while it streams: keep their choice across repaints
  target.addEventListener('click', (e) => { const d = e.target.closest('summary') && e.target.closest('details.think'); if (d) thinkOpen = !d.open; });
  const paint = () => {
    pending = false;
    if (raw) status.textContent = '';
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
    target.innerHTML = mdChat(raw);
    const d = target.querySelector('details.think');
    if (d && thinkOpen !== null) d.open = thinkOpen;
    if (nearBottom) box.scrollTop = box.scrollHeight;
  };
  try {
    await stream('/api/chat', { session_id: s.id, model: currentModel(), use_kb: kbOn(), use_web: webOn(), persona: currentPersona(), ...payload }, (ev) => {
      if (ev.type === 'start') { s.title = ev.title; $('#viewTitle').textContent = ev.title; }
      else if (ev.type === 'sources') target.before(sourcesEl(ev.sources));
      else if (ev.type === 'status') { status.textContent = ev.t; return; }
      else if (ev.type === 'queued') { status.textContent = ev.position > 0 ? queueText(ev.position) : ''; return; }
      else if (ev.type === 'web') { status.textContent = ''; target.before(webSourcesEl(ev)); return; }
      else if (ev.type === 'think') { if (!thinking) { raw += '<think>'; thinking = true; } raw += ev.t; }
      else if (ev.type === 'text') { if (thinking) { raw += '</think>\n\n'; thinking = false; } raw += ev.t; }
      else if (ev.type === 'error') error = ev.error;
      if (!pending) { pending = true; requestAnimationFrame(paint); }
    }, ctrl.signal);
  } catch (e) {
    if (e.name === 'AbortError') stopped = true;
    else { error = e.message; refused = !!e.refused; }
  }
  state.busy = null;
  $('#sendBtn').textContent = 'Send';
  loadSessions();
  if (state.session !== s) return; // the user opened another chat meanwhile
  // after Stop the server saves the partial answer a moment later: wait for it, else keep the local one
  let fresh = null;
  for (let i = 0; i < (stopped ? 4 : 1); i++) {
    try { fresh = await api(`/api/sessions/${s.id}`); } catch (e) { break; }
    if (!stopped || !raw || fresh.messages.at(-1)?.role === 'assistant') break;
    await new Promise((r) => setTimeout(r, 400));
  }
  if (state.session !== s || state.busy) return; // switched chats or sent again while loading
  if (fresh) {
    if (stopped && raw && fresh.messages.at(-1)?.role !== 'assistant') fresh.messages.push({ ...ans, content: raw + (thinking ? '</think>' : '') });
    state.session = fresh;
  }
  renderMessages();
  if (error) $('#messages').append(el('div', { class: 'msg' }, el('div', { class: 'avatar warn' }, icon('alert')), el('div', { class: 'body err' }, error)));
  $('#messages').scrollTop = $('#messages').scrollHeight;
  if (!error && !stopped) remember(s.id);
  return refused ? 'refused' : 'ok';
}

// after an answer: the server picks lasting facts about the user from it (sunak/memory.py); say what it kept, with Undo
async function remember(sid) {
  if (!state.settings?.use_memory) return;
  let r;
  try { r = await api(`/api/sessions/${sid}/remember`, { method: 'POST', body: {} }); } catch (e) { return; }
  if (!r.added?.length) return;
  toast(tr('Remembered: {text}', { text: r.added.map((n) => n.content).join(' · ') }), { label: tr('Undo'), fn: async () => {
    await Promise.all(r.added.map((n) => api(`/api/notes/${n.id}`, { method: 'DELETE' }).catch(() => {})));
    toast('Forgotten');
  } });
}

/* ---------------- Image generation ----------------
   A message that asks for a picture ("make a picture of …") is recognised and made by the image generator without
   asking: the chat model first writes a better prompt, the image model paints it (Sunak's own program, see
   sunak/sdcpp.py, or Automatic1111 / ComfyUI, see sunak/imagegen.py). */
// image_status.problem: what is missing for Sunak's own program ('' = nothing), see sdcpp.status
const imageProblem = () => state.settings?.image_status?.problem || '';
const imagineReady = () => (state.settings?.image_gen || 'off') !== 'off' && !imageProblem();
const IMAGE_PROBLEMS = {
  setup: 'No image generator is set up. Set up Sunak’s own image program on the Models page under Image models, or connect ComfyUI or Automatic1111 in Settings.',
  no_engine: 'The image program is not set up. Set it up on the Models page under Image models.',
  no_model: 'The image program is ready, but no image model is downloaded yet. Download one on the Models page under Image models (SD-Turbo is small and fast).',
};
// a picture was asked for but something is missing: say what, and go there
async function imagineSetup() {
  const p = imageProblem(), st = state.settings.image_status;
  if (p === 'choose') {  // program and model are there, only the choice was never made
    await useImageModel(st.model);
    return imagineReady();
  }
  if (!isAdmin()) { toast('An admin profile has to set up pictures first (Models page, Image models).'); return false; }
  toast(IMAGE_PROBLEMS[p || 'setup'], { label: 'Open', fn: () => show('models') });
  return false;
}
function genFigure(m) {
  if (m.meta.pending) {
    return el('div', { class: 'gen-wait', role: 'status' }, el('progress', { max: 1 }), el('span', { class: 'muted small gen-status' }, 'Painting the picture…'), el('div', { class: 'muted small gen-prompt', 'data-no-i18n': '' }));
  }
  const g = m.meta.imagegen, src = `/api/images/${m.meta.images[0]}`;
  return el('figure', { class: 'gen-figure' },
    el('a', { href: src, target: '_blank', rel: 'noopener' }, el('img', { src, alt: g.prompt, loading: 'lazy', width: g.width, height: g.height, 'data-no-i18n': '' })),
    el('figcaption', { class: 'muted small' },
      el('div', { class: 'gen-prompt', 'data-no-i18n': '' }, el('b', {}, `${tr(g.request ? 'Improved prompt' : 'Prompt')}: `), g.prompt),
      el('div', { 'data-no-i18n': '' }, `${g.width}×${g.height} · ${tr('seed')} ${g.seed} · ${g.steps} ${tr('steps')}${g.model ? ` · ${g.model}` : ''}`)));
}
// A chat model cannot paint. When the message asks for a picture ("generate an image of …", "mach ein Bild von …",
// "mal mir eine Katze"), Sunak makes it with the image generator by itself: the chat model improves the description
// first. The server decides (sunak/intent.py: rules, and for unclear messages the chat model).
async function pictureIntent(text, quick, where) {  // quick: rules only, never ask the chat model; where: chat/research (for the log)
  if (text.length > 600) return null;
  const ctrl = new AbortController(), timer = setTimeout(() => ctrl.abort(), 30000);
  $('#sendBtn').disabled = true;
  try {
    const r = await api('/api/imagine/intent', { method: 'POST', body: { text, model: currentModel() || '', quick: !!quick, where: where || 'chat' }, signal: ctrl.signal });
    return r.image ? r : null;
  } catch (e) { return null; } // no answer: it is a normal chat message
  finally { clearTimeout(timer); $('#sendBtn').disabled = false; }
}
async function pictureRequest(text, subject) {
  if (!imagineReady()) {
    // not set up (yet): say what is missing (and where to fix it), then let the chat model answer as usual
    if (state.settings.image_status?.problem === 'choose') { if (!(await imagineSetup())) return false; }
    else { await imagineSetup(); return false; }
  }
  if (!state.session) {
    try {
      state.session = await api('/api/sessions', { method: 'POST', body: { model: currentModel() || '', use_kb: kbOn(), use_web: webOn(), persona: currentPersona() } });
    } catch (e) { toast(e.message); return true; }
    state.session.messages = [];
  }
  promptEl.value = ''; autosize();
  sending = false; // from here on state.busy guards against a second send
  await runImagine({ prompt: text, improve: true, model: currentModel() || '', fallback: subject || text, aspect: 'auto' });
  return true;
}
// A picture request typed in another view (Deep Research): paint it in a new chat instead of searching the web for it.
async function divertPicture(text, where) {
  const ask = await pictureIntent(text, false, where);
  if (!ask) return false;
  if (!imagineReady() && state.settings.image_status?.problem !== 'choose') { await imagineSetup(); return false; }
  newChat();
  if (!(await pictureRequest(text, ask.subject))) promptEl.value = text, autosize();
  return true;
}
async function runImagine(body) {
  const s = state.session;
  s.messages.push({ role: 'user', content: body.prompt, meta: { imagine: { aspect: body.aspect } } });
  s.messages.push({ role: 'assistant', content: '', meta: { pending: true } });
  const ctrl = new AbortController();
  state.busy = ctrl;
  $('#sendBtn').textContent = 'Stop';
  renderMessages();
  const wait = $('#messages').lastElementChild.querySelector('.gen-wait');
  const bar = wait.querySelector('progress'), statusEl = wait.querySelector('.gen-status'), promptShown = wait.querySelector('.gen-prompt');
  let error = null, stopped = false;
  try {
    await stream('/api/imagine', { session_id: s.id, ...body }, (ev) => {
      if (ev.type === 'start') { s.title = ev.title; $('#viewTitle').textContent = ev.title; }
      else if (ev.type === 'status') statusEl.textContent = tr(ev.t);
      else if (ev.type === 'queued') { if (ev.position > 0) statusEl.textContent = queueText(ev.position); }
      else if (ev.type === 'prompt') promptShown.textContent = `${tr('Prompt')}: ${ev.prompt}`;
      else if (ev.type === 'progress') { if (ev.p == null) bar.removeAttribute('value'); else bar.value = ev.p; }
      else if (ev.type === 'error') error = ev.error;
    }, ctrl.signal);
  } catch (e) {
    if (e.name === 'AbortError') stopped = true;
    else error = e.message;
  }
  state.busy = null;
  $('#sendBtn').textContent = 'Send';
  loadSessions();
  if (state.session !== s) return;
  try { state.session = await api(`/api/sessions/${s.id}`); } catch (e) { s.messages = s.messages.filter((x) => !x.meta?.pending); }
  if (state.session !== s && state.session.id !== s.id) return;
  renderMessages();
  if (error && !stopped) $('#messages').append(el('div', { class: 'msg' }, el('div', { class: 'avatar warn' }, icon('alert')), el('div', { class: 'body err' }, error)));
  $('#messages').scrollTop = $('#messages').scrollHeight;
}

/* ---------------- Events and e-mails from the chat ----------------
   "trag mir morgen 10 Uhr Zahnarzt ein" / "schreib Anna eine Mail, dass ich später komme": Sunak prepares the event or the
   draft and shows it as a card. Nothing is saved or sent before a click (Save; in the Mail view Send, which asks again).
   The server recognises the request by rules (sunak/intent.py), so it works with every model. These cards live only in
   the open chat (they are not stored with it). */
async function assistantIntent(text) {
  if (text.length > 600) return null;
  try {
    const r = await api('/api/assistant/intent', { method: 'POST', body: { text } });
    return r.action || null;
  } catch (e) { return null; } // no answer: it is a normal chat message
}
async function assistantRequest(kind, text) {
  if (!currentModel()) { toast('Install or connect a model first'); show('settings'); return true; }
  if (!state.session) {
    try {
      state.session = await api('/api/sessions', { method: 'POST', body: { model: currentModel() || '', use_kb: kbOn(), use_web: webOn(), persona: currentPersona() } });
    } catch (e) { toast(e.message); return true; }
    state.session.messages = [];
  }
  const s = state.session;
  promptEl.value = ''; autosize();
  sending = false;
  const a = { kind, status: 'working', text };
  const reply = { role: 'assistant', content: '', model: currentModel(), meta: { assist: a } };
  s.messages.push({ role: 'user', content: text }, reply);
  const ctrl = new AbortController();
  state.busy = ctrl;
  $('#sendBtn').textContent = 'Stop';
  renderMessages();
  try {
    if (kind === 'event') {
      a.draft = await api('/api/calendar/parse', { method: 'POST', body: { text, now: isoLocal(new Date()), model: currentModel() }, signal: ctrl.signal });
      reply.content = `${a.draft.summary} (${a.draft.start.replace('T', ' ')})`;
    } else {
      a.draft = await api('/api/assistant/mail', { method: 'POST', body: { text, model: currentModel() }, signal: ctrl.signal });
      reply.content = `${a.draft.subject}\n\n${a.draft.body}`;
    }
    a.status = 'ready';
  } catch (e) {
    a.status = e.name === 'AbortError' ? 'stopped' : 'error';
    a.error = e.message;
    if (kind === 'mail' && /mail account/i.test(e.message)) a.setup = 'mail';
  }
  state.busy = null;
  $('#sendBtn').textContent = 'Send';
  if (state.session === s) renderMessages();
  return true;
}
// the event the calendar endpoint takes, from a parsed draft: all-day events end the day after (exclusive), timed ones go as UTC
function eventFromDraft(d) {
  if (d.all_day) return { summary: d.summary, all_day: true, start: d.start.slice(0, 10), end: ymd(addDays(dayOf(d.end.slice(0, 10)), 1)),
    location: d.location, description: d.description, repeat: '' };
  return { summary: d.summary, all_day: false, start: new Date(d.start).toISOString(), end: new Date(d.end).toISOString(),
    location: d.location, description: d.description, repeat: '' };
}
function eventWhen(d) {
  const day = (s) => dayOf(s.slice(0, 10)).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' });
  if (d.all_day) return d.end === d.start ? day(d.start) : `${day(d.start)} – ${day(d.end)}`;
  const time = (s) => s.slice(11, 16);
  return d.end.slice(0, 10) === d.start.slice(0, 10) ? `${day(d.start)}, ${time(d.start)} – ${time(d.end)}` : `${day(d.start)} ${time(d.start)} – ${day(d.end)} ${time(d.end)}`;
}
async function saveChatEvent(a, btn) {
  btn.disabled = true;
  try {
    let target = store.get('sunak-cal-target', 'local') || 'local';
    if (target !== 'local') {
      try { cal.info = await api('/api/calendar'); } catch (e) { /* Sunak's own calendar always exists */ }
      if (!calTargets().some((t) => t.value === target)) target = 'local';
    }
    const [source, calendar] = target.split(/\|(.*)/s);
    await api('/api/calendar/events', { method: 'POST', body: { source, calendar, event: eventFromDraft(a.draft) } });
    a.saved = true;
    a.savedIn = calTargets().find((t) => t.value === target)?.label || 'Sunak';
    renderMessages();
  } catch (e) { toast(e.message); btn.disabled = false; }
}
async function editChatEvent(a) {
  show('calendar');
  if (!cal.info) await loadCalendar();
  cal.sel = a.draft.start.slice(0, 10);
  const s = dayOf(cal.sel);
  if (s.getFullYear() !== cal.month.getFullYear() || s.getMonth() !== cal.month.getMonth()) { cal.month = new Date(s.getFullYear(), s.getMonth(), 1); loadCalEvents(); }
  else renderCalGrid();
  editEvent(null, a.draft);
}
async function openChatMail(a) {
  show('mail');
  await loadMailView();
  if (a.draft.account && state.mail.accounts.some((x) => x.id === a.draft.account)) $('#mailAccount').value = a.draft.account;
  openCompose({ to: a.draft.to, subject: a.draft.subject, start: a.draft.body });
}
// "That was a normal question": drop the card and send the message to the chat model as it is
function sendAsChat(a) {
  if (state.busy || sending) return;
  if (promptEl.value.trim() || state.attachments.length) { toast('Send or clear the text in the input box first'); return; }
  const msgs = state.session.messages, i = msgs.findIndex((x) => x.meta?.assist === a);
  if (i > 0) msgs.splice(i - 1, 2);
  renderMessages();
  promptEl.value = a.text; autosize();
  send(true);
}
const chatInstead = (a) => el('button', { class: 'btn', type: 'button', title: 'Not what you meant? Send your message to the model as a normal chat message', onclick: () => sendAsChat(a) }, 'Send as normal message');
const eventIsPast = (d) => (d.all_day ? dayOf(d.end.slice(0, 10)) < dayOf(ymd(new Date())) : new Date(d.end) < new Date());
// The chat model may answer an event or e-mail request with a fenced ```sunak-event``` / ```sunak-mail``` block (sunak/intent.py
// `abilities` tells it how). The block is never shown as text: the server checks its JSON (POST /api/assistant/check) and the
// same card as above appears in the newest answer; saving or sending still needs a click. The card is built with el(), as text.
const ACTION_BLOCK = /```sunak-(event|mail)[^\S\n]*\n([\s\S]*?)```/g;
const stripActions = (t) => t.replace(ACTION_BLOCK, '').replace(/```sunak-[\s\S]*$/, '').trim(); // the second one: a block still being written
const mdChat = (t) => md(stripActions(t));
const actionCache = new Map(); // block text → card state, so a repaint does not check (or save) it again
async function checkActionBlock(a, kind, json) {
  try {
    a.draft = await api('/api/assistant/check', { method: 'POST', body: { kind, json, now: isoLocal(new Date()) } });
    a.status = 'ready';
  } catch (e) {
    a.status = 'error';
    a.error = e.message;
    if (kind === 'mail' && /mail account/i.test(e.message)) a.setup = 'mail';
  }
}
function actionCards(m, last) {
  if (m.role !== 'assistant' || !m.content || !m.content.includes('```sunak-')) return null;
  const blocks = [...m.content.matchAll(ACTION_BLOCK)].slice(0, 3);
  if (!blocks.length) return null;
  const box = el('div', { class: 'assist-cards' });
  for (const [, kind, json] of blocks) {
    if (!last) { box.append(el('div', { class: 'muted small' }, kind === 'event' ? 'An event card was shown here.' : 'An e-mail card was shown here.')); continue; }
    const key = `${kind}\n${json}`;
    let a = actionCache.get(key);
    if (!a) { a = { kind, status: 'working', fromModel: true }; actionCache.set(key, a); if (actionCache.size > 50) actionCache.delete(actionCache.keys().next().value); }
    const holder = el('div', {}, assistEl({ meta: { assist: a } }));
    if (a.status === 'working' && !a.started) { a.started = true; checkActionBlock(a, kind, json).then(() => holder.replaceChildren(assistEl({ meta: { assist: a } }))); }
    box.append(holder);
  }
  return box;
}
function assistEl(m) {
  const a = m.meta.assist;
  if (a.status === 'working') return el('div', { class: 'muted small', role: 'status' }, a.kind === 'event' ? 'Preparing the event…' : 'Writing the e-mail…');
  if (a.status === 'stopped') return el('div', { class: 'muted small' }, 'Stopped.');
  if (a.status === 'error') {
    return el('div', { class: 'assist-card' },
      el('div', { class: 'err' }, a.error),
      el('div', { class: 'row' },
        a.setup === 'mail' ? el('button', { class: 'btn', type: 'button', onclick: () => { show('settings'); editMailAccount({}); } }, icon('plus'), 'Add mail account') : null,
        a.fromModel ? null : chatInstead(a)));
  }
  const d = a.draft;
  if (a.kind === 'event') {
    return el('div', { class: 'assist-card' },
      a.saved ? null : el('div', { class: 'assist-head' }, icon('calendar'), 'Event ready: nothing is saved yet'),
      el('div', { class: 'assist-title', 'data-no-i18n': '' }, d.summary),
      el('div', { 'data-no-i18n': '' }, eventWhen(d)),
      d.location ? el('div', { class: 'muted small', 'data-no-i18n': '' }, d.location) : null,
      d.description ? el('div', { class: 'muted small', 'data-no-i18n': '' }, d.description) : null,
      !a.saved && eventIsPast(d) ? el('div', { class: 'err small' }, icon('alert'), 'This date is in the past. Check it before saving, or tell Sunak the date again.') : null,
      a.saved ? el('div', { class: 'ok small' }, icon('check-circle'), tr('Saved in {calendar} ✓', { calendar: a.savedIn }))
        : el('div', { class: 'row' },
          el('button', { class: 'btn primary', type: 'button', onclick: (ev) => saveChatEvent(a, ev.currentTarget) }, 'Save'),
          el('button', { class: 'btn', type: 'button', title: 'Open the event form to change it', onclick: () => editChatEvent(a) }, 'Edit'),
          a.fromModel ? null : chatInstead(a)));
  }
  return el('div', { class: 'assist-card' },
    el('div', { class: 'assist-head' }, icon('mail'), 'E-mail ready: nothing is sent'),
    el('div', { 'data-no-i18n': '' }, el('b', {}, `${tr('To')}: `), d.to || (d.to_name ? `${d.to_name} (${tr('address missing')})` : tr('address missing'))),
    el('div', { 'data-no-i18n': '' }, el('b', {}, `${tr('Subject')}: `), d.subject),
    el('pre', { class: 'assist-body', 'data-no-i18n': '' }, d.body),
    el('div', { class: 'row' },
      el('button', { class: 'btn primary', type: 'button', title: 'Opens the compose form; sending needs your click and a confirmation there', onclick: () => openChatMail(a) }, 'Open in Mail'),
      el('button', { class: 'btn', type: 'button', onclick: () => navigator.clipboard.writeText(d.body).then(() => toast('Copied')) }, 'Copy text'),
      a.fromModel ? null : chatInstead(a)));
}

/* ---------------- Tools (MCP) ----------------
   The model calls the tools of the MCP servers: steps (tool calls) appear between its text and every
   call waits for a click. See sunak/toolrun.py. */
const isAdmin = () => !!state.settings?.profile?.admin;
// tools (plug button) of the MCP servers (Settings → Tools); every call asks first
const mcpReady = () => isAdmin() && (state.settings?.mcp_servers || []).some((m) => m.enabled);
const mcpOn = () => mcpReady() && store.get('sunak-mcp') === '1';
function renderToolsToggle() {
  const m = $('#mcpToggle');
  m.classList.toggle('hidden', !mcpReady());
  m.setAttribute('aria-pressed', String(mcpOn()));
  m.title = mcpOn() ? 'Tools (MCP) on: the model may use your MCP servers, after asking' : 'Tools (MCP): let the model use your MCP servers';
  $('#toolsBar').classList.toggle('hidden', !mcpOn());
}
$('#mcpToggle').onclick = () => {
  store.set('sunak-mcp', mcpOn() ? '0' : '1');
  renderToolsToggle();
};
$('#toolsRevoke').onclick = async () => {
  if (state.session?.id) await api('/api/tools/revoke', { method: 'POST', body: { session_id: state.session.id } }).catch((e) => toast(e.message));
  toast('Sunak asks again before every tool call in this chat');
};

const STEP_ICONS = { running: 'clock', waiting: 'help', done: 'check-circle', error: 'alert', denied: 'hand', stopped: 'stop' };
// one tool call; with onDecide it is a question with Allow / Allow in this chat / Deny
// `command` and `diff` only exist in steps of chats stored before 0.13.0 (the removed agent mode)
function diffEl(diff) {
  return el('pre', { class: 'diff' }, diff.split('\n').map((line) => el('span', {
    class: line.startsWith('@@') ? 'hunk' : /^\+(?!\+\+ )/.test(line) ? 'add' : /^-(?!-- )/.test(line) ? 'del' : '' }, line + '\n')));
}
function stepEl(st, onDecide) {
  const status = onDecide ? 'waiting' : st.status;
  const kids = [];
  if (st.command) kids.push(el('pre', { class: 'cmd' }, `$ ${st.command}`));
  if (st.input) kids.push(el('pre', { class: 'cmd' }, st.input));
  if (st.diff) kids.push(diffEl(st.diff));
  if (st.output && !onDecide) kids.push(el('pre', { class: 'step-out' }, st.output));
  const box = el('details', { class: `step ${status}`, open: !!onDecide || status === 'error' },
    el('summary', {}, el('span', { class: 'step-icon' }, icon(STEP_ICONS[status] || 'dot')), el('code', {}, st.title || st.tool)), kids);
  if (onDecide) {
    box.append(el('div', { class: 'row step-actions' },
      el('span', { class: 'muted small' }, 'Use this tool?'),
      el('button', { class: 'btn primary', type: 'button', onclick: () => onDecide('allow') }, 'Allow'),
      el('button', { class: 'btn', type: 'button', onclick: () => onDecide('always'),
        title: 'Don’t ask again in this chat until Sunak restarts or you click “Ask again”' }, tr('Allow {tool} in this chat', { tool: st.mcp_tool || st.tool })),
      el('button', { class: 'btn', type: 'button', onclick: () => onDecide('deny') }, 'Deny')));
  }
  return box;
}
function toolsEl(a) {
  const box = el('div', { class: 'tools-run' });
  for (const p of a.parts || []) {
    if (p.step) box.append(stepEl(p.step));
    else if (p.text) box.append(el('div', { class: 'md', html: mdChat(p.text) }));
  }
  return box;
}

async function runTools(payload, localUserMsg) {
  const s = state.session;
  if (localUserMsg) s.messages.push(localUserMsg);
  s.messages.push({ role: 'assistant', content: '', model: currentModel(), meta: { tools: { parts: [] } } });
  const ctrl = new AbortController();
  state.busy = ctrl;
  $('#sendBtn').textContent = 'Stop';
  renderMessages();
  const box = $('#messages');
  const target = box.lastElementChild.querySelector('.tools-run');
  target.classList.add('typing');
  const steps = {};
  let cur = null, pending = false, error = null, stopped = false, qnote = null;
  const scroll = () => { if (box.scrollHeight - box.scrollTop - box.clientHeight < 160) box.scrollTop = box.scrollHeight; };
  const paint = () => { pending = false; if (cur) cur.el.innerHTML = mdChat(cur.raw); scroll(); };
  const endText = () => { if (cur) { if (cur.thinking) cur.raw += '</think>'; cur.el.innerHTML = mdChat(cur.raw); cur = null; } };
  const showStep = (st, ask) => {
    const node = stepEl(st, ask && (async (decision) => {
      node.querySelectorAll('.step-actions button').forEach((b) => (b.disabled = true));
      try { await api('/api/tools/confirm', { method: 'POST', body: { run: state.toolRun, id: st.id, decision } }); }
      catch (e) { toast(e.message); }
    }));
    if (steps[st.id]) steps[st.id].replaceWith(node); else target.append(node);
    steps[st.id] = node;
    if (ask) node.scrollIntoView({ block: 'nearest' }); else scroll();
  };
  try {
    await stream('/api/tools', { session_id: s.id, model: currentModel(), persona: currentPersona(), ...payload }, (ev) => {
      if (ev.type === 'start') { s.title = ev.title; $('#viewTitle').textContent = ev.title; state.toolRun = ev.run; }
      else if (ev.type === 'think' || ev.type === 'text') {
        if (!cur) { cur = { raw: '', thinking: false, el: el('div', { class: 'md' }) }; target.append(cur.el); }
        if (ev.type === 'think' && !cur.thinking) { cur.raw += '<think>'; cur.thinking = true; }
        if (ev.type === 'text' && cur.thinking) { cur.raw += '</think>\n\n'; cur.thinking = false; }
        cur.raw += ev.t;
        if (!pending) { pending = true; requestAnimationFrame(paint); }
      } else if (ev.type === 'step' || ev.type === 'step_done') { endText(); showStep(ev); }
      else if (ev.type === 'confirm') showStep(ev, true);
      else if (ev.type === 'queued') {
        qnote?.remove(); qnote = null;
        if (ev.position > 0) { endText(); qnote = el('p', { class: 'notice muted small' }, icon('clock'), queueText(ev.position)); target.append(qnote); }
      }
      else if (ev.type === 'notice') { endText(); target.append(el('p', { class: 'notice muted small' }, icon('info'), ev.t)); }
      else if (ev.type === 'done') stopped = !!ev.stopped;
      else if (ev.type === 'error') error = ev.error;
    }, ctrl.signal);
  } catch (e) {
    if (e.name === 'AbortError') stopped = true;
    else error = e.message;
  }
  endText();
  state.busy = null;
  state.toolRun = null;
  $('#sendBtn').textContent = 'Send';
  loadSessions();
  if (state.session !== s) return;
  // after Stop the server saves what was done a moment later
  let fresh = null;
  for (let i = 0; i < (stopped ? 6 : 1); i++) {
    try { fresh = await api(`/api/sessions/${s.id}`); } catch (e) { break; }
    if (!stopped || fresh.messages.at(-1)?.role === 'assistant') break;
    await new Promise((r) => setTimeout(r, 400));
  }
  if (state.session !== s || state.busy) return;
  if (fresh) state.session = fresh;
  renderMessages();
  if (error) $('#messages').append(el('div', { class: 'msg' }, el('div', { class: 'avatar warn' }, icon('alert')), el('div', { class: 'body err' }, error)));
  $('#messages').scrollTop = $('#messages').scrollHeight;
}

function regenerate(m) {
  state.session.messages = state.session.messages.filter((x) => x.id < m.id);
  runChat({ truncate_from: m.id });
}
function editMessage(m) {
  const text = prompt('Edit your message:', m.content);
  if (text === null || !(text.trim() || m.meta?.images?.length)) return;
  state.session.messages = state.session.messages.filter((x) => x.id < m.id);
  const refs = m.meta?.images || [];
  runChat({ truncate_from: m.id, content: text.trim(), image_refs: refs },
    { role: 'user', content: text.trim(), localImages: refs.map((n) => `/api/images/${n}`) });
}

/* attachments: the text of each file (also PDF, Word, …) is inlined into the prompt */
const MAX_UPLOAD = 15 * 1024 * 1024;
const MAX_ATTACH_CHARS = 60000;
function fileData(f) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result.slice(r.result.indexOf(',') + 1));
    r.onerror = () => reject(new Error(tr('Could not read {name}', { name: f.name })));
    r.readAsDataURL(f);
  });
}
function dropAttachment(a) {
  const k = state.attachments.indexOf(a);
  if (k >= 0) state.attachments.splice(k, 1); // it may already be removed by its remove button
}
/* images go to the model as pictures (vision models), shrunk in the browser to at most 1568 px */
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
const MAX_IMAGES = 4, IMG_SIDE = 1568, IMG_BYTES = 3.5 * 1024 * 1024;
function loadImg(src) {
  return new Promise((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error(tr('this image cannot be read')));
    i.src = src;
  });
}
async function prepareImage(f) {
  const url = URL.createObjectURL(f);
  try {
    const img = await loadImg(url);
    const scale = Math.min(1, IMG_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    if (scale === 1 && f.size <= IMG_BYTES) {
      const data = await fileData(f);
      return { data, url: `data:${f.type};base64,${data}` };
    }
    const c = document.createElement('canvas');
    c.width = Math.round(img.naturalWidth * scale); c.height = Math.round(img.naturalHeight * scale);
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, c.width, c.height);
    let out = f.type === 'image/png' ? c.toDataURL('image/png') : '';
    if (!out || out.length > IMG_BYTES * 1.37) { // photos (and big PNGs) as JPEG on white
      ctx.globalCompositeOperation = 'destination-over'; ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);
      out = c.toDataURL('image/jpeg', 0.88);
    }
    return { data: out.slice(out.indexOf(',') + 1), url: out };
  } finally { URL.revokeObjectURL(url); }
}
async function attachImage(f) {
  if (state.attachments.filter((a) => a.image).length >= MAX_IMAGES) { toast(tr('At most {n} images per message', { n: MAX_IMAGES })); return; }
  const a = { name: f.name || 'image.png', image: true, loading: true };
  state.attachments.push(a);
  renderAttachments();
  try { Object.assign(a, await prepareImage(f), { loading: false }); } catch (e) { dropAttachment(a); toast(`${a.name}: ${e.message}`); }
  renderAttachments();
}
async function attachFiles(files) {
  for (const f of files) {
    if (IMAGE_TYPES.includes(f.type)) { await attachImage(f); continue; }
    if (f.size > MAX_UPLOAD) { toast(tr('{name} is too big (max 15 MB)', { name: f.name })); continue; }
    const a = { name: f.name, text: '', loading: true };
    state.attachments.push(a);
    renderAttachments();
    try {
      const r = await api('/api/extract', { method: 'POST', body: { name: f.name, data: await fileData(f) } });
      if (r.text.length > MAX_ATTACH_CHARS) {
        dropAttachment(a);
        toast(tr('{name} is long ({k}k characters). Add it to your knowledge base instead?', { name: f.name, k: Math.round(r.text.length / 1000) }),
          { label: 'Add to knowledge', fn: () => uploadKb([f]).then(() => setKb(true)) });
      } else { a.text = r.text; a.loading = false; }
    } catch (e) {
      dropAttachment(a);
      toast(e.message);
    }
    renderAttachments();
  }
}
$('#fileInput').onchange = (e) => { attachFiles([...e.target.files]); e.target.value = ''; };
function renderAttachments() {
  const box = $('#attachments');
  box.innerHTML = '';
  state.attachments.forEach((a, i) => box.append(el('span', { class: 'chip' },
    a.image && a.url ? el('img', { class: 'thumb', src: a.url, alt: '' }) : icon(a.loading ? 'clock' : a.image ? 'image' : 'file'), a.name,
    el('button', { type: 'button', 'aria-label': tr('Remove {name}', { name: a.name }), onclick: () => { state.attachments.splice(i, 1); renderAttachments(); } }, icon('x', 'solo')))));
}
// paste a screenshot straight into the message box
promptEl.addEventListener('paste', (e) => {
  const pics = [...(e.clipboardData?.files || [])].filter((f) => IMAGE_TYPES.includes(f.type));
  if (!pics.length) return;
  e.preventDefault();
  attachFiles(pics);
});
// drop files anywhere on the chat to attach them
const chatView = $('#view-chat');
chatView.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); chatView.classList.add('drag'); } });
chatView.addEventListener('dragleave', (e) => { if (!chatView.contains(e.relatedTarget)) chatView.classList.remove('drag'); });
chatView.addEventListener('drop', (e) => { e.preventDefault(); chatView.classList.remove('drag'); attachFiles([...e.dataTransfer.files]); });

/* ---------------- Voice ----------------
   Speech input (microphone): a local Whisper server (recorded here, sent as 16 kHz WAV, see sunak/speech.py) or the
   browser's speech recognition, on this device only unless Settings → Voice allows more.
   Reading aloud (speaker): the browser's speech synthesis, preferably with a voice that runs on this device. */
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const tts = window.speechSynthesis;
const speechLang = () => ({ de: 'de-DE', en: 'en-US' })[sunakLang] || navigator.language || 'en-US';
const voice = { rec: null, recorder: null, busy: false, speaking: null };
const speechMode = () => state.settings?.speech_input || 'local';
function renderMic() {
  const b = $('#micBtn'), on = !!(voice.rec || voice.recorder);
  b.classList.toggle('hidden', speechMode() === 'off');
  b.classList.toggle('recording', on);
  b.setAttribute('aria-pressed', String(on));
  b.disabled = voice.busy;
  b.title = voice.busy ? tr('Turning speech into text…') : on ? tr('Stop recording') : tr('Speak instead of typing');
}
function addSpoken(text) {
  const before = promptEl.value.trim() ? `${promptEl.value.trimEnd()} ` : '';
  promptEl.value = before + text;
  autosize();
}
$('#micBtn').onclick = async () => {
  if (voice.rec) { voice.rec.stop(); return; }
  if (voice.recorder) { voice.recorder.stop(); return; }
  if (voice.busy) return;
  if (!window.isSecureContext) { toast(tr('The microphone only works on this computer (or over https). On a phone, use the dictation of its keyboard.')); return; }
  try {
    if (state.settings.whisper_url) await recordWhisper();
    else if (SpeechRec && (speechMode() === 'browser' || await onDeviceReady())) startRecognition(speechMode() !== 'browser');
    else toast(tr('Set up speech input in Settings → Voice: a local Whisper server, or allow the browser’s recognition.'),
      { label: tr('Open'), fn: () => show('settings') });
  } catch (e) {
    toast(e.name === 'NotAllowedError' ? tr('Sunak may not use the microphone. Allow it in the browser’s site settings.') : e.message);
  }
  renderMic();
};
// the browser's recognition on this device (Google Chrome 139+ can download a speech model for it; plain
// Chromium has the same functions without the speech service, and asking there crashed the tab in tests)
async function onDeviceReady() {
  const chrome = (navigator.userAgentData?.brands || []).some((b) => b.brand === 'Google Chrome');
  if (!chrome || typeof SpeechRec.available !== 'function') return false;
  const opts = { langs: [speechLang()], processLocally: true };
  const st = await SpeechRec.available(opts).catch(() => 'unavailable');
  if (st === 'available') return true;
  if (st !== 'downloadable' && st !== 'downloading') return false;
  toast(tr('Downloading the speech model of your browser…'));
  return !!(await SpeechRec.install(opts).catch(() => false));
}
function startRecognition(local) {
  const rec = new SpeechRec();
  rec.lang = speechLang();
  rec.interimResults = true;
  rec.continuous = true;
  if (local) rec.processLocally = true;
  const before = promptEl.value;
  rec.onresult = (e) => {
    promptEl.value = before;
    addSpoken([...e.results].map((r) => r[0].transcript).join('').trim());
  };
  rec.onerror = (e) => { if (e.error !== 'aborted' && e.error !== 'no-speech') toast(tr('Speech recognition failed: {error}', { error: e.error })); };
  rec.onend = () => { voice.rec = null; renderMic(); promptEl.focus(); };
  voice.rec = rec;
  rec.start();
}
async function recordWhisper() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const rec = new MediaRecorder(stream), chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    voice.recorder = null; voice.busy = true; renderMic();
    try {
      const r = await api('/api/transcribe', { method: 'POST', body: { audio: await toWav(new Blob(chunks, { type: rec.mimeType })) } });
      if (r.text) addSpoken(r.text); else toast(tr('Nothing was understood'));
    } catch (e) { toast(e.message); }
    voice.busy = false; renderMic(); promptEl.focus();
  };
  voice.recorder = rec;
  rec.start();
}
// any recording (webm, ogg, mp4) → 16 kHz mono 16-bit WAV as base64, which every Whisper server reads
async function toWav(blob) {
  const ctx = new AudioContext();
  let audio;
  try { audio = await ctx.decodeAudioData(await blob.arrayBuffer()); } finally { ctx.close(); }
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(audio.duration * rate)), rate);
  const src = off.createBufferSource();
  src.buffer = audio; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const view = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (at, s) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  str(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  str(36, 'data'); view.setUint32(40, pcm.length * 2, true);
  pcm.forEach((v, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
  const bytes = new Uint8Array(view.buffer);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function pickVoice() {
  const all = tts.getVoices(), chosen = all.find((v) => v.voiceURI === store.get('sunak-voice', ''));
  if (chosen) return chosen;
  const lang = speechLang().slice(0, 2);
  return all.find((v) => v.localService && v.lang.toLowerCase().startsWith(lang)) || all.find((v) => v.localService) || null;
}
// what an answer sounds like without Markdown, code, links and [1] citations, in pieces the browser reads reliably
function speakable(text) {
  const plain = text.replace(/<think>[\s\S]*?(<\/think>|$)/g, '')
    .replace(/```[\s\S]*?(```|$)/g, ` ${tr('(code)')} `)
    .replace(/`([^`]*)`/g, '$1').replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\s*\[\d+\]/g, '')
    .replace(/https?:\/\/\S+/g, '').replace(/^\s{0,3}(#{1,6}|[-*+]|\d+[.)]|>)\s+/gm, '').replace(/[*_~|#]+/g, '');
  const pieces = [];
  for (const s of plain.match(/[^.!?;:\n]+[.!?;:]*/g) || []) {
    const t = s.trim();
    if (!t) continue;
    if (pieces.length && pieces.at(-1).length + t.length < 200) pieces[pieces.length - 1] += ` ${t}`; else pieces.push(t);
  }
  return pieces;
}
function speak(text, onEnd) {
  tts.cancel();
  const v = pickVoice(), pieces = speakable(text);
  pieces.forEach((p, i) => {
    const u = new SpeechSynthesisUtterance(p);
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = speechLang();
    if (i === pieces.length - 1) { u.onend = onEnd; u.onerror = onEnd; }
    tts.speak(u);
  });
  return pieces.length > 0;
}
function speakButton(m) {
  const key = m.id || m;
  const b = el('button', { class: `speak-btn${voice.speaking === key ? ' on' : ''}`, title: tr('Read aloud'), 'aria-label': tr('Read aloud'),
    onclick: () => {
      const again = voice.speaking === key;
      tts.cancel(); voice.speaking = null;
      $$('.speak-btn.on').forEach((x) => x.classList.remove('on'));
      if (again) return;
      if (speak(m.content, () => { if (voice.speaking === key) { voice.speaking = null; $$('.speak-btn.on').forEach((x) => x.classList.remove('on')); } })) {
        voice.speaking = key;
        b.classList.add('on');
      }
    } }, icon('volume', 'solo'));
  return b;
}
function renderVoices() {
  const sel = $('#ttsVoice');
  sel.replaceChildren(el('option', { value: '' }, tr('Automatic (a voice on this device in the language of the interface)')),
    ...(tts ? tts.getVoices() : []).map((v) => el('option', { value: v.voiceURI, 'data-no-i18n': '' },
      `${v.name} (${v.lang})${v.localService ? '' : ` · ${tr('online')}`}`)));
  sel.value = store.get('sunak-voice', '');
  sel.disabled = $('#ttsTest').disabled = !tts;
}
if (tts) tts.onvoiceschanged = renderVoices;
$('#ttsVoice').onchange = (e) => store.set('sunak-voice', e.target.value);
$('#ttsTest').onclick = () => speak(tr('Hi, I am Sunak. This is how I sound.'));

/* ---------------- Knowledge base ---------------- */
const kbOn = () => (state.session ? !!state.session.use_kb : store.get('sunak-kb') === '1');
function renderKbToggle() {
  const b = $('#kbToggle');
  b.setAttribute('aria-pressed', String(kbOn()));
  b.title = kbOn() ? 'Knowledge base on: answers use your files' : 'Answer with my knowledge base';
}
async function setKb(on) {
  store.set('sunak-kb', on ? '1' : '0');
  if (state.session) {
    state.session.use_kb = on;
    if (state.session.id) await api(`/api/sessions/${state.session.id}`, { method: 'PATCH', body: { use_kb: on } });
  }
  renderKbToggle(); renderWebToggle();
}
$('#kbToggle').onclick = async () => {
  const on = !kbOn();
  await setKb(on);
  if (on) {
    await loadKbData();
    if (!state.kb.files.length) toast('Your knowledge base is empty.', { label: 'Add files', fn: () => show('knowledge') });
    else toast(trn(state.kb.files.length, 'Knowledge base on ({n} file)', 'Knowledge base on ({n} files)'));
  } else toast('Knowledge base off');
};
function sourcesEl(sources) {
  const box = el('div', { class: 'sources kb-sources' });
  if (!sources.length) box.append(el('span', { class: 'muted small' }, icon('book'), tr('No matching files')));
  sources.forEach((src) => box.append(el('button', { class: 'chip', type: 'button', title: tr('Show file'),
    onclick: () => { show('knowledge'); previewKb(src.id); } }, icon('book'), src.name)));
  return box;
}
/* ---------------- Web search in the chat ----------------
   Per chat like the knowledge base: the server searches (DuckDuckGo or SEARXNG_URL), reads the top
   pages and gives them to the model as numbered sources. */
const webOn = () => (state.session ? !!state.session.use_web : store.get('sunak-web') === '1');
function renderWebToggle() {
  const b = $('#webToggle');
  b.setAttribute('aria-pressed', String(webOn()));
  b.title = webOn() ? 'Web search on: answers use current web pages' : 'Search the web for answers';
}
async function setWeb(on) {
  store.set('sunak-web', on ? '1' : '0');
  if (state.session) {
    state.session.use_web = on;
    if (state.session.id) await api(`/api/sessions/${state.session.id}`, { method: 'PATCH', body: { use_web: on } });
  }
  renderWebToggle();
}
$('#webToggle').onclick = async () => {
  const on = !webOn();
  await setWeb(on);
  toast(on ? 'Web search on: your question goes to the search engine' : 'Web search off');
};
function webSourcesEl(web) {
  return el('div', { class: 'sources kb-sources' },
    el('span', { class: 'muted small', title: tr('Searched for: {query}', { query: web.query }) }, icon('globe', 'solo')),
    web.sources.map((src, i) => el('a', { class: 'chip', href: src.url, target: '_blank', rel: 'noopener noreferrer', title: src.url },
      `[${i + 1}] ${src.title || new URL(src.url).hostname}`)));
}

async function loadKbData() {
  state.kb = await api('/api/knowledge');
}
async function loadKb() {
  await loadKbData();
  const box = $('#kbList');
  box.innerHTML = '';
  if (!state.kb.files.length) { box.append(el('p', { class: 'muted' }, 'No files yet.')); return; }
  box.append(el('p', { class: 'muted small' }, `${trn(state.kb.files.length, '{n} file', '{n} files')} · ${tr('{k}k characters', { k: Math.round(state.kb.chars / 1000) })}`));
  for (const f of state.kb.files) {
    box.append(el('div', { class: 'kb-item' },
      el('button', { class: 'kb-name', title: 'Show text', onclick: () => previewKb(f.id) }, icon('file'), f.name),
      el('span', { class: 'muted small' }, `${(f.size / 1024).toFixed(f.size < 10240 ? 1 : 0)} KB · ${Math.round(f.chars / 100) / 10}k chars`),
      el('button', { class: 'icon-btn', title: 'Remove', onclick: async () => {
        if (!confirm(tr('Remove “{name}” from your knowledge base?', { name: f.name }))) return;
        await api(`/api/knowledge/${f.id}`, { method: 'DELETE' });
        $('#kbPreview').classList.add('hidden');
        loadKb();
      } }, icon('trash'))));
  }
}
async function previewKb(id) {
  const box = $('#kbPreview');
  try {
    const f = await api(`/api/knowledge/${id}`);
    box.innerHTML = '';
    box.append(el('div', { class: 'row' }, el('h3', { style: 'margin:0;flex:1' }, f.name),
      el('button', { class: 'icon-btn', title: 'Close', onclick: () => box.classList.add('hidden') }, icon('x'))),
      el('pre', { class: 'kb-text' }, f.text.length > 20000 ? `${f.text.slice(0, 20000)}\n\n… (${tr('{k}k characters in total', { k: Math.round(f.text.length / 1000) })})` : f.text));
    box.classList.remove('hidden');
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { toast(e.message); }
}
async function uploadKb(files) {
  const box = $('#kbUploads');
  let added = 0;
  for (const f of files) {
    const line = el('div', { class: 'kb-upload muted small' }, icon('clock'), tr('Reading {name}…', { name: f.name }));
    box.append(line);
    if (f.size > MAX_UPLOAD) { line.replaceChildren(icon('x'), tr('{name} is too big (max 15 MB)', { name: f.name })); line.classList.add('err'); continue; }
    try {
      const r = await api('/api/knowledge', { method: 'POST', body: { name: f.name, data: await fileData(f) } });
      line.remove();
      added++;
      toast(tr('Added {name}', { name: r.name }));
    } catch (e) { line.replaceChildren(icon('x'), e.message); line.classList.add('err'); }
  }
  if (state.view === 'knowledge') loadKb(); else loadKbData();
  return added;
}
$('#kbInput').onchange = (e) => { uploadKb([...e.target.files]); e.target.value = ''; };
const kbDrop = $('#kbDrop');
kbDrop.addEventListener('dragover', (e) => { e.preventDefault(); kbDrop.classList.add('drag'); });
kbDrop.addEventListener('dragleave', () => kbDrop.classList.remove('drag'));
kbDrop.addEventListener('drop', (e) => { e.preventDefault(); kbDrop.classList.remove('drag'); $('#kbUploads').innerHTML = ''; uploadKb([...e.dataTransfer.files]); });
let kbSearchTimer = null;
$('#kbSearch').oninput = () => {
  clearTimeout(kbSearchTimer);
  kbSearchTimer = setTimeout(async () => {
    const q = $('#kbSearch').value.trim();
    const box = $('#kbResults');
    box.innerHTML = '';
    if (!q) return;
    const hits = await api(`/api/knowledge/search?q=${encodeURIComponent(q)}`);
    if (!hits.length) box.append(el('p', { class: 'muted small' }, 'Nothing found.'));
    hits.forEach((h) => box.append(el('button', { class: 'kb-hit', onclick: () => previewKb(h.file_id) },
      el('b', {}, h.name), el('span', { class: 'muted small' }, h.snippet))));
  }, 250);
};

/* ---------------- Mail ---------------- */
// Reading never marks mail as read; sending and saving drafts happen only on a click.
state.mail = { accounts: [], presets: {}, folders: [], items: [], more: false, open: null, compose: null, seq: 0 };
const mailAcc = () => state.mail.accounts.find((a) => a.id === $('#mailAccount').value);
const mailFolder = () => $('#mailFolder').value || 'INBOX';
const addrs = (s) => (s || '').match(/[^\s<>,;"]+@[^\s<>,;"]+/g) || [];
const who = (m) => m.from_name || m.from_addr || '(unknown)';
function mailDate(ts, long) {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  if (long) return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  return d.toDateString() === now.toDateString() ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : '2-digit' });
}
function mailAsText(m) {
  const head = [`From: ${m.from_name ? `${m.from_name} <${m.from_addr}>` : m.from_addr}`, `To: ${m.to || ''}`];
  if (m.cc) head.push(`Cc: ${m.cc}`);
  if (m.date) head.push(`Date: ${mailDate(m.date, true)}`);
  head.push(`Subject: ${m.subject}`);
  if (m.attachments?.length) head.push(`Attachments: ${m.attachments.map((a) => a.name).join(', ')}`);
  return `${head.join('\n')}\n\n${m.text.length > 12000 ? `${m.text.slice(0, 12000)}\n[… shortened]` : m.text}`;
}
async function loadMailAccounts() {
  const r = await api('/api/mail/accounts');
  state.mail.accounts = r.accounts;
  state.mail.presets = r.presets;
}
async function loadMailView() {
  try { await loadMailAccounts(); } catch (e) { toast(e.message); return; }
  const sel = $('#mailAccount');
  const keep = sel.value || store.get('sunak-mail-account');
  sel.innerHTML = '';
  state.mail.accounts.forEach((a) => sel.append(el('option', { value: a.id }, a.name ? `${a.name} · ${a.email}` : a.email)));
  if (!state.mail.accounts.length) {
    $('#mailItems').innerHTML = '';
    $('#mailItems').append(el('div', { class: 'card' }, el('p', {}, 'No mail account linked yet.'),
      el('button', { class: 'btn primary', onclick: () => { show('settings'); editMailAccount({}); } }, icon('plus'), 'Add mail account')));
    showMailPane('empty');
    return;
  }
  sel.value = state.mail.accounts.some((a) => a.id === keep) ? keep : state.mail.accounts[0].id;
  await loadFolders();
  loadMailList();
}
async function loadFolders() {
  const fsel = $('#mailFolder');
  const keep = fsel.dataset.account === $('#mailAccount').value ? fsel.value : 'INBOX';
  fsel.innerHTML = '';
  fsel.append(el('option', { value: 'INBOX' }, 'Inbox'));
  fsel.dataset.account = $('#mailAccount').value;
  try { state.mail.folders = await api(`/api/mail/${$('#mailAccount').value}/folders`); } catch (e) { toast(e.message); return; }
  fsel.innerHTML = '';
  state.mail.folders.forEach((f) => fsel.append(el('option', { value: f.id }, f.name)));
  fsel.value = state.mail.folders.some((f) => f.id === keep) ? keep : (state.mail.folders[0]?.id || 'INBOX');
}
async function loadMailList(older) {
  const box = $('#mailItems');
  const seq = ++state.mail.seq;
  const q = new URLSearchParams({ folder: mailFolder(), q: $('#mailSearch').value.trim() });
  if ($('#mailUnread').getAttribute('aria-pressed') === 'true') q.set('unread', '1');
  if (older && state.mail.items.length) q.set('before', state.mail.items[state.mail.items.length - 1].uid);
  if (!older) { box.innerHTML = ''; box.append(el('p', { class: 'muted small' }, 'Loading…')); }
  let r;
  try { r = await api(`/api/mail/${$('#mailAccount').value}/messages?${q}`); } catch (e) {
    if (seq !== state.mail.seq) return;
    box.innerHTML = ''; box.append(el('p', { class: 'err' }, e.message)); return;
  }
  if (seq !== state.mail.seq) return; // a newer request is on its way
  state.mail.items = older ? state.mail.items.concat(r.messages) : r.messages;
  state.mail.more = r.more;
  renderMailList();
}
function renderMailList() {
  const box = $('#mailItems');
  box.innerHTML = '';
  if (!state.mail.items.length) box.append(el('p', { class: 'muted small' }, 'No e-mails here.'));
  for (const m of state.mail.items) {
    box.append(el('button', { type: 'button', class: `mail-item${m.seen ? '' : ' unread'}${state.mail.open?.uid === m.uid ? ' active' : ''}`,
      onclick: () => openMail(m.uid) },
    el('span', { class: 'mi-top' }, el('span', { class: 'mi-from' }, who(m)), el('span', { class: 'muted small' }, mailDate(m.date))),
    el('span', { class: 'mi-subj' }, m.flagged ? icon('star') : '', m.answered ? icon('reply') : '', m.subject)));
  }
  if (state.mail.more) box.append(el('button', { class: 'btn wide', type: 'button', onclick: () => loadMailList(true) }, 'Load older'));
}
function showMailPane(which) {
  $('#mailEmpty').classList.toggle('hidden', which !== 'empty');
  $('#mailReader').classList.toggle('hidden', which !== 'reader');
  $('#mailCompose').classList.toggle('hidden', which !== 'compose');
}
async function openMail(uid) {
  if (state.mail.compose && !confirmDiscard()) return;
  const r = $('#mailReader');
  r.innerHTML = '';
  r.append(el('p', { class: 'muted' }, 'Loading…'));
  showMailPane('reader');
  const aid = $('#mailAccount').value, folder = mailFolder();
  let m;
  try { m = await api(`/api/mail/${aid}/message?${new URLSearchParams({ folder, uid })}`); } catch (e) {
    r.innerHTML = ''; r.append(el('p', { class: 'err' }, e.message)); return;
  }
  m.account = aid;
  state.mail.open = m;
  renderMailList();
  renderReader(m);
}
function renderReader(m) {
  const r = $('#mailReader');
  r.innerHTML = '';
  const aiBox = el('div', { class: 'md mail-ai hidden' });
  const att = m.attachments.map((a, i) => el('a', { class: 'chip', download: a.name, title: `${a.type} · ${Math.ceil(a.size / 1024)} KB`,
    href: `/api/mail/${m.account}/attachment?${new URLSearchParams({ folder: m.folder, uid: m.uid, i })}` }, icon('paperclip'), a.name));
  r.append(...[el('h2', { class: 'mail-subject' }, m.subject),
    el('div', { class: 'mail-head small' },
      el('div', {}, el('b', {}, who(m)), m.from_name ? el('span', { class: 'muted' }, ` <${m.from_addr}>`) : null),
      el('div', { class: 'muted' }, `${tr('To: {to}', { to: m.to })}${m.cc ? ` · Cc: ${m.cc}` : ''} · ${mailDate(m.date, true)}`)),
    el('div', { class: 'row' },
      el('button', { class: 'btn', type: 'button', onclick: () => replyTo(m, false) }, icon('reply'), 'Reply'),
      el('button', { class: 'btn', type: 'button', onclick: () => replyTo(m, true) }, icon('reply-all'), 'Reply all'),
      el('button', { class: 'btn', type: 'button', onclick: () => forward(m) }, icon('forward'), 'Forward'),
      el('button', { class: 'btn', type: 'button', onclick: () => mailAi('summarize', mailAsText(m), aiBox) }, icon('sparkles'), 'Summarize'),
      el('button', { class: 'btn', type: 'button', title: 'Attach this e-mail to a new chat and ask anything about it', onclick: () => askInChat(m) }, icon('chat'), 'Ask in chat'),
      el('button', { class: 'btn', type: 'button', title: 'The model reads the date out of this e-mail, you check it and save',
        onclick: () => { show('calendar'); calQuickAdd(`${tr('Sent: {date}', { date: m.date })}\n${mailAsText(m)}`.slice(0, 20000)); } }, icon('calendar'), 'Add to calendar')),
    mailActions(m),
    aiBox,
    att.length ? el('div', { class: 'sources' }, att) : null,
    el('div', { class: 'mail-body' }, m.text || tr('(no text)')),
    m.truncated ? el('p', { class: 'muted small' }, 'This e-mail is very long; only the beginning is shown.') : null].filter(Boolean));
  r.scrollTop = 0;
}
function mailActions(m) {
  const others = state.mail.folders.filter((f) => f.id !== m.folder);
  const sel = el('select', { 'aria-label': 'Move to folder', onchange: () => { const t = sel.value; sel.value = ''; if (t) moveMail(m, t); } },
    el('option', { value: '' }, 'Move to…'), ...others.map((f) => el('option', { value: f.id }, f.name)));
  return el('div', { class: 'row mail-actions' }, sel,
    el('button', { class: 'btn', type: 'button', onclick: () => deleteMail(m) }, icon('trash'), 'Delete'));
}
function mailGone(m, msg) {
  state.mail.items = state.mail.items.filter((x) => x.uid !== m.uid);
  if (state.mail.open?.uid === m.uid) { state.mail.open = null; showMailPane('empty'); }
  renderMailList();
  toast(msg);
}
async function moveMail(m, target) {
  try {
    const r = await api(`/api/mail/${m.account}/move`, { method: 'POST', body: { folder: m.folder, uids: [m.uid], target } });
    mailGone(m, tr('Moved to {folder} ✓', { folder: r.folder }));
  } catch (e) { toast(e.message); }
}
async function deleteMail(m) {
  const trash = state.mail.folders.find((f) => f.role === 'trash');
  const forever = !trash || trash.id === m.folder;
  if (!confirm(forever ? tr('Delete “{subject}” for good? This cannot be undone.', { subject: m.subject })
    : tr('Move “{subject}” to the Trash?', { subject: m.subject }))) return;
  try {
    const r = await api(`/api/mail/${m.account}/delete`, { method: 'POST', body: { folder: m.folder, uids: [m.uid], permanent: forever } });
    mailGone(m, r.permanent ? tr('Deleted for good ✓') : tr('Moved to {folder} ✓', { folder: r.folder }));
  } catch (e) { toast(e.message); }
}
async function mailAi(task, text, box, instruction = '', onText) {
  if (!currentModel()) { toast('Install or connect a model first'); return; }
  let raw = '', thinking = false, failed = null;
  if (box) { box.classList.remove('hidden'); box.classList.add('typing'); box.innerHTML = ''; }
  try {
    await stream('/api/mail/ai', { task, text, instruction, account: $('#mailAccount').value, model: currentModel() }, (ev) => {
      if (ev.type === 'think') { if (!thinking) { raw += '<think>'; thinking = true; } raw += ev.t; }
      else if (ev.type === 'text') { if (thinking) { raw += '</think>\n\n'; thinking = false; } raw += ev.t; if (onText) onText(ev.t); }
      else if (ev.type === 'error') failed = ev.error;
      if (box) box.innerHTML = md(raw);
    });
  } catch (e) { failed = e.message; }
  if (box) box.classList.remove('typing');
  if (failed) toast(tr('AI error: {error}', { error: failed }));
  return !failed;
}
function askInChat(m) {
  newChat();
  const name = `${tr('E-mail')}: ${m.subject}`.replace(/[`\n\r]/g, "'").slice(0, 120);
  state.attachments.push({ name, text: mailAsText(m).replace(/```/g, "'''") });
  renderAttachments();
  promptEl.focus();
  toast('E-mail attached. Ask anything about it, e.g. “What do they want from me?”');
}
$('#mailAccount').onchange = async () => {
  store.set('sunak-mail-account', $('#mailAccount').value);
  state.mail.open = null; showMailPane('empty');
  await loadFolders(); loadMailList();
};
$('#mailFolder').onchange = () => { state.mail.open = null; showMailPane('empty'); loadMailList(); };
let mailSearchTimer = null;
$('#mailSearch').oninput = () => { clearTimeout(mailSearchTimer); mailSearchTimer = setTimeout(() => loadMailList(), 500); };
$('#mailUnread').onclick = (e) => {
  const b = e.currentTarget;
  b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true'));
  loadMailList();
};
$('#mailRefresh').onclick = () => loadMailList();
$('#mailOverview').onclick = () => {
  if (!state.mail.items.length) return toast('No e-mails in this list');
  const list = state.mail.items.slice(0, 60).map((m) => `- ${m.seen ? '' : '[unread] '}${mailDate(m.date, true)} · ${who(m)} <${m.from_addr}> · ${m.subject}`).join('\n');
  if (state.mail.compose && !confirmDiscard()) return;
  state.mail.open = null;
  renderMailList();
  const r = $('#mailReader');
  const box = el('div', { class: 'md mail-ai' });
  r.innerHTML = '';
  r.append(el('h2', { class: 'mail-subject' }, icon('sparkles'), tr('Overview of {n} e-mails', { n: Math.min(60, state.mail.items.length) })),
    el('p', { class: 'muted small' }, 'Based on sender and subject only.'), box);
  showMailPane('reader');
  mailAi('overview', list, box);
};

/* compose: new mail, reply, forward */
function confirmDiscard() {
  const c = state.mail.compose;
  const dirty = c && ($('#mailBody').value.trim() !== (c.start || '').trim() || $('#mailTo').value.trim() !== (c.to || '')
    || c.files.length > (c.savedFiles || 0));
  if (dirty && !confirm('Discard this e-mail?')) return false;
  state.mail.compose = null;
  return true;
}
function openCompose(c) {
  if (!mailAcc()) { toast('Add a mail account first'); show('settings'); return; }
  if (state.mail.compose && !confirmDiscard()) return;
  c.files = c.files || [];
  state.mail.compose = c;
  renderComposeFiles();
  const acc = mailAcc();
  $('#mailFrom').textContent = tr('From: {from}', { from: acc.name ? `${acc.name} <${acc.email}>` : acc.email });
  $('#mailTo').value = c.to || '';
  $('#mailCc').value = c.cc || '';
  $('#mailBcc').value = '';
  $('#mailSubject').value = c.subject || '';
  $('#mailBody').value = c.start || '';
  $('#mailAiHint').value = '';
  $('#mailAiRow').classList.toggle('hidden', !c.original);
  showMailPane('compose');
  (c.to ? $('#mailBody') : $('#mailTo')).focus();
  $('#mailBody').setSelectionRange(0, 0);
}
const quote = (m) => `\n\n${tr('On {date}, {who} wrote:', { date: mailDate(m.date, true), who: who(m) })}\n${m.text.split('\n').map((l) => `> ${l}`).join('\n')}`;
const prefixed = (p, s) => (s.toLowerCase().startsWith(p.toLowerCase()) ? s : `${p} ${s}`);
function replyTo(m, all) {
  const me = mailAcc()?.email.toLowerCase();
  const to = addrs(m.reply_to || m.from_addr);
  const cc = all ? [...addrs(m.to), ...addrs(m.cc)].filter((a) => a.toLowerCase() !== me && !to.includes(a)) : [];
  openCompose({ to: to.join(', '), cc: [...new Set(cc)].join(', '), subject: prefixed('Re:', m.subject), start: quote(m),
    in_reply_to: m.message_id, references: m.references, original: m });
}
function forward(m) {
  const head = `\n\n---------- ${tr('Forwarded message')} ----------\n${mailAsText(m)}`;
  // the original's attachments go along (fetched by the server when sending); each can be removed
  openCompose({ subject: prefixed('Fwd:', m.subject), start: head,
    fwd: { folder: m.folder, uid: m.uid, list: m.attachments, keep: m.attachments.map((a, i) => i) } });
}
const MAIL_MAX_ATTACH = 17 * 1024 * 1024;
function composeSize(c) {
  return c.files.reduce((n, f) => n + f.size, 0) + (c.fwd ? c.fwd.keep.reduce((n, i) => n + c.fwd.list[i].size, 0) : 0);
}
function renderComposeFiles() {
  const c = state.mail.compose, box = $('#mailAttach');
  box.innerHTML = '';
  const chip = (name, size, drop) => el('span', { class: 'chip', title: `${Math.ceil(size / 1024)} KB` },
    icon('paperclip'), el('span', { 'data-no-i18n': '' }, name),
    el('button', { type: 'button', title: tr('Remove {name}', { name }), onclick: () => { drop(); renderComposeFiles(); } }, icon('x', 'solo')));
  if (c.fwd) c.fwd.keep.forEach((i) => box.append(chip(c.fwd.list[i].name, c.fwd.list[i].size, () => { c.fwd.keep = c.fwd.keep.filter((k) => k !== i); })));
  c.files.forEach((f) => box.append(chip(f.name, f.size, () => { c.files = c.files.filter((x) => x !== f); })));
}
$('#mailFiles').onchange = async (e) => {
  const c = state.mail.compose, input = e.target;
  for (const f of [...input.files]) {
    if (composeSize(c) + f.size > MAIL_MAX_ATTACH) { toast(tr('{name} is too large: at most 17 MB together', { name: f.name })); break; }
    try { c.files.push({ name: f.name, size: f.size, data: await fileData(f) }); } catch (err) { toast(err.message); }
  }
  input.value = '';
  renderComposeFiles();
};
$('#mailNew').onclick = () => openCompose({});
$('#mailClose').onclick = () => { if (confirmDiscard()) showMailPane(state.mail.open ? 'reader' : 'empty'); };
function composeData() {
  const c = state.mail.compose;
  return { to: $('#mailTo').value, cc: $('#mailCc').value, bcc: $('#mailBcc').value, subject: $('#mailSubject').value,
    body: $('#mailBody').value, in_reply_to: c.in_reply_to || '', references: c.references || '',
    attachments: c.files.map((f) => ({ name: f.name, data: f.data })),
    forward: c.fwd?.keep.length ? { folder: c.fwd.folder, uid: c.fwd.uid, attachments: c.fwd.keep } : null };
}
$('#mailAiBtn').onclick = async () => {
  const c = state.mail.compose;
  if (!c?.original) return;
  const btn = $('#mailAiBtn'), ta = $('#mailBody');
  const rest = ta.value; // the AI text goes above what is there (the quoted original)
  btn.disabled = true; btn.lastChild.textContent = tr('Writing…'); ta.readOnly = true;
  let out = '';
  const ok = await mailAi('reply', mailAsText(c.original), null, $('#mailAiHint').value.trim(), (t) => {
    out += t; ta.value = out.replace(/^\s+/, '') + rest;
  });
  btn.disabled = false; btn.lastChild.textContent = tr('Draft reply'); ta.readOnly = false;
  if (!ok) { ta.value = rest; return; }
  ta.value = `${out.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').trim()}${rest}`;
  ta.focus(); ta.setSelectionRange(0, 0); ta.scrollTop = 0;
  toast('Draft written. Check it, then click Send.');
};
$('#mailCompose').onsubmit = async (e) => {
  e.preventDefault();
  const d = composeData();
  const to = [...addrs(d.to), ...addrs(d.cc), ...addrs(d.bcc)];
  if (!to.length) return toast('Enter a recipient');
  if (!d.subject.trim() && !confirm('Send without a subject?')) return;
  if (!confirm(tr('Send this e-mail to {to}?', { to: to.join(', ') }))) return;
  const btn = $('#mailSend');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    const r = await api(`/api/mail/${$('#mailAccount').value}/send`, { method: 'POST', body: d });
    toast(r.warning || 'Sent ✓');
    state.mail.compose = null;
    showMailPane(state.mail.open ? 'reader' : 'empty');
  } catch (err) { toast(err.message); }
  btn.disabled = false; btn.textContent = 'Send';
};
$('#mailDraft').onclick = async () => {
  try {
    const r = await api(`/api/mail/${$('#mailAccount').value}/draft`, { method: 'POST', body: composeData() });
    toast(tr('Saved in {folder} ✓', { folder: r.folder }));
    state.mail.compose.start = $('#mailBody').value; // nothing unsaved any more
    state.mail.compose.savedFiles = state.mail.compose.files.length;
    state.mail.compose.to = $('#mailTo').value.trim();
  } catch (err) { toast(err.message); }
};

/* new mail: every 2 minutes the server looks into each Inbox (read-only); new unread mail gets a notice,
   the Mail button shows how many are unread. The browser remembers the newest UID it announced. */
const MAIL_POLL = 120000;
let mailPolling = false;
async function checkNewMail() {
  if (mailPolling) return;
  if (!state.settings?.mail_notify) { $('#mailBadge').classList.add('hidden'); return; }
  mailPolling = true;
  let r;
  try { r = await api('/api/mail/new'); } catch (e) { mailPolling = false; return; }
  mailPolling = false;
  let seen = {};
  try { seen = JSON.parse(store.get('sunak-mail-seen', '{}')) || {}; } catch (e) { /* start over */ }
  const fresh = [];
  let unread = 0;
  for (const a of r.accounts) {
    if (a.error) continue;
    unread += a.unseen;
    const prev = seen[a.id]?.v === a.uidvalidity ? seen[a.id].uid : null;
    const top = Math.max(0, ...a.latest.map((m) => m.uid));
    if (prev !== null) fresh.push(...a.latest.filter((m) => m.uid > prev).map((m) => ({ ...m, account: a.id })));
    seen[a.id] = { v: a.uidvalidity, uid: Math.max(top, prev || 0) }; // the first look only sets the baseline
  }
  store.set('sunak-mail-seen', JSON.stringify(seen));
  const badge = $('#mailBadge');
  badge.textContent = unread > 99 ? '99+' : String(unread);
  badge.classList.toggle('hidden', !unread);
  if (!fresh.length) return;
  const first = fresh[0];
  const msg = fresh.length === 1 ? tr('New e-mail from {who}: {subject}', { who: who(first), subject: first.subject })
    : tr('{n} new e-mails', { n: fresh.length });
  const open = () => openNewMail(first.account);
  toast(msg, { label: tr('Open'), fn: open });
  if (window.Notification?.permission === 'granted' && document.hidden) {
    try {
      const n = new Notification('Sunak', { body: msg, icon: '/icon.svg', tag: 'sunak-mail' });
      n.onclick = () => { window.focus(); open(); n.close(); };
    } catch (e) { /* not allowed here */ }
  }
  if (state.view === 'mail' && mailFolder() === 'INBOX' && fresh.some((m) => m.account === $('#mailAccount').value)
      && !state.mail.compose) loadMailList();
}
async function openNewMail(aid) {
  show('mail');
  if ($('#mailAccount').value !== aid && state.mail.accounts.some((a) => a.id === aid)) {
    $('#mailAccount').value = aid;
    $('#mailAccount').onchange();
  } else if (mailFolder() !== 'INBOX' && $('#mailFolder').querySelector('option[value="INBOX"]')) {
    $('#mailFolder').value = 'INBOX';
    $('#mailFolder').onchange();
  }
}
function renderMailDesktop() {
  for (const [btn, info] of [[$('#mailDesktop'), $('#mailDesktopState')], [$('#remindersDesktop'), $('#remindersDesktopState')]]) {
    if (!window.Notification || !window.isSecureContext) {
      btn.disabled = true;
      info.textContent = tr('This browser cannot show notifications here (only on localhost or https).');
      continue;
    }
    btn.disabled = Notification.permission !== 'default';
    info.textContent = Notification.permission === 'granted' ? tr('On ✓')
      : Notification.permission === 'denied' ? tr('Blocked in the browser settings') : '';
  }
}
for (const id of ['#mailDesktop', '#remindersDesktop']) {
  $(id).onclick = async () => {
    try { await Notification.requestPermission(); } catch (e) { /* old browsers */ }
    renderMailDesktop();
  };
}

/* calendar reminders: every 30 seconds the server hands out the due ones this profile has not been given yet (each
   only once); each gets a notice in the page and, when allowed, a notification of the system. */
const REMINDER_POLL = 30000;
let remindersPolling = false;
function showReminder(r) {
  toast(`${r.title} · ${r.text}`, { label: tr('Open'), fn: () => show('calendar') });
  if (window.Notification?.permission === 'granted') {
    try {
      const n = new Notification(r.title, { body: r.text, icon: '/icon.svg', tag: 'sunak-reminder-' + r.id, requireInteraction: true });
      n.onclick = () => { window.focus(); show('calendar'); n.close(); };
    } catch (e) { /* not allowed here */ }
  }
}
async function checkReminders() {
  if (remindersPolling || !state.settings?.reminders) return;
  remindersPolling = true;
  try {
    (await api('/api/reminders')).items.forEach(showReminder);
  } catch (e) { /* the next look tries again */ }
  remindersPolling = false;
}

/* settings: link, test and remove accounts */
let mailDraftAcc = null;
async function renderMailAccounts() {
  try { await loadMailAccounts(); } catch (e) { return; }
  const box = $('#mailAccountList');
  box.innerHTML = '';
  if (!state.mail.accounts.length) box.append(el('p', { class: 'muted small' }, 'No account linked.'));
  for (const a of state.mail.accounts) {
    box.append(el('div', { class: 'provider' },
      el('span', { style: 'flex:1' }, icon('mail'), el('b', {}, a.email), a.name ? el('span', { class: 'muted' }, ` · ${a.name}`) : null),
      el('span', { class: 'muted small' }, a.imap_host),
      el('button', { class: 'btn', type: 'button', onclick: () => editMailAccount(a) }, 'Edit'),
      el('button', { class: 'icon-btn', type: 'button', title: 'Unlink (nothing is deleted on the mail server)', onclick: async () => {
        if (!confirm(tr('Unlink {email} from Sunak? Your mail stays on the server.', { email: a.email }))) return;
        await api(`/api/mail/accounts/${a.id}`, { method: 'DELETE' });
        if (mailDraftAcc?.id === a.id) editMailAccount(null);
        renderMailAccounts();
      } }, icon('x'))));
  }
}
function applyPreset(a, pid) {
  const p = state.mail.presets[pid];
  a.preset = pid;
  if (p) for (const k of ['imap_host', 'imap_port', 'imap_security', 'smtp_host', 'smtp_port', 'smtp_security', 'save_sent']) a[k] = p[k];
}
function presetFor(addr) {
  const domain = (addr.split('@')[1] || '').toLowerCase();
  return Object.keys(state.mail.presets).find((k) => state.mail.presets[k].domains.includes(domain)) || '';
}
function editMailAccount(a) {
  const box = $('#mailAccountForm');
  box.innerHTML = '';
  $('#addMailAccount').classList.toggle('hidden', !!a);
  mailDraftAcc = a ? { imap_port: 993, imap_security: 'ssl', smtp_port: 587, smtp_security: 'starttls', save_sent: true, ...a, password: '' } : null;
  if (!a) return;
  const d = mailDraftAcc;
  if (d.id) d.preset = Object.keys(state.mail.presets).find((k) => state.mail.presets[k].imap_host === d.imap_host) || '';
  const field = (k, attrs = {}) => {
    const i = el('input', { 'aria-label': attrs.placeholder, ...attrs });
    i.value = d[k] ?? '';
    i.oninput = () => { d[k] = attrs.type === 'number' ? +i.value : i.value; };
    return i;
  };
  const sec = (k) => {
    const s = el('select', { onchange: (e) => (d[k] = e.target.value) }, el('option', { value: 'ssl' }, 'SSL/TLS'),
      el('option', { value: 'starttls' }, 'STARTTLS'), el('option', { value: 'none' }, 'None (localhost only)'));
    s.value = d[k];
    return s;
  };
  const help = el('p', { class: 'muted small' });
  const result = el('div', { class: 'small' });
  const servers = el('div');
  const renderServers = () => {
    servers.innerHTML = '';
    const p = state.mail.presets[d.preset];
    help.innerHTML = '';
    if (p) help.append(`${p.help} `, ...(p.link ? [el('a', { href: p.link, target: '_blank', rel: 'noopener' }, 'Open', icon('external', 'after'))] : []));
    else help.append('Enter the IMAP and SMTP servers of your provider below (see its help pages).');
    servers.append(
      el('div', { class: 'row' }, el('span', { class: 'mail-lbl' }, 'IMAP'), field('imap_host', { placeholder: 'imap.example.com' }),
        field('imap_port', { type: 'number', min: 1, max: 65535, class: 'port', placeholder: 'Port' }), sec('imap_security')),
      el('div', { class: 'row' }, el('span', { class: 'mail-lbl' }, 'SMTP'), field('smtp_host', { placeholder: 'smtp.example.com' }),
        field('smtp_port', { type: 'number', min: 1, max: 65535, class: 'port', placeholder: 'Port' }), sec('smtp_security')),
      el('div', { class: 'row' }, field('username', { placeholder: 'User name (if not the e-mail address)' })),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!d.save_sent, onchange: (e) => (d.save_sent = e.target.checked) }),
        ' Save a copy of sent mail in the Sent folder (off for Gmail and Outlook, they do it themselves)'));
  };
  const presetSel = el('select', { 'aria-label': 'Provider', onchange: (e) => { applyPreset(d, e.target.value); renderServers(); } },
    el('option', { value: '' }, 'Other provider'),
    Object.entries(state.mail.presets).map(([k, p]) => el('option', { value: k }, p.title)));
  presetSel.value = d.preset || '';
  const emailIn = field('email', { placeholder: 'E-mail address', type: 'email' });
  emailIn.addEventListener('input', () => {
    const pid = presetFor(d.email);
    if (pid && pid !== d.preset && !d.id) { applyPreset(d, pid); presetSel.value = pid; renderServers(); }
  });
  renderServers();
  const pw = field('password', { type: 'password', autocomplete: 'new-password',
    placeholder: a.has_password ? '•••••• saved (type to replace)' : 'App password' });
  box.append(el('div', { class: 'card' },
    el('h3', {}, d.id ? tr('Edit {email}', { email: d.email }) : 'Link a mail account'),
    el('div', { class: 'row' }, emailIn, presetSel),
    el('div', { class: 'row' }, field('name', { placeholder: 'Your name (shown to recipients)' }), pw),
    help,
    el('details', { open: !d.preset }, el('summary', { class: 'muted small' }, 'Server settings'), servers),
    result,
    el('div', { class: 'row' },
      el('button', { class: 'btn', type: 'button', onclick: async (e) => {
        const b = e.currentTarget;
        b.disabled = true; result.textContent = 'Testing…';
        try {
          const r = await api('/api/mail/test', { method: 'POST', body: { account: d } });
          result.innerHTML = '';
          result.append(el('div', { class: r.imap ? 'bad' : 'ok' }, icon(r.imap ? 'x' : 'check'), r.imap ? tr('Reading (IMAP): {error}', { error: r.imap }) : tr('Reading (IMAP) works')),
            el('div', { class: r.smtp ? 'bad' : 'ok' }, icon(r.smtp ? 'x' : 'check'), r.smtp ? tr('Sending (SMTP): {error}', { error: r.smtp }) : tr('Sending (SMTP) works')));
        } catch (err) { result.innerHTML = ''; result.append(el('div', { class: 'bad' }, err.message)); }
        b.disabled = false;
      } }, 'Test connection'),
      el('button', { class: 'btn primary', type: 'button', onclick: async () => {
        try {
          await api('/api/mail/accounts', { method: 'POST', body: { account: d } });
          toast(tr('{email} linked ✓', { email: d.email }));
          editMailAccount(null);
          renderMailAccounts();
        } catch (err) { toast(err.message); }
      } }, 'Save account'),
      el('button', { class: 'btn', type: 'button', onclick: () => editMailAccount(null) }, 'Cancel'))));
  emailIn.focus();
}
$('#addMailAccount').onclick = () => editMailAccount({});

/* ---------------- Models (native Ollama) ---------------- */
const gb = (bytes) => `${(bytes / 1e9).toFixed(1)} GB`;

async function loadOllama() {
  try { state.ollama = await api('/api/ollama'); } catch (e) { state.ollama = null; }
  if (state.view === 'models') renderModelsView();
  if (state.view === 'chat' && !state.session?.messages?.length) renderMessages();
}

function ollamaBanner() {
  const o = state.ollama;
  const box = el('div', { class: 'banner' });
  if (!o) {
    box.append(el('span', {}, 'No Ollama provider configured. '), el('button', { class: 'btn', onclick: () => show('settings') }, 'Open Settings'));
    return box;
  }
  if (o.running) {
    box.classList.add('ok-banner');
    box.append(el('span', {}, `● ${tr('Ollama {version} is running', { version: o.version || '' })}`),
      el('span', { class: 'muted small' }, ` · ${trn(o.models.length, '{n} model', '{n} models')} · ${o.base_url}`));
    return box;
  }
  box.classList.add('warn-banner');
  if (!o.local) {
    box.append(el('p', {}, tr('Can’t reach Ollama at {url}. Make sure it runs on that computer.', { url: o.base_url })),
      el('button', { class: 'btn primary', onclick: () => refreshAll() }, 'Check again'));
  } else if (o.installed) {
    const btn = el('button', { class: 'btn primary', onclick: async () => {
      btn.disabled = true; btn.textContent = 'Starting…'; state.ollamaBusy = true;
      try { await api('/api/ollama/start', { method: 'POST', body: {} }); state.ollamaBusy = false; toast('Ollama started'); await refreshAll(); }
      catch (e) { state.ollamaBusy = false; toast(e.message); btn.disabled = false; btn.textContent = 'Start Ollama'; }
    } }, 'Start Ollama');
    box.append(el('p', {}, 'Ollama is installed but not running.'), btn);
  } else if (o.install.automatic) {
    const log = el('pre', { class: 'install-log hidden' });
    const btn = el('button', { class: 'btn primary', onclick: async () => {
      btn.disabled = true; btn.textContent = 'Installing…'; log.classList.remove('hidden');
      state.ollamaBusy = true;
      let failed = null;
      try {
        await stream('/api/ollama/install', {}, (ev) => {
          if (ev.type === 'status') { log.textContent += ev.t + '\n'; log.scrollTop = log.scrollHeight; }
          if (ev.type === 'error') failed = ev.error;
        });
      } catch (e) { failed = e.message; }
      if (failed) { state.ollamaBusy = false; toast(failed); btn.disabled = false; btn.textContent = 'Install Ollama'; return; }
      toast('Ollama installed');
      await api('/api/ollama/start', { method: 'POST', body: {} }).catch(() => {});
      state.ollamaBusy = false;
      await refreshAll();
    } }, 'Install Ollama');
    box.append(el('p', {}, 'Ollama runs AI models on your computer. It is free and installs in a minute.'), btn,
      el('span', { class: 'muted small' }, ` (${o.install.command})`), log);
  } else if (o.install.method === 'script') {
    box.append(el('p', {}, 'Ollama runs AI models on your computer. Install it with this command in a terminal, then click “Check again”:'),
      el('div', { class: 'cmd' }, el('code', {}, o.install.command),
        el('button', { class: 'btn', onclick: () => navigator.clipboard.writeText(o.install.command).then(() => toast('Copied')) }, 'Copy')),
      el('button', { class: 'btn primary', onclick: () => refreshAll() }, 'Check again'));
  } else {
    box.append(el('p', {}, 'Ollama runs AI models on your computer. Download and open it, then click “Check again”.'),
      el('a', { class: 'btn primary', href: o.install.command, target: '_blank', rel: 'noopener' }, 'Download Ollama'), ' ',
      el('button', { class: 'btn', onclick: () => refreshAll() }, 'Check again'));
  }
  return box;
}

/* Downloads keep running while you switch pages; every widget for a model shows the same progress. */
function startPull(name) {
  if (state.pulls[name]) return;
  const ctrl = new AbortController();
  state.pulls[name] = { pct: 0, label: 'Starting…', ctrl };
  updatePullWidgets();
  (async () => {
    let failed = null;
    try {
      await stream('/api/models/pull', { model: name }, (ev) => {
        const p = state.pulls[name];
        if (!p) return;
        if (ev.type === 'error') failed = ev.error;
        if (ev.type !== 'progress') return;
        if (ev.total) {
          p.pct = Math.min(100, Math.round(ev.completed / ev.total * 100));
          p.label = `${p.pct}% · ${tr('{done} of {total}', { done: gb(ev.completed), total: gb(ev.total) })}`;
        } else p.label = ev.status;
        updatePullWidgets();
      }, ctrl.signal);
    } catch (e) {
      if (e.name === 'AbortError') { delete state.pulls[name]; updatePullWidgets(); toast(tr('Download of {name} cancelled', { name })); return; }
      failed = e.message;
    }
    delete state.pulls[name];
    if (failed) { toast(tr('Download failed: {error}', { error: failed })); updatePullWidgets(); return; }
    store.set('sunak-model', `ollama::${name}`);
    toast(tr('{name} is ready ✓', { name }));
    await refreshAll();
  })();
}

function pullWidget(name) {
  const w = el('div', { class: 'pull', 'data-pull': name });
  fillPullWidget(w);
  return w;
}
function fillPullWidget(w) {
  const name = w.dataset.pull, p = state.pulls[name];
  w.innerHTML = '';
  if (!p) return;
  w.append(el('div', { class: 'progress' }, el('div', { style: `width:${p.pct}%` })),
    el('div', { class: 'pull-row' }, el('span', { class: 'muted small' }, p.label),
      el('button', { class: 'btn small-btn', type: 'button', onclick: () => p.ctrl.abort() }, 'Cancel')));
}
function pullButton(name, label = 'Download') {
  const wrap = el('div', { class: 'pull-slot', 'data-slot': name, 'data-label': label });
  fillPullSlot(wrap);
  return wrap;
}
function fillPullSlot(wrap) {
  if (wrap.dataset.img) return fillImageSlot(wrap);
  const name = wrap.dataset.slot;
  wrap.innerHTML = '';
  if (state.pulls[name]) wrap.append(pullWidget(name));
  else if (isInstalled(name)) wrap.append(el('button', { class: 'btn', onclick: () => useModel(name) }, 'Chat with it →'));
  else wrap.append(el('button', { class: 'btn primary', onclick: () => startPull(name) }, icon('download'), wrap.dataset.label));
}
function fillImageSlot(wrap) {
  const key = wrap.dataset.img, p = state.imgPulls[key];
  wrap.innerHTML = '';
  if (p) {
    wrap.append(el('div', { class: 'pull' }, el('div', { class: 'progress' }, el('div', { style: `width:${p.pct}%` })),
      el('div', { class: 'pull-row' }, el('span', { class: 'muted small' }, p.label),
        el('button', { class: 'btn small-btn', type: 'button', onclick: () => p.ctrl.abort() }, 'Cancel'))));
    return;
  }
  wrap.append(el('button', { class: 'btn primary', type: 'button', onclick: () => {
    if (key === 'engine') {
      imgDownload('engine', '/api/imagegen/engine/install', { name: wrap._sel.value }, async () => {
        await refreshImageStatus();
        if (imageProblem() === 'choose') { await useImageModel(state.settings.image_status.model); return; }
        toast('Image program installed ✓ Next: download an image model below.');
        $('#imageCatalog').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    } else {
      imgDownload(key, '/api/imagegen/models/pull', wrap._body, (r) => {
        toast('Image model ready ✓');
        if (state.settings?.image_gen !== 'local' || !state.settings?.image_gen_model || imageProblem()) useImageModel(r.id);
        else refreshImageStatus();
      });
    }
  } }, icon('download'), wrap.dataset.label));
}
function updatePullWidgets() {
  $$('.pull-slot').forEach(fillPullSlot);
  $$('.downloads > .pull').forEach(fillPullWidget);
  const dl = $('#downloads');
  if (dl) {
    dl.innerHTML = '';
    for (const name of Object.keys(state.pulls)) dl.append(el('div', { class: 'card dl' }, el('b', {}, name), pullWidget(name)));
  }
}
function isInstalled(name) {
  const tagged = name.includes(':') ? name : `${name}:latest`;
  return (state.ollama?.models || []).some((m) => m.name === name || m.name === tagged);
}
function useModel(name) {
  const id = `ollama::${isInstalled(name) && !name.includes(':') ? `${name}:latest` : name}`;
  store.set('sunak-model', id);
  newChat();
  syncModelSelect();
}

/* GPU: which one this computer has, and whether Ollama really uses it */
function gpuBanners(o) {
  const out = [];
  const g = o.gpu;
  const box = el('div', { class: 'banner' });
  if (g?.usable) {
    box.append(el('span', {}, icon('bolt'), `GPU: ${g.name || g.vendor}`), el('span', { class: 'muted small' },
      g.unified ? ` · ${tr('Metal, shares the {gb} GB memory', { gb: o.ram_gb || '?' })}` : ` · ${g.vram_gb} GB VRAM · ${tr('models marked “fits GPU” run fully on it')}`));
  } else if (g) {
    box.append(el('span', {}, icon('cpu'), 'No GPU that Ollama can use was found.'), el('span', { class: 'muted small' }, ' Models run on the CPU, smaller models answer faster.'));
  } else if (!o.local) {
    box.append(el('span', {}, o.gpu_expected ? icon('bolt') : '', o.gpu_expected ? `GPU: ${tr('{vendor} via Docker', { vendor: o.gpu_expected === 'nvidia' ? 'NVIDIA' : 'AMD' })}`
      : tr('Ollama runs at {url} and uses that computer’s GPU, if it has one.', { url: o.base_url })));
  } else return out; // still detecting
  if (o.running) {
    const loaded = el('div', { class: 'gpu-loaded small' });
    if (!o.loaded?.length) loaded.append(el('span', { class: 'muted' }, 'Chat with a model to see whether it runs on the GPU.'));
    for (const m of o.loaded || []) {
      const where = m.gpu_pct >= 100 ? '100% GPU' : m.gpu_pct > 0 ? tr('{pct}% GPU, rest CPU (model is bigger than the VRAM)', { pct: m.gpu_pct }) : 'CPU';
      loaded.append(el('span', { class: `chip${m.gpu_pct > 0 ? ' on' : ''}` }, `${m.name}: ${where}`));
    }
    box.append(loaded);
  }
  out.push(box);
  const warn = o.gpu_warning || g?.hint;
  if (warn) out.push(el('div', { class: 'banner warn-banner' }, el('p', {}, icon('alert'), warn)));
  return out;
}

function renderModelsView() {
  const o = state.ollama;
  const banner = $('#ollamaBanner');
  banner.innerHTML = '';
  banner.append(ollamaBanner());
  const gbox = $('#gpuBox');
  gbox.innerHTML = '';
  if (o) gbox.append(...gpuBanners(o));
  const list = $('#installedList');
  list.innerHTML = '';
  if (!o?.models?.length) list.append(el('p', { class: 'muted' }, o?.running ? 'No models yet. Pick one below.' : '–'));
  for (const m of o?.models || []) {
    list.append(el('div', { class: 'model-row' },
      el('span', { class: 'n' }, el('b', {}, m.name), el('span', { class: 'muted small' }, [m.parameters, m.quantization].filter(Boolean).map((x) => ` · ${x}`).join(''))),
      el('span', { class: 'muted small' }, gb(m.size)),
      el('button', { class: 'btn', onclick: () => useModel(m.name) }, 'Chat'),
      el('button', { class: 'btn danger', title: 'Delete from disk', onclick: async () => {
        if (!confirm(tr('Delete {name} from disk?', { name: m.name }))) return;
        try { await api('/api/models/delete', { method: 'POST', body: { model: `ollama::${m.name}` } }); toast('Deleted'); await refreshAll(); }
        catch (e) { toast(e.message); }
      } }, icon('trash'))));
  }
  renderCatFilters();
  const cat = $('#catalog');
  cat.innerHTML = '';
  const t = state.catType;
  const items = t === 'image' ? [] : (o?.catalog || []).filter((m) => (t === 'all' || m.tags.includes(t)) && catMatch(m));
  if (t !== 'image' && !items.length) cat.append(el('p', { class: 'muted' }, o ? 'No model in the list matches. Try other filters or “Search online”.' : ''));
  for (const m of items) {
    cat.append(el('div', { class: 'model-card' },
      el('div', { class: 'mc-head' }, el('b', {}, m.title), fitBadge(m)),
      el('code', { class: 'small' }, m.name),
      el('p', { class: 'muted small' }, m.description),
      el('div', { class: 'mc-foot' }, el('span', { class: 'small' }, `≈ ${m.size_gb} GB`), ...m.tags.map((x) => el('span', { class: 'chip' }, x))),
      o?.running ? pullButton(m.name) : null));
  }
  renderImageModels();
  updatePullWidgets();
}
const fitBadge = (m) => el('span', { class: `badge ${m.gpu ? 'gpu' : m.fits ? 'fit' : 'nofit'}`, title: m.gpu ? 'Runs fully on your GPU' : m.fits ? 'Runs, on the CPU or partly on the GPU' : '' },
  m.gpu ? icon('bolt') : m.fits ? icon('check') : '', m.gpu ? 'fits GPU' : m.fits ? 'fits' : 'needs more RAM');

/* Search and filters: the lists on this page are filtered right away; “Search online” also asks
   ollama.com and Hugging Face (see sunak/modelsearch.py) and quietly shows nothing when they cannot be reached. */
const catQuery = () => $('#modelSearch').value.trim().toLowerCase();
function catMatch(m) {
  if (state.catFits && !m.fits) return false;
  if (state.catMax && m.size_gb > state.catMax) return false;
  const q = catQuery();
  return !q || q.split(/\s+/).every((w) => [m.name || m.id, m.title, m.description, ...(m.tags || [])].join(' ').toLowerCase().includes(w));
}
function renderCatFilters() {
  const types = { all: 'All', chat: 'Chat', vision: 'Vision', coding: 'Coding', reasoning: 'Reasoning', image: 'Image' };
  const box = $('#catFilters');
  box.replaceChildren(...Object.entries(types).map(([k, label]) => el('button', { class: `chip-btn${state.catType === k ? ' on' : ''}`, type: 'button',
    onclick: () => { state.catType = k; renderModelsView(); } }, label)),
  el('select', { 'aria-label': 'Size', onchange: (e) => { state.catMax = Number(e.target.value); renderModelsView(); } },
    ...[[0, 'Any size'], [2, 'Up to 2 GB'], [5, 'Up to 5 GB'], [10, 'Up to 10 GB']].map(([v, label]) => el('option', { value: v, selected: state.catMax === v }, label))),
  el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: state.catFits, onchange: (e) => { state.catFits = e.target.checked; renderModelsView(); } }), 'Fits my computer'));
}
$('#modelSearch').addEventListener('input', () => { state.online = null; renderModelsView(); renderOnline(); });
$('#modelSearchForm').onsubmit = async (e) => {
  e.preventDefault();
  const q = $('#modelSearch').value.trim();
  if (!q) return toast('Type what to search for');
  const kind = state.catType === 'image' ? 'image' : 'chat';
  state.online = { q, kind, loading: true };
  renderOnline();
  try { state.online = { q, kind, ...(await api(`/api/models/search?q=${encodeURIComponent(q)}&kind=${kind}`)) }; }
  catch (err) { state.online = { q, kind, ollama: [], huggingface: [], unreachable: ['ollama', 'huggingface'] }; }
  if (state.online.q === $('#modelSearch').value.trim()) renderOnline();
};
function renderOnline() {
  const box = $('#onlineResults');
  const r = state.online;
  box.innerHTML = '';
  if (!r) return;
  if (r.loading) { box.append(el('p', { class: 'muted small' }, tr('Searching ollama.com and Hugging Face for “{q}” …', { q: r.q }))); return; }
  const cards = [];
  for (const m of r.ollama || []) {
    const sizes = m.sizes.length ? m.sizes : [''];
    cards.push(el('div', { class: 'model-card' },
      el('div', { class: 'mc-head' }, el('b', { 'data-no-i18n': '' }, m.name), el('span', { class: 'muted small' }, 'Ollama library')),
      el('p', { class: 'muted small', 'data-no-i18n': '' }, m.description),
      el('div', { class: 'mc-foot' }, ...m.capabilities.map((c) => el('span', { class: 'chip', 'data-no-i18n': '' }, c))),
      o_running() ? el('div', { class: 'size-pulls' }, sizes.map((sz) => {
        const name = sz ? `${m.name}:${sz}` : m.name;
        const gbs = sz ? ollamaGb(sz) : null;
        return pullButton(name, sz ? `${sz}${gbs ? ` · ≈ ${gbs} GB` : ''}` : 'Download');
      })) : el('p', { class: 'muted small' }, 'Start Ollama to download.')));
  }
  for (const h of r.huggingface || []) cards.push(hfCard(h, r.kind));
  if (cards.length) box.append(el('h2', { class: 'section' }, tr('Online results for “{q}”', { q: r.q })), el('div', { class: 'catalog' }, cards));
  else if (r.unreachable.length === (r.kind === 'image' ? 1 : 2)) box.append(el('p', { class: 'muted small' }, 'Online search is not reachable right now. The list below shows Sunak’s own catalog.'));
  else box.append(el('p', { class: 'muted small' }, tr('Nothing found online for “{q}”.', { q: r.q })));
  updatePullWidgets();
}
const o_running = () => !!state.ollama?.running;
function ollamaGb(size) {
  const m = /^(\d+(?:\.\d+)?)([bm])$/i.exec(size);
  if (!m) return null;
  const b = Number(m[1]) / (m[2].toLowerCase() === 'm' ? 1000 : 1);
  return Math.round((b * 0.6 + 0.3) * 10) / 10;
}
function hfCard(h, kind) {
  const files = el('div', { class: 'hf-files' });
  const btn = el('button', { class: 'btn', type: 'button', onclick: async () => {
    btn.disabled = true;
    try {
      const info = await api(`/api/models/files?repo=${encodeURIComponent(h.repo)}&kind=${kind}`);
      btn.remove();
      files.append(el('p', { class: 'muted small' }, `${tr('License')}: `, el('a', { href: info.url, target: '_blank', rel: 'noopener', 'data-no-i18n': '' }, info.license || tr('see the model page')),
        info.gated ? ` · ${tr('needs a Hugging Face login, Sunak cannot download it')}` : ''));
      if (!info.files.length) files.append(el('p', { class: 'muted small' }, kind === 'image' ? 'No single-file model (.safetensors, .ckpt, .gguf) in this repository.' : 'No GGUF files in this repository.'));
      for (const f of info.files) {
        const label = `${f.quant || f.path} · ${gb(f.size)}`;
        files.append(el('div', { class: 'hf-file' }, el('span', { class: 'small', title: f.path, 'data-no-i18n': '' }, label),
          kind === 'image' ? imagePullButton({ repo: h.repo, path: f.path }, `hf:${h.repo}/${f.path}`)
            : o_running() ? pullButton(f.ollama) : null));
      }
      updatePullWidgets();
    } catch (e) { toast(e.message); btn.disabled = false; }
  } }, 'Show files');
  return el('div', { class: 'model-card' },
    el('div', { class: 'mc-head' }, el('b', { 'data-no-i18n': '', title: h.repo }, h.repo), el('span', { class: 'muted small' }, 'Hugging Face')),
    el('p', { class: 'muted small' }, tr('{n} downloads', { n: h.downloads.toLocaleString() }), h.vision ? ' · ' : '', h.vision ? icon('eye') : '', h.vision ? 'vision' : ''),
    kind === 'image' ? el('p', { class: 'muted small' }, 'Only single-file Stable Diffusion models (SD 1.x, 2.x, SDXL) work.') : null,
    btn, files);
}

/* Image models for Sunak's own image program (sunak/sdcpp.py): the program and each model are downloaded
   only after a click; downloads continue where they stopped. */
async function loadLocalImages() {
  try { state.local = await api('/api/imagegen/local'); } catch (e) { state.local = null; }
  if (state.view === 'models') renderImageModels();
  if (state.view === 'settings') renderLocalGenSelect();
}
function imgDownload(key, path, body, onDone) {
  if (state.imgPulls[key]) return;
  const ctrl = new AbortController();
  state.imgPulls[key] = { pct: 0, label: 'Starting…', ctrl };
  updatePullWidgets();
  (async () => {
    let failed = null, result = null;
    try {
      await stream(path, body, (ev) => {
        const p = state.imgPulls[key];
        if (ev.type === 'error') failed = ev.error;
        if (ev.type === 'done') result = ev;
        if (ev.type !== 'progress' || !p) return;
        p.pct = ev.total ? Math.min(100, Math.round(ev.completed / ev.total * 100)) : 0;
        p.label = ev.total ? `${p.pct}% · ${tr('{done} of {total}', { done: gb(ev.completed), total: gb(ev.total) })}` : gb(ev.completed);
        updatePullWidgets();
      }, ctrl.signal);
    } catch (e) {
      failed = e.name === 'AbortError' ? null : e.message;
      if (e.name === 'AbortError') toast('Download paused. Click Download again to continue.');
    }
    delete state.imgPulls[key];
    if (failed) toast(tr('Download failed: {error}', { error: failed }));
    if (result) onDone(result);
    await loadLocalImages();
    updatePullWidgets();
  })();
}
function imagePullButton(body, key, label = 'Download') {
  const wrap = el('div', { class: 'pull-slot', 'data-img': key, 'data-label': label });
  wrap._body = body;
  fillPullSlot(wrap);
  return wrap;
}
function renderImageModels() {
  const sec = $('#imageModels');
  sec.classList.toggle('hidden', !['all', 'image'].includes(state.catType));
  const box = $('#imageEngine'), cat = $('#imageCatalog');
  box.innerHTML = ''; cat.innerHTML = '';
  const L = state.local;
  if (!L) { box.append(el('p', { class: 'muted small' }, '…')); return; }
  const eng = L.engine;
  if (eng.installed) {
    box.append(el('div', { class: 'banner' }, el('div', {}, icon('image'), `${tr('Image program installed')}: stable-diffusion.cpp ${eng.tag || ''}`,
      el('span', { class: 'muted small', 'data-no-i18n': '' }, ` · ${eng.kind || ''}`),
      L.models.some((m) => m.installed) ? null : el('p', { class: 'next-step small' }, icon('info'),
        'Next step: download an image model below. Without one the program cannot make pictures.')),
      el('button', { class: 'btn small-btn', type: 'button', onclick: async () => {
        if (!confirm('Remove the image program? Your image models stay.')) return;
        await api('/api/imagegen/engine/remove', { method: 'POST' }).catch((e) => toast(e.message));
        refreshImageStatus();
      } }, 'Remove')));
  } else box.append(engineSetup());
  const items = L.models.filter(catMatch);
  if (!items.length) cat.append(el('p', { class: 'muted' }, 'No image model matches. Try other filters or “Search online” with the Image filter.'));
  for (const m of items) {
    const using = state.settings?.image_gen === 'local' && state.settings?.image_gen_model === m.id;
    cat.append(el('div', { class: 'model-card' },
      el('div', { class: 'mc-head' }, el('b', m.custom ? { 'data-no-i18n': '' } : {}, m.title), fitBadge(m)),
      el('p', { class: 'muted small' }, m.description),
      el('p', { class: 'small' }, icon('file'), el('a', { href: m.license_url, target: '_blank', rel: 'noopener', title: 'License' }, m.license)),
      el('div', { class: 'mc-foot' }, el('span', { class: 'small' }, `≈ ${m.size_gb} GB`), ...(m.tags || []).map((x) => el('span', { class: 'chip' }, x))),
      m.installed
        ? el('div', { class: 'row' }, using ? el('span', { class: 'chip on' }, icon('check'), 'In use') : el('button', { class: 'btn primary', type: 'button', onclick: () => useImageModel(m.id) }, 'Use for pictures'),
          el('button', { class: 'btn danger', type: 'button', title: 'Delete from disk', onclick: async () => {
            if (!confirm(tr('Delete {name} from disk?', { name: m.title }))) return;
            try { await api('/api/imagegen/models/delete', { method: 'POST', body: { id: m.id } }); } catch (e) { toast(e.message); }
            refreshImageStatus();
          } }, icon('trash', 'solo')))
        : imagePullButton({ id: m.id }, m.id, m.partial ? 'Continue download' : 'Download')));
  }
  updatePullWidgets();
}
function engineSetup() {
  const box = el('div', { class: 'banner' });
  const intro = el('p', {}, 'Sunak can make pictures by itself with stable-diffusion.cpp, a free program without extra installs. Set it up once, then download an image model below.');
  const go = el('button', { class: 'btn primary', type: 'button', onclick: async () => {
    go.disabled = true;
    let res;
    try { res = await api('/api/imagegen/engine'); } catch (e) { toast(e.message); go.disabled = false; return; }
    const kinds = { cuda: 'NVIDIA graphics card (CUDA)', vulkan: 'graphics card (Vulkan)', rocm: 'AMD graphics card (ROCm)', metal: 'Apple GPU (Metal)', cpu: 'processor only' };
    const sel = el('select', { 'aria-label': 'Version' }, res.options.map((o, i) => el('option', { value: o.name },
      `${tr(kinds[o.kind] || o.kind)}${i === 0 ? ` (${tr('recommended')})` : ''} · ${gb(o.size)} · ${o.name}`)));
    go.replaceWith(el('div', { class: 'row' }, sel, imagePullButton(null, 'engine', 'Install')));
    $('[data-img="engine"]', box)._sel = sel;
    updatePullWidgets();
  } }, 'Set up the image program');
  box.append(intro, state.imgPulls.engine ? imagePullButton(null, 'engine') : go, el('p', { class: 'muted small' }, 'Downloaded from github.com/leejet/stable-diffusion.cpp. With a graphics card a picture takes seconds, on the processor alone one to several minutes.'));
  return box;
}
async function refreshImageStatus() {  // the settings carry what is missing for pictures
  try { state.settings = await api('/api/settings'); } catch (e) { /* keep the old state */ }
  renderToolsToggle();
  loadLocalImages();
}
async function useImageModel(id) {
  try { state.settings = await api('/api/settings', { method: 'PUT', body: { image_gen: 'local', image_gen_model: id } }); }
  catch (e) { toast(e.message); return; }
  toast('Ready: ask for a picture in the chat, e.g. “make a picture of a lighthouse at dusk”.');
  renderImageModels();
}
$('#pullForm').onsubmit = (e) => {
  e.preventDefault();
  const n = $('#pullName').value.trim();
  if (!n) return;
  if (!/^[A-Za-z0-9._:/-]+$/.test(n)) return toast('Use an Ollama name like qwen3:4b');
  if (!state.ollama?.running) return toast('Start Ollama first');
  startPull(n);
  $('#pullName').value = '';
};

/* ---------------- Compare ---------------- */
function renderCompareModels() {
  const box = $('#compareModels');
  const prev = new Set($$('input:checked', box).map((i) => i.value));
  box.innerHTML = '';
  if (state.models.length < 2) { box.append(el('p', { class: 'muted' }, 'You need at least two models. Download more in Settings.')); return; }
  state.models.forEach((m, i) => box.append(el('label', { class: 'chip check' },
    el('input', { type: 'checkbox', value: m.id, checked: prev.size ? prev.has(m.id) : i < 2 }), m.name)));
}
$('#compareForm').onsubmit = async (e) => {
  e.preventDefault();
  const models = $$('#compareModels input:checked').map((i) => i.value);
  const prompt = $('#comparePrompt').value.trim();
  if (models.length < 2 || models.length > 4) return toast('Pick 2 to 4 models');
  if (!prompt) return;
  const grid = $('#compareGrid');
  grid.innerHTML = '';
  const cols = models.map((id) => {
    const out = el('div', { class: 'md typing' });
    const info = el('span', { class: 'muted' }, '…');
    grid.append(el('div', { class: 'compare-col' }, el('h3', {}, el('span', {}, id.split('::')[1]), info), out));
    return { out, info, raw: '', thinking: false };
  });
  try {
    await stream('/api/compare', { prompt, models }, (ev) => {
      const c = cols[ev.i];
      if (ev.type === 'think') { if (!c.thinking) { c.raw += '<think>'; c.thinking = true; } c.raw += ev.t; }
      else if (ev.type === 'text') { if (c.thinking) { c.raw += '</think>\n\n'; c.thinking = false; } c.raw += ev.t; }
      else if (ev.type === 'done') { c.out.classList.remove('typing'); c.info.textContent = `${ev.seconds}s`; }
      else if (ev.type === 'error') { c.out.classList.remove('typing'); c.raw += `\n\n**Error:** ${ev.error}`; c.info.textContent = tr('failed'); }
      c.out.innerHTML = md(c.raw);
    });
  } catch (err) { toast(err.message); }
};

/* ---------------- Research ---------------- */
let researchText = '';
$('#researchForm').onsubmit = async (e) => {
  e.preventDefault();
  const q = $('#researchQ').value.trim();
  if (!q) return;
  if (await divertPicture(q, 'research')) return;
  const log = $('#researchStatus'), src = $('#researchSources'), rep = $('#researchReport');
  log.innerHTML = ''; src.innerHTML = ''; rep.innerHTML = ''; researchText = '';
  $('#researchActions').classList.add('hidden');
  const btn = $('#researchForm button'); btn.disabled = true;
  let thinking = false;
  try {
    await stream('/api/research', { question: q, model: currentModel() }, (ev) => {
      if (ev.type === 'status') log.append(el('div', {}, ev.t));
      else if (ev.type === 'sources') ev.sources.forEach((s, i) => src.append(el('a', { class: 'chip', href: s.url, target: '_blank', rel: 'noopener', title: s.url }, `[${i + 1}] ${s.title.slice(0, 60)}`)));
      else if (ev.type === 'think') { if (!thinking) { researchText += '<think>'; thinking = true; } researchText += ev.t; rep.innerHTML = md(researchText); }
      else if (ev.type === 'text') { if (thinking) { researchText += '</think>\n\n'; thinking = false; } researchText += ev.t; rep.innerHTML = md(researchText); }
      else if (ev.type === 'error') log.append(el('div', { class: 'bad' }, ev.error));
      else if (ev.type === 'done') { log.append(el('div', {}, 'Done ✓')); $('#researchActions').classList.remove('hidden'); }
    });
  } catch (err) { log.append(el('div', { class: 'bad' }, err.message)); }
  btn.disabled = false;
};
function researchMarkdown() {
  const links = $$('#researchSources a').map((a) => `- ${a.textContent} – ${a.href}`).join('\n');
  return `${researchText.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').trim()}\n\n## ${tr('Sources')}\n${links}\n`;
}
$('#researchSave').onclick = async () => {
  const doc = await api('/api/documents', { method: 'POST', body: { title: $('#researchQ').value.trim().slice(0, 80), content: researchMarkdown() } });
  show('documents'); openDoc(doc.id);
};
$('#researchCopy').onclick = () => navigator.clipboard.writeText(researchMarkdown()).then(() => toast('Copied'));

/* ---------------- Documents ---------------- */
async function loadDocs() {
  const docs = await api('/api/documents');
  const list = $('#docList');
  list.innerHTML = '';
  docs.forEach((d) => list.append(el('div', { class: `doc-item${state.doc?.id === d.id ? ' active' : ''}`, onclick: () => openDoc(d.id), ...KEY_BUTTON }, d.title)));
}
async function openDoc(id) {
  if (state.docBusy) { toast('Wait until the AI edit is finished'); return; }
  await saveDocNow();
  state.doc = await api(`/api/documents/${id}`);
  state.docUndo = null;
  $('#docTitle').value = state.doc.title;
  $('#docContent').value = state.doc.content;
  $('#docSaved').textContent = '';
  setPreview(false);
  $('#docEditor').classList.remove('hidden');
  $('#docEmpty').classList.add('hidden');
  loadDocs();
}
$('#newDoc').onclick = async () => {
  if (state.docBusy) { toast('Wait until the AI edit is finished'); return; }
  const d = await api('/api/documents', { method: 'POST', body: { title: tr('Untitled'), content: '' } });
  await openDoc(d.id);
  $('#docTitle').select();
};
let docTimer = null;
function docChanged() { $('#docSaved').textContent = 'Editing…'; clearTimeout(docTimer); docTimer = setTimeout(saveDocNow, 700); }
async function saveDocNow() {
  clearTimeout(docTimer); docTimer = null;
  if (!state.doc) return;
  const title = $('#docTitle').value.trim() || tr('Untitled'), content = $('#docContent').value;
  if (title === state.doc.title && content === state.doc.content) return;
  const id = state.doc.id;
  const saved = await api(`/api/documents/${id}`, { method: 'PUT', body: { title, content } });
  if (state.doc?.id === id) state.doc = saved; // another document may be open by now
  $('#docSaved').textContent = 'Saved ✓';
  if (state.view === 'documents') loadDocs();
}
$('#docTitle').oninput = docChanged;
$('#docContent').oninput = docChanged;
function setPreview(on) {
  $('#docPreview').classList.toggle('hidden', !on);
  $('#docContent').classList.toggle('hidden', on);
  $('#docPreviewBtn').textContent = on ? 'Edit' : 'Preview';
  if (on) $('#docPreview').innerHTML = md($('#docContent').value);
}
$('#docPreviewBtn').onclick = () => setPreview($('#docPreview').classList.contains('hidden'));
$('#docExport').onclick = () => {
  const a = el('a', { href: URL.createObjectURL(new Blob([$('#docContent').value], { type: 'text/markdown' })), download: `${($('#docTitle').value || 'document').replace(/[^\w\- ]+/g, '')}.md` });
  a.click(); URL.revokeObjectURL(a.href);
};
$('#docDelete').onclick = async () => {
  if (state.docBusy) { toast('Wait until the AI edit is finished'); return; }
  if (!state.doc || !confirm(tr('Delete “{title}”?', { title: state.doc.title }))) return;
  await api(`/api/documents/${state.doc.id}`, { method: 'DELETE' });
  state.doc = null;
  $('#docEditor').classList.add('hidden'); $('#docEmpty').classList.remove('hidden');
  loadDocs();
};
$('#docAiForm').onsubmit = async (e) => {
  e.preventDefault();
  const instruction = $('#docAi').value.trim();
  if (!instruction || !state.doc || state.docBusy) return;
  const ta = $('#docContent');
  const docId = state.doc.id;
  setPreview(false);
  const before = ta.value;
  let start = ta.selectionStart, end = ta.selectionEnd;
  const selection = before.slice(start, end);
  if (!selection) { start = 0; end = before.length; }
  const btn = $('#docAiForm button'); btn.disabled = true; btn.textContent = 'Working…';
  // the document stays locked while the AI writes into it (no typing, no switching documents)
  state.docBusy = true; ta.readOnly = true;
  let out = '', failed = null;
  try {
    await stream('/api/documents/ai', { instruction, content: before, selection, model: currentModel() }, (ev) => {
      if (ev.type === 'text') { out += ev.t; ta.value = before.slice(0, start) + out + before.slice(end); }
      else if (ev.type === 'error') failed = ev.error;
    });
  } catch (err) { failed = err.message; }
  state.docBusy = false; ta.readOnly = false;
  btn.disabled = false; btn.textContent = 'Apply';
  if (state.doc?.id !== docId) return;
  if (failed) { ta.value = before; toast(tr('AI error: {error}', { error: failed })); return; }
  ta.value = before.slice(0, start) + out.replace(/^```\w*\n([\s\S]*?)\n```\s*$/, '$1') + before.slice(end);
  $('#docAi').value = '';
  docChanged();
  toast('AI edit applied', { label: 'Undo', fn: () => { if (state.doc?.id === docId) { ta.value = before; docChanged(); } } });
};

/* ---------------- Calendar ----------------
   Month grid with the events of all calendars (see sunak/cal.py). Times come as UTC and are shown in
   this device's time zone; all-day events as dates with an exclusive end. */
const cal = { month: null, sel: null, events: [], info: null, editing: null };
const pad2 = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const hm = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
const dayOf = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const uiLocale = () => ({ de: 'de-DE', en: 'en-US' })[sunakLang] || navigator.language;
function isoLocal(d) { // 2026-10-06T00:00:00+02:00: the device's own offset, so the server knows its dates
  const off = -d.getTimezoneOffset(), a = Math.abs(off);
  return `${ymd(d)}T${hm(d)}:${pad2(d.getSeconds())}${off >= 0 ? '+' : '-'}${pad2(Math.floor(a / 60))}:${pad2(a % 60)}`;
}
const calHidden = () => new Set(store.get('sunak-cal-hidden', '').split('\n').filter(Boolean));
const calKey = (e) => e.calendar ? `${e.source}|${e.calendar}` : e.source;
function calColor(e) { return e.color || 'var(--accent)'; }
function calNameOf(key) {
  if (key === 'local') return 'Sunak';
  const [sid, href] = key.split('|');
  const src = (cal.info?.sources || []).find((s) => s.id === sid);
  if (!src) return '';
  return href ? (src.calendars || []).find((c) => c.href === href)?.name || src.name : src.name;
}
// the days an event covers (all-day: end exclusive; timed: until the minute before its end)
function eventDays(e) {
  if (e.all_day) {
    const out = [];
    for (let d = dayOf(e.start), end = dayOf(e.end); d < end && out.length < 62; d = addDays(d, 1)) out.push(ymd(d));
    return out.length ? out : [e.start];
  }
  const s = new Date(e.start), en = new Date(Math.max(new Date(e.end) - 1, +s));
  const out = [];
  for (let d = new Date(s.getFullYear(), s.getMonth(), s.getDate()); d <= en && out.length < 62; d = addDays(d, 1)) out.push(ymd(d));
  return out;
}
function calRange() {
  const first = new Date(cal.month.getFullYear(), cal.month.getMonth(), 1);
  const start = addDays(first, -((first.getDay() + 6) % 7)); // weeks start on Monday
  return [start, addDays(start, 42)];
}
async function loadCalendar() {
  if (!cal.month) { const t = new Date(); cal.month = new Date(t.getFullYear(), t.getMonth(), 1); cal.sel = ymd(t); }
  try { cal.info = await api('/api/calendar'); } catch (e) { toast(e.message); return; }
  renderCalLegend();
  await loadCalEvents();
}
async function loadCalEvents() {
  const [start, end] = calRange();
  const month = cal.month;
  renderCalGrid();
  let res;
  try { res = await api(`/api/calendar/events?${new URLSearchParams({ start: isoLocal(start), end: isoLocal(end) })}`); }
  catch (e) { toast(e.message); return; }
  if (cal.month !== month) return; // the user went on to another month meanwhile
  cal.events = res.events;
  const box = $('#calErrors');
  box.innerHTML = '';
  for (const err of res.errors) box.append(el('p', { class: 'err small' }, icon('alert'), el('b', { 'data-no-i18n': '' }, err.name || calNameOf(err.source)), `: ${err.error}`));
  renderCalGrid();
  renderCalDay();
}
function visibleEvents() {
  const hidden = calHidden();
  return cal.events.filter((e) => !hidden.has(calKey(e)) && !hidden.has(e.source));
}
function renderCalGrid() {
  $('#calTitle').textContent = cal.month.toLocaleDateString(uiLocale(), { month: 'long', year: 'numeric' });
  const [start] = calRange();
  const byDay = {};
  for (const e of visibleEvents()) for (const d of eventDays(e)) (byDay[d] ||= []).push(e);
  const grid = $('#calGrid');
  grid.innerHTML = '';
  for (let i = 0; i < 7; i++) grid.append(el('div', { class: 'cal-wd' }, addDays(start, i).toLocaleDateString(uiLocale(), { weekday: 'short' })));
  const today = ymd(new Date());
  for (let i = 0; i < 42; i++) {
    const d = addDays(start, i), key = ymd(d), evs = byDay[key] || [];
    const cls = ['cal-day', d.getMonth() !== cal.month.getMonth() && 'other', key === today && 'today', key === cal.sel && 'sel'].filter(Boolean).join(' ');
    grid.append(el('button', { class: cls, type: 'button', 'aria-label': d.toLocaleDateString(uiLocale(), { dateStyle: 'full' }),
      onclick: () => { cal.sel = key; renderCalGrid(); renderCalDay(); } },
      el('span', { class: 'n' }, d.getDate()),
      evs.slice(0, 3).map((e) => el('span', { class: `cal-chip${e.all_day ? ' all' : ''}${e.status === 'cancelled' ? ' cancelled' : ''}`, 'data-no-i18n': '',
        style: `--c:${calColor(e)}` }, e.all_day ? '' : el('b', {}, hm(new Date(e.start))), ` ${e.summary || '…'}`)),
      evs.length > 3 ? el('span', { class: 'cal-more' }, `+${evs.length - 3}`) : null));
  }
}
function timeText(e) {
  if (e.all_day) {
    const last = addDays(dayOf(e.end), -1);
    return e.start === ymd(last) ? tr('All day') : `${dayOf(e.start).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' })} – ${last.toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' })}`;
  }
  const s = new Date(e.start), en = new Date(e.end);
  const sameDay = ymd(s) === ymd(en) || +en === +s;
  return sameDay ? `${hm(s)}${+en > +s ? ` – ${hm(en)}` : ''}`
    : `${s.toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' })} ${hm(s)} – ${en.toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' })} ${hm(en)}`;
}
function renderCalDay() {
  $('#calDayTitle').textContent = dayOf(cal.sel).toLocaleDateString(uiLocale(), { weekday: 'long', day: 'numeric', month: 'long' });
  const box = $('#calDay');
  box.innerHTML = '';
  const evs = visibleEvents().filter((e) => eventDays(e).includes(cal.sel));
  if (!evs.length) box.append(el('p', { class: 'muted small' }, 'No events.'));
  for (const e of evs) {
    box.append(el('button', { class: `cal-item${e.status === 'cancelled' ? ' cancelled' : ''}`, type: 'button', style: `--c:${calColor(e)}`, onclick: () => editEvent(e) },
      el('span', { class: 'when' }, timeText(e), e.recurring ? icon('refresh', 'before') : ''),
      el('b', { 'data-no-i18n': '' }, e.summary || '…'),
      e.location ? el('span', { class: 'muted small', 'data-no-i18n': '' }, icon('pin'), e.location) : null,
      el('span', { class: 'muted small', 'data-no-i18n': '' }, calNameOf(calKey(e)))));
  }
}
function renderCalLegend() {
  const box = $('#calLegend');
  box.innerHTML = '';
  const hidden = calHidden();
  const toggle = (key) => (ev) => {
    const h = calHidden();
    if (ev.target.checked) h.delete(key); else h.add(key);
    store.set('sunak-cal-hidden', [...h].join('\n'));
    renderCalGrid(); renderCalDay();
  };
  const row = (key, name, color) => el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !hidden.has(key), onchange: toggle(key) }),
    el('span', { class: 'cal-dot', style: `--c:${color || 'var(--accent)'}` }), el('span', { 'data-no-i18n': '' }, name));
  box.append(el('h3', {}, 'Calendars'));
  for (const s of cal.info.sources) {
    if (s.type === 'caldav') for (const c of (s.calendars || []).filter((c) => c.enabled)) box.append(row(`${s.id}|${c.href}`, `${c.name} · ${s.name}`, c.color || s.color));
    else if (s.enabled !== false) box.append(row(s.id, s.name, s.color));
  }
  box.append(el('button', { class: 'btn small-btn', type: 'button', onclick: () => { show('settings'); $('#calSourceList').scrollIntoView({ block: 'center' }); } }, 'Manage calendars'));
}
// calendars new events can go to: Sunak's own and every shown CalDAV calendar
function calTargets() {
  const out = [{ value: 'local', label: 'Sunak' }];
  for (const s of cal.info?.sources || []) {
    if (s.type === 'caldav' && s.enabled !== false) for (const c of (s.calendars || []).filter((c) => c.enabled)) out.push({ value: `${s.id}|${c.href}`, label: `${c.name} · ${s.name}` });
  }
  return out;
}
const remLabel = (n) => (n < 0 ? tr('{n} minutes after the start', { n: -n }) : tr('{n} minutes before', { n }));
function editEvent(e, draft) {
  // e: an existing event, or null with `draft` {summary, start, end, all_day, location, description} in local form
  cal.editing = e;
  const box = $('#calForm');
  box.innerHTML = '';
  box.classList.remove('hidden');
  $('#calDayBox').classList.add('hidden');
  const writable = !e || e.writable;
  const series = !!e?.recurring;
  let d = draft;
  if (e) {
    const s = e.all_day ? dayOf(e.start) : new Date(e.start), en = e.all_day ? addDays(dayOf(e.end), -1) : new Date(e.end);
    d = { summary: e.summary, all_day: e.all_day, location: e.location, description: e.description,
      start: e.all_day ? ymd(s) : `${ymd(s)}T${hm(s)}`, end: e.all_day ? ymd(en) : `${ymd(en)}T${hm(en)}` };
  }
  const [sd, st = '09:00'] = d.start.split('T'), [ed, et = st] = d.end.split('T');
  const input = (attrs, value) => { const i = el('input', attrs); i.value = value ?? ''; i.disabled = !writable; return i; };
  const title = input({ placeholder: 'Title', 'aria-label': 'Title' }, d.summary);
  const allDay = input({ type: 'checkbox' }); allDay.checked = !!d.all_day;
  const startD = input({ type: 'date', 'aria-label': 'Start date' }, sd), startT = input({ type: 'time', 'aria-label': 'Start time' }, st);
  const endD = input({ type: 'date', 'aria-label': 'End date' }, ed), endT = input({ type: 'time', 'aria-label': 'End time' }, et);
  if (series) [allDay, startD, startT, endD, endT].forEach((i) => (i.disabled = true));
  const place = input({ placeholder: 'Place', 'aria-label': 'Place' }, d.location);
  const notes = el('textarea', { rows: 3, placeholder: 'Notes', 'aria-label': 'Notes' });
  notes.value = d.description || ''; notes.disabled = !writable;
  const repeat = el('select', { 'aria-label': 'Repeat' }, [['', 'Does not repeat'], ['DAILY', 'Every day'], ['WEEKLY', 'Every week'],
    ['MONTHLY', 'Every month'], ['YEARLY', 'Every year']].map(([v, t]) => el('option', { value: v }, t)));
  const target = el('select', { 'aria-label': 'Calendar' }, calTargets().map((t) => el('option', { value: t.value }, t.label)));
  target.value = store.get('sunak-cal-target', 'local');
  if (!target.value) target.value = 'local';
  // reminder: minutes before the start; all-day events are reminded at 9:00 (negative = after midnight of the day)
  const remSel = el('select', { 'aria-label': 'Reminder' });
  remSel.disabled = !writable;
  let remDirty = false;
  const fillRem = (keep) => {
    const opts = allDay.checked ? [['', 'No reminder'], ['-540', 'On the day at 9:00'], ['900', 'The day before at 9:00'], ['2340', '2 days before at 9:00']]
      : [['', 'No reminder'], ['0', 'At the start'], ['5', '5 minutes before'], ['10', '10 minutes before'], ['15', '15 minutes before'],
        ['30', '30 minutes before'], ['60', '1 hour before'], ['120', '2 hours before'], ['1440', '1 day before'], ['2880', '2 days before']];
    if (keep !== '' && !opts.some(([v]) => v === keep)) opts.push([keep, remLabel(Number(keep))]);
    remSel.replaceChildren(...opts.map(([v, t]) => el('option', { value: v }, t)));
    remSel.value = keep;
  };
  const remStart = e ? (e.alarms?.length ? String(e.alarms[0]) : '') : (d.all_day ? '' : store.get('sunak-cal-reminder', ''));
  fillRem(remStart);
  remSel.onchange = () => { remDirty = true; };
  const syncTimes = () => [startT, endT].forEach((i) => i.classList.toggle('hidden', allDay.checked));
  allDay.onchange = () => { syncTimes(); fillRem(remSel.value); }; syncTimes();  // a chosen reminder stays, as an extra choice if need be
  startD.onchange = () => { if (endD.value < startD.value) endD.value = startD.value; };
  const save = async () => {
    if (!title.value.trim()) { title.focus(); return toast('Give the event a title'); }
    if (!startD.value) return toast('Pick a date');
    let start, end;
    if (allDay.checked) { start = startD.value; end = ymd(addDays(dayOf(endD.value || startD.value), 1)); }
    else {
      start = new Date(`${startD.value}T${startT.value || '00:00'}`).toISOString();
      end = new Date(`${endD.value || startD.value}T${endT.value || startT.value || '00:00'}`).toISOString();
    }
    const event = { summary: title.value, all_day: allDay.checked, start, end, location: place.value, description: notes.value, repeat: e ? '' : repeat.value };
    if (remDirty || !e) {
      event.reminder = remSel.value === '' ? null : Number(remSel.value);
      if (e) event.reminder_was = e.alarms?.length ? e.alarms[0] : null;  // only the reminder that was shown is replaced
    }
    if (!e) store.set('sunak-cal-reminder', allDay.checked ? '' : remSel.value);
    try {
      if (e) await api('/api/calendar/events', { method: 'PUT', body: { source: e.source, uid: e.uid, href: e.href, etag: e.etag, recurring: series, event } });
      else {
        const [source, calendar] = target.value.split(/\|(.*)/s);
        store.set('sunak-cal-target', target.value);
        await api('/api/calendar/events', { method: 'POST', body: { source, calendar, event } });
      }
    } catch (err) { return toast(err.message); }
    cal.sel = allDay.checked ? startD.value : ymd(new Date(start));
    const s = dayOf(cal.sel);
    cal.month = new Date(s.getFullYear(), s.getMonth(), 1);
    closeEventForm();
    loadCalEvents();
    toast('Saved');
  };
  const del = async () => {
    if (!confirm(series ? tr('Delete “{title}” with all its dates?', { title: e.summary }) : tr('Delete “{title}”?', { title: e.summary }))) return;
    try { await api('/api/calendar/events/delete', { method: 'POST', body: { source: e.source, uid: e.uid, href: e.href, etag: e.etag } }); }
    catch (err) { return toast(err.message); }
    closeEventForm();
    loadCalEvents();
  };
  box.append(el('div', { class: 'card cal-form' },
    el('h3', {}, e ? (writable ? 'Edit event' : 'Event') : 'New event'),
    !writable ? el('p', { class: 'muted small' }, 'This calendar is a subscription and read-only.') : null,
    series && writable ? el('p', { class: 'muted small' }, 'A repeating event: date and time belong to the whole series and are changed in the app it comes from. Title, place and notes can be changed here.') : null,
    title,
    el('label', { class: 'check' }, allDay, 'All day'),
    el('div', { class: 'row' }, el('span', { class: 'cal-lbl' }, 'Start'), startD, startT),
    el('div', { class: 'row' }, el('span', { class: 'cal-lbl' }, 'End'), endD, endT),
    e ? null : el('div', { class: 'row' }, repeat, target),
    el('div', { class: 'row' }, el('span', { class: 'cal-lbl' }, 'Reminder'), remSel),
    !state.settings?.reminders && writable ? el('p', { class: 'muted small' }, 'Reminders are off. Turn them on in Settings → Reminders.') : null,
    place, notes,
    el('div', { class: 'row' },
      writable ? el('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save') : null,
      e && writable ? el('button', { class: 'btn danger', type: 'button', onclick: del }, 'Delete') : null,
      el('button', { class: 'btn', type: 'button', onclick: closeEventForm }, writable ? 'Cancel' : 'Close'))));
  if (writable) title.focus();
}
function closeEventForm() {
  cal.editing = null;
  $('#calForm').classList.add('hidden');
  $('#calForm').innerHTML = '';
  $('#calDayBox').classList.remove('hidden');
  renderCalDay();
}
function newEvent() {
  const day = cal.sel || ymd(new Date());
  const now = new Date(), h = Math.min(now.getHours() + 1, 23);
  editEvent(null, { summary: '', all_day: false, start: `${day}T${pad2(h)}:00`, end: `${day}T${pad2(Math.min(h + 1, 23))}:${h + 1 > 23 ? '59' : '00'}` });
}
async function calQuickAdd(text) {
  if (!currentModel()) { toast('Install or connect a model first'); return; }
  if (!cal.info) await loadCalendar();
  const btn = $('#calQuick button');
  btn.disabled = true;
  const lab = btn.lastChild, old = lab.textContent;
  lab.textContent = '…';
  try {
    const d = await api('/api/calendar/parse', { method: 'POST', body: { text, now: isoLocal(new Date()), model: currentModel() } });
    cal.sel = d.start.slice(0, 10);
    const s = dayOf(cal.sel);
    if (s.getFullYear() !== cal.month.getFullYear() || s.getMonth() !== cal.month.getMonth()) { cal.month = new Date(s.getFullYear(), s.getMonth(), 1); loadCalEvents(); }
    else renderCalGrid();
    editEvent(null, d);
    $('#calQuickText').value = '';
  } catch (e) { toast(e.message); }
  finally { btn.disabled = false; lab.textContent = old; }
}
$('#calQuick').onsubmit = (ev) => { ev.preventDefault(); const t = $('#calQuickText').value.trim(); if (t) calQuickAdd(t); };
$('#calPrev').onclick = () => { cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() - 1, 1); loadCalEvents(); };
$('#calNext').onclick = () => { cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() + 1, 1); loadCalEvents(); };
$('#calToday').onclick = () => { const t = new Date(); cal.month = new Date(t.getFullYear(), t.getMonth(), 1); cal.sel = ymd(t); loadCalEvents(); };
$('#calNew').onclick = newEvent;

/* calendar accounts (Settings → Calendars). Passwords never come back: an empty field keeps the saved one. */
async function renderCalSources() {
  try { cal.info = await api('/api/calendar'); } catch (e) { return; }
  const box = $('#calSourceList');
  box.innerHTML = '';
  for (const s of cal.info.sources.filter((s) => s.type !== 'local')) {
    box.append(el('div', { class: 'provider' },
      el('span', { class: 'cal-dot', style: `--c:${s.color}` }),
      el('span', { style: 'flex:1' }, el('b', { 'data-no-i18n': '' }, s.name), el('span', { class: 'muted small' }, ' · ', s.type === 'ics' ? tr('ICS (read-only)') : trn((s.calendars || []).length, '{n} calendar', '{n} calendars'))),
      el('button', { class: 'btn', type: 'button', onclick: () => editCalSource(s) }, 'Edit'),
      el('button', { class: 'icon-btn', type: 'button', title: 'Remove (nothing changes on the calendar server)', onclick: async () => {
        if (!confirm(tr('Remove {name} from Sunak? The calendar itself stays on its server.', { name: s.name }))) return;
        await api(`/api/calendar/sources/${s.id}`, { method: 'DELETE' }).catch((e) => toast(e.message));
        editCalSource(null); renderCalSources();
      } }, icon('x'))));
  }
}
function editCalSource(s) {
  const box = $('#calSourceForm');
  box.innerHTML = '';
  $('#addCalSource').classList.toggle('hidden', !!s);
  if (!s) return;
  const d = { type: 'caldav', name: '', url: '', username: '', password: '', mail_account: '', ...s, password: '' };
  const help = el('p', { class: 'muted small' });
  const field = (k, attrs) => { const i = el('input', { 'aria-label': attrs.placeholder, ...attrs }); i.value = d[k] ?? ''; i.oninput = () => (d[k] = i.value); return i; };
  const url = field('url', { placeholder: 'Address, e.g. https://caldav.icloud.com', spellcheck: 'false', autocomplete: 'off' });
  const user = field('username', { placeholder: 'User name (usually your e-mail address)', autocomplete: 'off' });
  const pw = field('password', { type: 'password', autocomplete: 'new-password',
    placeholder: s.has_password ? '•••••• saved (type to replace)' : 'Password or app password' });
  const name = field('name', { placeholder: 'Name' });
  const cals = el('div');
  (d.calendars || []).forEach((c) => cals.append(el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: c.enabled,
    onchange: (ev) => (c.enabled = ev.target.checked) }), el('span', { class: 'cal-dot', style: `--c:${c.color || d.color}` }), el('span', { 'data-no-i18n': '' }, c.name))));
  const preset = el('select', { 'aria-label': 'Provider', onchange: (ev) => {
    const p = cal.info.presets[ev.target.value];
    if (p) { d.url = url.value = p.url; if (!d.name) d.name = name.value = p.title; }
    sync();
  } }, el('option', { value: '' }, 'Provider…'), Object.entries(cal.info.presets).map(([k, p]) => el('option', { value: k }, p.title)));
  const fromMail = el('select', { 'aria-label': 'Use the login of a mail account', onchange: (ev) => {
    const m = cal.info.mail_accounts.find((x) => x.id === ev.target.value);
    d.mail_account = m ? m.id : '';
    if (m) {
      d.username = user.value = m.email;
      if (cal.info.presets[m.preset]) { preset.value = m.preset; d.url = url.value = cal.info.presets[m.preset].url; }
      if (!d.name) d.name = name.value = m.email;
    }
    sync();
  } }, el('option', { value: '' }, 'Own login'), cal.info.mail_accounts.map((m) => el('option', { value: m.id }, tr('Login of {email}', { email: m.email }))));
  fromMail.value = d.mail_account || '';
  const kind = el('select', { 'aria-label': 'Type', onchange: (ev) => { d.type = ev.target.value; sync(); } },
    el('option', { value: 'caldav' }, 'CalDAV account (read and write)'), el('option', { value: 'ics' }, 'ICS address (subscription, read-only)'));
  kind.value = d.type;
  if (s.id) kind.disabled = true;
  const caldavOnly = [preset, fromMail, user, pw];
  function sync() {
    caldavOnly.forEach((x) => x.classList.toggle('hidden', d.type !== 'caldav'));
    pw.placeholder = d.mail_account && !s.has_password ? 'Empty = the mail account’s password' : s.has_password ? '•••••• saved (type to replace)' : 'Password or app password';
    url.placeholder = d.type === 'ics' ? 'Calendar address (https:// or webcal://)' : 'Address, e.g. https://caldav.icloud.com';
    help.innerHTML = '';
    const mailPreset = cal.info.mail_accounts.find((m) => m.id === d.mail_account)?.preset;
    const p = cal.info.presets[preset.value];
    if (d.type === 'ics') help.append('Paste the calendar’s address, e.g. Google Calendar → Settings → your calendar → “Secret address in iCal format”.');
    else if (mailPreset && cal.info.ics_only[mailPreset]) help.append(cal.info.ics_only[mailPreset]);
    else if (p) help.append(p.help);
  }
  sync();
  const result = el('p', { class: 'small' });
  box.append(el('div', { class: 'card' },
    el('h3', {}, s.id ? tr('Edit {name}', { name: s.name }) : 'Add calendar'),
    el('div', { class: 'row' }, kind, fromMail, preset), help,
    el('div', { class: 'row' }, url), el('div', { class: 'row' }, user, pw), el('div', { class: 'row' }, name),
    cals, result,
    el('div', { class: 'row' },
      el('button', { class: 'btn primary', type: 'button', onclick: async (ev) => {
        ev.target.disabled = true;
        result.textContent = tr('Connecting…');
        try {
          const saved = await api('/api/calendar/sources', { method: 'POST', body: { source: d } });
          result.textContent = '';
          toast(saved.type === 'caldav' ? tr('{name}: {n} calendars found', { name: saved.name, n: saved.calendars.length }) : 'Saved');
          editCalSource(null); renderCalSources();
        } catch (e) { result.replaceChildren(icon('alert'), e.message); ev.target.disabled = false; }
      } }, 'Save'),
      el('button', { class: 'btn', type: 'button', onclick: () => editCalSource(null) }, 'Cancel'))));
  url.focus();
}
$('#addCalSource').onclick = () => editCalSource({ type: 'caldav' });

/* ---------------- Notes ---------------- */
async function loadNotes() {
  const notes = await api('/api/notes');
  const box = $('#noteList');
  box.innerHTML = '';
  if (!notes.length) box.append(el('p', { class: 'muted' }, 'No notes yet.'));
  for (const n of notes) {
    const c = el('div', { class: 'c', contenteditable: 'true', spellcheck: 'false', style: 'white-space:pre-wrap' }, n.content);
    c.onblur = () => { const v = c.innerText.trim(); if (v && v !== n.content) { n.content = v; api(`/api/notes/${n.id}`, { method: 'PATCH', body: { content: v } }).then(() => toast('Saved')); } };
    // memories Sunak picked up by itself say where from (the chat may be gone)
    const date = new Date(n.created * 1000).toLocaleDateString();
    const origin = !n.source ? null : n.source_title
      ? el('div', { class: 'origin muted small link', title: tr('Open this chat'), ...KEY_BUTTON, onclick: () => openSession(n.source) },
        icon('sparkles'), tr('Remembered from the chat “{title}”, {date}', { title: n.source_title, date }))
      : el('div', { class: 'origin muted small' }, icon('sparkles'), tr('Remembered from a chat, {date}', { date }));
    box.append(el('div', { class: `note${n.is_memory ? ' memory' : ''}` }, el('div', { class: 'note-main' }, c, origin), el('div', { class: 'tools' },
      el('label', { class: 'check', title: 'Remember in chats' }, el('input', { type: 'checkbox', checked: !!n.is_memory,
        onchange: async (e) => { await api(`/api/notes/${n.id}`, { method: 'PATCH', body: { is_memory: e.target.checked } }); loadNotes(); } }), 'memory'),
      el('button', { class: 'icon-btn', title: 'Delete', onclick: async () => { await api(`/api/notes/${n.id}`, { method: 'DELETE' }); loadNotes(); } }, icon('trash')))));
  }
}
$('#noteForm').onsubmit = async (e) => {
  e.preventDefault();
  const content = $('#noteInput').value.trim();
  if (!content) return;
  await api('/api/notes', { method: 'POST', body: { content, is_memory: $('#noteMemory').checked } });
  $('#noteInput').value = '';
  loadNotes();
};
$('#noteInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('#noteForm').requestSubmit(); });

/* ---------------- Settings ---------------- */
let draftProviders = [];
function renderDefaultModel(value = $('#defaultModel').value || state.settings.default_model) {
  const dm = $('#defaultModel');
  dm.innerHTML = '';
  dm.append(el('option', { value: '' }, 'Last used model'), ...state.models.map((m) => el('option', { value: m.id, selected: value === m.id }, `${m.name} (${m.provider_name})`)));
}
function renderSettings() {
  const s = state.settings;
  loadUsage();
  renderDefaultModel(s.default_model);
  draftProviders = s.providers.map((p) => ({ ...p }));
  renderProviders();
  draftPersonas = s.personas.map((p) => ({ ...p }));
  renderPersonas();
  draftMcp = (s.mcp_servers || []).map((m) => ({ ...m }));
  mcpSaved = JSON.stringify(draftMcp);
  renderMcp();
  $('#sysPrompt').value = s.system_prompt;
  $('#temperature').value = s.temperature;
  $('#tempVal').textContent = s.temperature;
  $('#useMemory').checked = s.use_memory;
  $('#autoMemory').checked = s.auto_memory;
  $('#mailNotify').checked = s.mail_notify;
  $('#remindersOn').checked = s.reminders;
  $('#ntfyUrl').value = s.ntfy_url;
  $('#ntfyUrl').disabled = !isAdmin();
  $('#ntfyTopic').value = s.ntfy_topic;
  renderMailDesktop();
  $('#checkUpdates').checked = s.check_updates;
  $('#reportMode').value = s.error_reports || 'off';
  if (isAdmin()) loadReports();
  $('#speechInput').value = s.speech_input;
  $('#whisperUrl').value = s.whisper_url;
  $('#whisperModel').value = s.whisper_model;
  $('#aiImageDetect').checked = s.ai_image_detect;
  $('#imageGen').value = s.image_gen;
  $('#imageGenUrl').value = s.image_gen_url;
  $('#imageGenModel').value = s.image_gen === 'local' ? '' : s.image_gen_model;
  $('#imageGenSize').value = String(s.image_gen_size);
  $('#imageGenSteps').value = s.image_gen_steps;
  $('#imageGenResult').textContent = '';
  renderImageGenUrl();
  renderVoices();
  renderLook();
  renderMailAccounts();
  renderCalSources();
  renderProfile();
  if (isAdmin()) renderLan();
  $('#aboutLine').textContent = `Sunak ${state.status?.version || ''} · ${state.status?.ram_gb ? state.status.ram_gb + ' GB RAM' : ''}`;
}
const CLAUDE_URL = 'https://api.anthropic.com';
function connectClaude() {
  show('settings');
  let i = draftProviders.findIndex((p) => p.type === 'anthropic');
  if (i < 0) { draftProviders.push({ name: 'Claude', type: 'anthropic', base_url: CLAUDE_URL, api_key: '' }); i = draftProviders.length - 1; renderProviders(); }
  const input = $$('#providerList .key-input')[i];
  input.scrollIntoView({ block: 'center' });
  input.focus();
  toast('Paste your Claude API key, then click “Save settings”');
}
function renderProviders() {
  const box = $('#providerList');
  box.innerHTML = '';
  draftProviders.forEach((p, i) => {
    const err = state.modelErrors.find((e) => e.provider === p.id);
    const count = state.models.filter((m) => m.provider === p.id).length;
    const bind = (k) => (e) => { p[k] = e.target.value; };
    box.append(el('div', { class: 'provider' },
      el('input', { value: p.name, placeholder: 'Name', oninput: bind('name') }),
      el('select', { onchange: (e) => {
        p.type = e.target.value;
        if (p.type === 'anthropic' && !p.base_url) { p.base_url = CLAUDE_URL; renderProviders(); }
      } }, el('option', { value: 'ollama', selected: p.type === 'ollama' }, 'Ollama'),
        el('option', { value: 'anthropic', selected: p.type === 'anthropic' }, 'Claude (Anthropic)'),
        el('option', { value: 'openai', selected: p.type === 'openai' }, 'OpenAI-compatible')),
      el('input', { value: p.base_url, placeholder: 'Base URL', oninput: bind('base_url') }),
      el('input', { value: p.api_key || '', type: 'password', autocomplete: 'off', class: 'key-input', oninput: bind('api_key'),
        placeholder: p.has_key ? '•••••• saved (type to replace)' : p.type === 'anthropic' ? 'API key (sk-ant-…)' : 'API key (optional)' }),
      el('span', { class: `status ${err ? 'bad' : 'ok'}`, title: err?.error || '' }, err ? (p.type === 'ollama' ? '● offline' : '● not connected') : p.id ? `● ${trn(count, '{n} model', '{n} models')}` : ''),
      el('button', { class: 'icon-btn', title: 'Remove', onclick: () => { draftProviders.splice(i, 1); renderProviders(); } }, icon('x'))));
  });
}
$('#addProvider').onclick = () => { draftProviders.push({ name: '', type: 'openai', base_url: '', api_key: '' }); renderProviders(); };
$('#providerPreset').onchange = (e) => {
  if (!e.target.value) return;
  const [type, name, base_url] = e.target.value.split('|');
  draftProviders.push({ name, type, base_url, api_key: '' });
  e.target.value = '';
  renderProviders();
};
$('#temperature').oninput = (e) => ($('#tempVal').textContent = e.target.value);
let draftPersonas = [];
function renderPersonas() {
  const box = $('#personaList');
  box.innerHTML = '';
  draftPersonas.forEach((p, i) => {
    const prompt = el('textarea', { rows: 3, placeholder: 'Instructions, e.g. “Answer like a friendly chef.” Empty = default behaviour' });
    prompt.value = p.prompt;
    prompt.oninput = () => (p.prompt = prompt.value);
    box.append(el('div', { class: 'card persona' },
      el('div', { class: 'row' },
        el('input', { value: p.name, placeholder: 'Name', 'aria-label': 'Name', oninput: (e) => (p.name = e.target.value) }),
        el('button', { class: 'icon-btn', title: 'Delete persona', onclick: () => {
          if (draftPersonas.length === 1) return toast('Keep at least one persona');
          draftPersonas.splice(i, 1); renderPersonas();
        } }, icon('trash'))),
      prompt));
  });
}
$('#addPersona').onclick = () => { draftPersonas.push({ icon: '', name: tr('New persona'), prompt: '' }); renderPersonas(); $('#personaList .persona:last-child input').select(); };

/* MCP servers. Environment values and tokens are never sent to the browser: an empty field keeps the saved
   ones (as long as the command or address stays the same), typing replaces them. */
let draftMcp = [], mcpSaved = '[]';
function mcpBody(m) {
  const out = { id: m.id, name: m.name.trim(), type: m.type, enabled: m.enabled !== false };
  if (m.type === 'stdio') {
    out.command = m.command || '';
    if (m.envText?.trim()) out.env = m.envText;
  } else {
    out.url = m.url || '';
    if (m.token) out.token = m.token;
  }
  return out;
}
function renderMcp() {
  const box = $('#mcpList');
  box.innerHTML = '';
  draftMcp.forEach((m, i) => {
    const stdio = m.type === 'stdio';
    const result = el('p', { class: 'muted small mcp-result' }, m.result || '');
    const env = el('textarea', { rows: 2, spellcheck: 'false', 'aria-label': 'Environment variables',
      placeholder: m.env_keys?.length ? tr('Saved: {names}. Type NAME=value lines to replace them.', { names: m.env_keys.join(', ') })
        : 'Environment variables (optional), one NAME=value per line' });
    env.value = m.envText || '';
    env.oninput = () => (m.envText = env.value);
    const test = el('button', { class: 'btn', type: 'button', onclick: async () => {
      test.disabled = true;
      result.textContent = tr('Starting {name} …', { name: m.name || 'server' });
      try {
        const r = await api('/api/mcp/test', { method: 'POST', body: { server: mcpBody(m) } });
        m.result = `✓ ${trn(r.tools.length, '{n} tool', '{n} tools')}: ${r.tools.map((t) => t.name).join(', ')}`;
      } catch (e) { m.result = e.message; m.failed = true; }
      result.textContent = m.result;
      test.disabled = false;
    } }, 'Test');
    box.append(el('div', { class: 'card persona mcp' },
      el('div', { class: 'row' },
        el('input', { value: m.name, placeholder: 'Name', 'aria-label': 'Name', oninput: (e) => (m.name = e.target.value) }),
        el('select', { 'aria-label': 'Type', onchange: (e) => { m.type = e.target.value; renderMcp(); } },
          el('option', { value: 'stdio', selected: stdio }, 'Program'),
          el('option', { value: 'http', selected: !stdio }, 'Address (HTTP)')),
        el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: m.enabled !== false,
          onchange: (e) => (m.enabled = e.target.checked) }), 'on'),
        test,
        el('button', { class: 'icon-btn', type: 'button', title: 'Remove server', onclick: () => { draftMcp.splice(i, 1); renderMcp(); } }, icon('trash'))),
      stdio
        ? [el('input', { value: m.command || '', spellcheck: 'false', autocomplete: 'off', class: 'mcp-cmd', 'aria-label': 'Command',
            placeholder: 'Command, e.g. npx -y @modelcontextprotocol/server-memory', oninput: (e) => (m.command = e.target.value) }), env]
        : [el('input', { value: m.url || '', spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Address',
            placeholder: 'Address, e.g. http://localhost:3000/mcp', oninput: (e) => (m.url = e.target.value) }),
          el('input', { value: m.token || '', type: 'password', autocomplete: 'off', 'aria-label': 'Token',
            placeholder: m.has_token ? '•••••• saved (type to replace)' : 'Token (optional)', oninput: (e) => (m.token = e.target.value) })],
      result));
  });
}
$('#addMcp').onclick = () => { draftMcp.push({ name: '', type: 'stdio', command: '', enabled: true }); renderMcp(); $('#mcpList .mcp:last-child input').focus(); };
$('#mcpPreset').onchange = (e) => {
  if (!e.target.value) return;
  const [name, command] = e.target.value.split('|');
  draftMcp.push({ name, type: 'stdio', command, enabled: true });
  e.target.value = '';
  renderMcp();
  const input = $('#mcpList .mcp:last-child .mcp-cmd');
  input.focus();
  if (command.includes('/path/to/folder')) input.setSelectionRange(command.indexOf('/path/to/folder'), command.length);
};

$('#saveSettings').onclick = async () => {
  const s = state.settings;
  // only when changed: from another device without a password the server refuses MCP changes
  const mcpChanged = JSON.stringify(draftMcp) !== mcpSaved;
  try {
    // installation settings only from admin profiles (the server refuses them from others)
    const install = !isAdmin() ? {} : {
      ...(mcpChanged ? { mcp_servers: draftMcp.map(mcpBody) } : {}),
      providers: draftProviders.filter((p) => p.base_url.trim()), check_updates: $('#checkUpdates').checked,
      error_reports: $('#reportMode').value, ntfy_url: $('#ntfyUrl').value,
      speech_input: $('#speechInput').value, whisper_url: $('#whisperUrl').value, whisper_model: $('#whisperModel').value,
      ai_image_detect: $('#aiImageDetect').checked,
      image_gen: $('#imageGen').value, image_gen_url: $('#imageGenUrl').value,
      image_gen_model: $('#imageGen').value === 'local' ? $('#imageGenLocal').value : $('#imageGenModel').value,
      image_gen_size: Number($('#imageGenSize').value), image_gen_steps: Number($('#imageGenSteps').value),
    };
    state.settings = await api('/api/settings', { method: 'PUT', body: { ...install,
      system_prompt: $('#sysPrompt').value, temperature: parseFloat($('#temperature').value), use_memory: $('#useMemory').checked, auto_memory: $('#autoMemory').checked,
      mail_notify: $('#mailNotify').checked, reminders: $('#remindersOn').checked,
      ntfy_topic: $('#ntfyTopic').value, reminder_lang: sunakLang, accent: s.accent, theme: s.theme, default_model: $('#defaultModel').value, personas: draftPersonas,
    } });
    applyLook();
    renderPersonaSelect();
    renderToolsToggle();
    renderMic();
    await loadModels();
    renderSettings();
    checkUpdate();
    $('#settingsMsg').textContent = 'Saved ✓';
    setTimeout(() => ($('#settingsMsg').textContent = ''), 2000);
  } catch (e) { toast(e.message); }
};
$('#ntfyNew').onclick = () => {
  const b = crypto.getRandomValues(new Uint8Array(8));
  $('#ntfyTopic').value = 'sunak-' + [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  $('#remindersMsg').textContent = tr('Save the settings, then subscribe to this topic in the ntfy app.');
};
$('#remindersTest').onclick = async () => {
  const msg = $('#remindersMsg');
  msg.textContent = '';
  try {
    const r = await api('/api/reminders/test', { method: 'POST', body: { ...(isAdmin() ? { ntfy_url: $('#ntfyUrl').value } : {}), ntfy_topic: $('#ntfyTopic').value, lang: sunakLang } });
    showReminder({ id: 'test', title: r.title, text: r.text });
    msg.textContent = r.pushed ? tr('Test sent to your phone and shown here.') : tr('Test shown here. Enter a topic to test the push message.');
  } catch (e) { msg.textContent = e.message; }
};
const IMAGE_GEN_URLS = { automatic1111: 'http://127.0.0.1:7860', comfyui: 'http://127.0.0.1:8188' };
function renderLocalGenSelect() {
  const sel = $('#imageGenLocal');
  const ready = (state.local?.models || []).filter((m) => m.installed);
  const want = sel.value || state.settings.image_gen_model;
  sel.replaceChildren(...(ready.length ? ready.map((m) => el('option', { value: m.id, selected: m.id === want, 'data-no-i18n': '' }, m.title))
    : [el('option', { value: '' }, 'No image model downloaded yet')]));
  if (state.local && !state.local.engine.installed) sel.append(el('option', { value: '', disabled: true }, 'The image program is not set up yet'));
}
$('#imageGenModels').onclick = () => { state.catType = 'image'; show('models'); };
function renderImageGenUrl() {
  const kind = $('#imageGen').value;
  $$('.remote-gen').forEach((x) => x.classList.toggle('hidden', kind === 'local'));
  $$('.local-gen').forEach((x) => x.classList.toggle('hidden', kind !== 'local'));
  if (kind === 'local') { renderLocalGenSelect(); if (!state.local) loadLocalImages(); }
  $('#imageGenUrl').placeholder = IMAGE_GEN_URLS[kind] ? tr('empty = {url}', { url: IMAGE_GEN_URLS[kind] }) : '';
  $$('#imageGenUrl, #imageGenModel, #imageGenTest, #imageGenSize, #imageGenSteps').forEach((x) => (x.disabled = kind === 'off'));
}
$('#imageGen').onchange = () => { renderImageGenUrl(); $('#imageGenResult').textContent = ''; };
$('#imageGenTest').onclick = async () => {
  const btn = $('#imageGenTest'), out = $('#imageGenResult');
  btn.disabled = true;
  out.textContent = tr('Connecting…');
  try {
    const r = await api('/api/imagegen/test', { method: 'POST', body: { type: $('#imageGen').value, url: $('#imageGenUrl').value } });
    $('#imageGenModelList').replaceChildren(...r.models.map((m) => el('option', { value: m })));
    out.textContent = r.models.length ? `✓ ${trn(r.models.length, '{n} model', '{n} models')}: ${r.models.join(', ')}` : tr('Connected, but the program has no model yet.');
  } catch (e) { out.replaceChildren(icon('alert'), e.message); }
  btn.disabled = false;
};
$('#savePassword').onclick = async () => {
  const pw = $('#password').value;
  if (pw && pw.length < 4) return toast('Use at least 4 characters');
  if (!pw && !state.settings.password_set) return toast('Type a password first');
  if (!pw && !confirm('Remove the password?')) return;
  try { state.settings = await api('/api/settings', { method: 'PUT', body: { password: pw } }); }
  catch (e) { toast(e.message); return; }
  $('#password').value = '';
  toast(pw ? 'Password set. Log in again on other devices.' : 'Password removed');
  if (pw) location.reload();
  else renderProfile(); // other unsaved settings stay as they are
  renderLan(); // removing the password also switches phone access off
};
/* ---------------- Phone access ----------------
   A second listener on the network address (see App.start_lan), only with a password. */
async function renderLan(info) {
  const box = $('#lanBox');
  try { info = info || await api('/api/lan'); } catch (e) { box.replaceChildren(el('p', { class: 'err small' }, e.message)); return; }
  const toggle = el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: info.enabled, disabled: info.fixed || (!info.enabled && !info.password_set),
    onchange: async (e) => {
      try { await renderLan(await api('/api/lan', { method: 'POST', body: { enabled: e.target.checked } })); }
      catch (err) { toast(err.message); e.target.checked = !e.target.checked; }
    } }), ' Allow phones and tablets in my network');
  const kids = [toggle];
  if (!info.password_set && !info.enabled) kids.push(el('p', { class: 'muted small' }, icon('lock'), 'Set a password below first.'));
  if (info.error) kids.push(el('p', { class: 'err small' }, info.error));
  if (info.enabled && info.url) {
    kids.push(el('div', { class: 'lan-card' },
      el('div', { class: 'qr', html: info.qr }),
      el('div', {},
        el('p', {}, 'Scan with the phone camera, or type this address into its browser:'),
        el('p', {}, el('code', { class: 'lan-url' }, info.url), ' ',
          el('button', { class: 'btn', type: 'button', onclick: () => navigator.clipboard.writeText(info.url).then(() => toast('Copied')) }, 'Copy')),
        el('p', { class: 'muted small' }, 'Log in with your password. To get an app icon: in the phone browser’s menu choose “Add to Home screen”. If the phone cannot connect, allow Python in your computer’s firewall.'),
        info.fixed ? el('p', { class: 'muted small' }, 'Sunak was started with --host 0.0.0.0, so it is always reachable in your network.') : '')));
  } else if (info.enabled) kids.push(el('p', { class: 'err small' }, 'No network address found. Is this computer connected to Wi-Fi or a cable?'));
  box.replaceChildren(...kids);
}

$('#stopBtn').onclick = async () => {
  if (!confirm('Stop Sunak? Open it again with the Sunak icon or the “sunak” command.')) return;
  await api('/api/shutdown', { method: 'POST' });
  document.body.innerHTML = '<div class="welcome"><h2>Sunak stopped</h2><p class="muted">Start it again with the Sunak icon or the <code>sunak</code> command.</p></div>';
};

/* ---------------- Updates ---------------- */
async function checkUpdate() {
  let u;
  try { u = await api('/api/update'); } catch (e) { return; } // no hint is better than an error here
  if (u.result) toast(u.result.ok ? tr('Update installed ✓ (Sunak {version})', { version: state.status?.version || '' }) : tr('Update failed: {error}', { error: u.result.error }));
  if ($('#updateBtn').disabled) return; // an update is running
  state.update = u;
  $('#updateNote').classList.toggle('hidden', !u.available);
  $('#updateText').textContent = `${tr('Update available')}${u.behind > 1 ? ` (${tr('{n} changes', { n: u.behind })})` : ''}`;
  $('#updateBtn').classList.toggle('hidden', !u.can_update);
  $('#updateNote').title = u.can_update ? '' : 'Run “git pull” and the installer in your Sunak folder to update.';
}
// the entries of CHANGELOG.md between the installed and the new version, shown before anything is installed
function changelogView(entries) {
  const box = el('div', { class: 'changelog' });
  if (!entries?.length) { box.append(el('p', { class: 'muted' }, tr('No changelog available'))); return box; }
  for (const e of entries) box.append(el('h4', {}, e.date ? `${e.version} · ${e.date}` : e.version), el('div', { class: 'md', html: md(e.body) }));
  return box;
}
$('#updateBtn').onclick = () => {
  const u = state.update || {};
  $('#changelogTitle').textContent = u.version ? tr('Update to Sunak {version}', { version: u.version }) : tr('Update Sunak');
  $('#changelogBody').replaceChildren(changelogView(u.changelog));
  $('#changelogDlg').showModal();
};
$('#changelogCancel').onclick = () => $('#changelogDlg').close();
$('#changelogInstall').onclick = () => { $('#changelogDlg').close(); installUpdate(); };
async function installUpdate() {
  const btn = $('#updateBtn');
  if (state.busy && !confirm('Sunak is still answering. Update and restart anyway?')) return;
  btn.disabled = true;
  btn.textContent = 'Updating…';
  try { await api('/api/update', { method: 'POST' }); }
  catch (e) { toast(e.message); btn.disabled = false; btn.textContent = 'Update'; return; }
  $('#updateText').textContent = 'Installing, Sunak restarts…';
  const old = state.status?.instance;
  const started = Date.now();
  while (Date.now() - started < 300000) {
    await new Promise((r) => setTimeout(r, 1500));
    try {
      const s = await (await fetch('/api/status')).json();
      if (s.instance && s.instance !== old) { location.reload(); return; }
    } catch (e) { /* not back yet */ }
  }
  $('#updateText').textContent = 'Sunak did not come back. Start it with the Sunak icon or “sunak”.';
  btn.classList.add('hidden');
}

// Settings → Updates → "Check for updates now": same check as the hint, but at once and with the reason when it fails
const UPDATE_ERRORS = {
  no_clone: 'This Sunak was not installed from a git clone, so there is nothing to compare with.',
  no_remote: 'Sunak could not reach the update source (no network or no access).',
  no_upstream: 'The clone has no branch to compare with.',
};
$('#checkNow').onclick = async () => {
  const btn = $('#checkNow'), out = $('#checkResult'), install = $('#installNow'), log = $('#checkChangelog');
  btn.disabled = true; install.classList.add('hidden'); log.replaceChildren(); out.textContent = tr('Checking…');
  try {
    const r = await api('/api/update/check', { method: 'POST' });
    if (!r.known) out.textContent = tr('Check failed: {reason}', { reason: tr(UPDATE_ERRORS[r.error] || 'Unknown reason.') });
    else if (!r.available) out.textContent = tr('Sunak {version} is up to date ✓', { version: r.current });
    else {
      out.textContent = r.version && r.version !== r.current ? tr('New version {version} available (you have {current})', { version: r.version, current: r.current })
        : tr('An update is available ({n} changes)', { n: r.behind });
      install.classList.toggle('hidden', !r.can_update);
      if (!r.can_update) out.textContent += ` ${tr('Run “git pull” and the installer in your Sunak folder to update.')}`;
      log.replaceChildren(changelogView(r.changelog));
    }
    checkUpdate(); // the hint at the top follows the same result
  } catch (e) { out.textContent = tr('Check failed: {reason}', { reason: e.message }); }
  btn.disabled = false;
};
$('#installNow').onclick = installUpdate; // the changes are shown right above it

// Settings → Error reports: errors that wait for the user's OK (or were sent), the GitHub token, a sample report
async function loadReports(call) {
  try { renderReports(await (call || api('/api/reports'))); } catch (e) { toast(e.message); }
}
function renderReports(r) {
  $('#reportTokenInfo').textContent = tr(r.token_set ? 'A token is saved on this computer.' : 'No token saved yet.');
  const list = $('#reportList');
  list.replaceChildren();
  if (!r.pending.length) list.append(el('p', { class: 'muted small' }, tr('No error reports are waiting.')));
  for (const p of r.pending) {
    const send = el('button', { class: 'btn primary', type: 'button' }, 'Send');
    send.onclick = async () => {
      send.disabled = true;
      try {
        const res = await api('/api/reports/send', { method: 'POST', body: { id: p.fp } });
        toast(tr(res.action === 'created' ? 'Report sent: issue #{n}' : 'Added to the existing issue #{n}', { n: res.number }));
        loadReports();
      } catch (e) { toast(e.message); send.disabled = false; }
    };
    const dismiss = el('button', { class: 'btn', type: 'button' }, 'Dismiss');
    dismiss.onclick = () => loadReports(api('/api/reports/dismiss', { method: 'POST', body: { id: p.fp } }));
    list.append(el('div', { class: 'card report' },
      el('strong', { 'data-no-i18n': '' }, p.title),
      el('div', { class: 'muted small', 'data-no-i18n': '' }, `${tr('Seen {n}×', { n: p.count })} · ${new Date(p.last * 1000).toLocaleString()}`),
      el('div', { class: 'muted small' }, 'Public on GitHub: everyone can read this report.'),
      el('details', {}, el('summary', {}, 'Show what would be sent'), el('pre', { class: 'report-body', 'data-no-i18n': '' }, p.body)),
      el('div', { class: 'row' }, r.token_set ? send : null,
        el('a', { class: 'btn', href: p.url, target: '_blank', rel: 'noopener' }, 'Open on GitHub'), dismiss)));
  }
  if (r.sent.length) {
    list.append(el('p', { class: 'muted small' }, tr('Sent reports')),
      el('ul', { class: 'report-sent' }, r.sent.map((x) => el('li', {},
        el('a', { href: x.url, target: '_blank', rel: 'noopener', 'data-no-i18n': '' }, `#${x.number}`), ' ', el('span', { class: 'muted small', 'data-no-i18n': '' }, x.title)))));
  }
}
$('#reportMode').onchange = (e) => {  // the issues are public: ask before everything is sent without a look
  if (e.target.value === 'auto' && !confirm(tr('Reports are sent to a PUBLIC GitHub repository, so everyone can read them, and without you looking at each one first. Send automatically?'))) {
    e.target.value = state.settings.error_reports === 'auto' ? 'auto' : 'ask';
  }
};
$('#reportTokenSave').onclick = () => {
  const input = $('#reportToken');
  loadReports(api('/api/reports/token', { method: 'POST', body: { token: input.value } }).then((r) => { input.value = ''; return r; }));
};
$('#reportTokenCheck').onclick = async () => {
  const out = $('#reportTokenInfo');
  out.textContent = tr('Checking…');
  try {
    const r = await api('/api/reports/check', { method: 'POST' });
    out.textContent = tr('Access works ✓ (repository {repo})', { repo: r.repo });
  } catch (e) { out.textContent = tr('Check failed: {reason}', { reason: e.message }); }
};
$('#reportSample').onclick = () => loadReports(api('/api/reports/sample', { method: 'POST' }));

/* ---------------- Profiles ----------------
   Each profile has its own chats, documents, notes, knowledge base, mail, calendar and preferences
   (see App.view). Installation settings (providers, tools, password …) belong to admin profiles. */
const profileName = (p) => p.name || tr('Main profile');
async function showProfilePicker(res) {
  if ($('#profilePicker')) return;
  try { res = res || await api('/api/profiles'); } catch (e) { toast(e.message); return; }
  const pinBox = el('form', { class: 'login hidden' });
  const box = el('div', { class: 'profile-picker', id: 'profilePicker', role: 'dialog', 'aria-modal': 'true' },
    el('img', { src: '/icon.svg', alt: '', width: 48, height: 48 }),
    el('h1', {}, 'Who is using Sunak?'),
    el('div', { class: 'profile-tiles' }, res.profiles.map((p) => el('button', { class: 'profile-tile', type: 'button', onclick: () => pick(p) },
      profileFace(p),
      el('span', p.name ? { 'data-no-i18n': '' } : {}, profileName(p)), p.has_pin ? el('span', { class: 'muted small', title: 'PIN' }, icon('lock', 'solo')) : null))),
    pinBox);
  async function select(p, pin) {
    try { await api('/api/profiles/select', { method: 'POST', body: { id: p.id, pin } }); location.reload(); }
    catch (e) { toast(e.message); pinBox.querySelector('input')?.select(); }
  }
  function pick(p) {
    if (!p.has_pin) return select(p, '');
    const input = el('input', { type: 'password', inputmode: 'numeric', autocomplete: 'off', placeholder: 'PIN', 'aria-label': 'PIN' });
    pinBox.replaceChildren(el('p', { 'data-no-i18n': '' }, tr('PIN for {name}', { name: profileName(p) })), input, el('button', { class: 'btn primary', type: 'submit' }, 'Open'));
    pinBox.onsubmit = (e) => { e.preventDefault(); select(p, input.value); };
    pinBox.classList.remove('hidden');
    input.focus();
  }
  document.body.append(box);
}
// a profile shows the user icon unless someone picked an emoji of their own ('🙂' was the old default)
const ownEmoji = (p) => (p.emoji && p.emoji !== '🙂' ? p.emoji : '');
const profileFace = (p) => (ownEmoji(p) ? el('span', { class: 'profile-emoji', 'data-no-i18n': '' }, ownEmoji(p))
  : el('span', { class: 'profile-emoji' }, icon('user', 'solo')));
function renderProfileChip() {
  const me = state.settings.profile, chip = $('#profileChip');
  chip.classList.toggle('hidden', state.settings.profiles_count < 2);
  chip.replaceChildren(profileFace(me), el('span', me.name ? { 'data-no-i18n': '' } : {}, profileName(me)), icon('swap', 'after muted'));
  chip.onclick = switchProfile;
}
async function switchProfile() {
  await api('/api/profiles/leave', { method: 'POST' }).catch(() => {});
  location.reload();
}
function profileForm(p, onSave, isNew) {
  const emoji = el('input', { class: 'emoji', value: ownEmoji(p), placeholder: '–', title: 'Your own emoji (optional)', 'aria-label': 'Icon', 'data-no-i18n': '' });
  const name = el('input', { value: p.name || '', placeholder: p.id === 'default' ? tr('Main profile') : 'Name', 'aria-label': 'Name', 'data-no-i18n': '' });
  const pin = el('input', { type: 'password', autocomplete: 'new-password', inputmode: 'numeric', 'aria-label': 'PIN',
    placeholder: p.has_pin ? '•••• saved (type to change)' : 'PIN (optional, at least 4 characters)' });
  const admin = el('input', { type: 'checkbox', checked: !!p.admin, disabled: p.id === 'default' || p.id === state.settings.profile.id });
  const save = el('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add profile' : 'Save profile');
  const form = el('form', { class: 'card persona profile-form' },
    el('div', { class: 'row' }, emoji, name),
    el('div', { class: 'row' }, pin,
      p.has_pin ? el('button', { class: 'btn', type: 'button', onclick: () => onSave({ pin: '' }) }, 'Remove PIN') : null),
    isAdmin() ? el('label', { class: 'check' }, admin, 'Admin: may change providers, tools, password and profiles') : null,
    el('div', { class: 'row' }, save, isNew ? el('button', { class: 'btn', type: 'button', onclick: () => renderProfile() }, 'Cancel') : null));
  form.onsubmit = (e) => {
    e.preventDefault();
    const body = { name: name.value, emoji: emoji.value };
    if (pin.value) body.pin = pin.value;
    if (isAdmin() && !admin.disabled) body.admin = admin.checked;
    if (p.id === 'default' && !name.value.trim()) delete body.name; // the main profile may stay unnamed
    onSave(body);
  };
  return form;
}
async function renderProfile() {
  const box = $('#profileBox');
  const me = state.settings.profile;
  const update = (pid) => async (body) => {
    try {
      const out = await api(`/api/profiles/${pid}`, { method: 'PATCH', body });
      if (pid === me.id) { state.settings.profile = out; renderProfileChip(); }
      toast('Saved ✓');
    } catch (e) { toast(e.message); return; }
    renderProfile();
  };
  const kids = [
    el('p', { class: 'muted small' }, 'Every profile has its own chats, documents, notes, knowledge base, mail, calendar and look. Providers and models are shared. A PIN keeps others out of your profile in the app, but not out of the files on this computer.'),
    profileForm(me, update(me.id)),
    el('div', { class: 'row' },
      state.settings.profiles_count > 1 || me.has_pin ? el('button', { class: 'btn', type: 'button', onclick: switchProfile }, icon('swap'), 'Switch profile') : null,
      state.settings.password_set ? el('button', { class: 'btn', type: 'button', onclick: async () => { await api('/api/logout', { method: 'POST' }); location.reload(); } }, 'Log out') : null),
  ];
  box.replaceChildren(...kids);
  if (!isAdmin()) return;
  let res;
  try { res = await api('/api/profiles'); } catch (e) { box.append(el('p', { class: 'err small' }, e.message)); return; }
  state.settings.profiles_count = res.profiles.length;
  renderProfileChip();
  const list = el('div', { class: 'profile-list' });
  for (const p of res.profiles) {
    if (p.id === me.id) continue;
    const row = el('div', { class: 'card persona profile-row' },
      el('div', { class: 'row' },
        profileFace(p),
        el('b', p.name ? { 'data-no-i18n': '' } : {}, profileName(p)),
        p.admin ? el('span', { class: 'muted small' }, 'Admin') : null,
        p.has_pin ? el('span', { class: 'muted small', title: 'PIN' }, icon('lock', 'solo')) : null,
        el('span', { class: 'spacer' }),
        el('button', { class: 'icon-btn', type: 'button', title: 'Edit profile', onclick: () => row.replaceWith(profileForm(p, update(p.id))) }, icon('edit')),
        p.id === 'default' ? null : el('button', { class: 'icon-btn', type: 'button', title: 'Delete profile', onclick: async () => {
          if (!confirm(`${tr('Delete the profile “{name}”?', { name: profileName(p) })}\n\n${tr('All its chats, documents, notes, knowledge base, mail and calendar links are deleted for good.')}`)) return;
          try { await api(`/api/profiles/${p.id}`, { method: 'DELETE' }); } catch (e) { toast(e.message); }
          renderProfile();
        } }, icon('trash'))));
    list.append(row);
  }
  const add = el('button', { class: 'btn', type: 'button', onclick: () => add.replaceWith(profileForm({ id: '', emoji: '' }, async (body) => {
    try { await api('/api/profiles', { method: 'POST', body }); toast('Profile added ✓'); } catch (e) { toast(e.message); return; }
    renderProfile();
  }, true)) }, icon('plus'), 'Add profile');
  box.append(el('h3', {}, 'Other profiles'), list, add);
}

/* ---------------- Boot ---------------- */
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); newChat(); }
  if (e.key === 'Escape') { closeSidebar(); $('#themeMenu').classList.add('hidden'); $('#exportMenu').classList.add('hidden'); }
});
async function refreshAll(poll = false) {
  await Promise.all([loadModels().catch((e) => { if (!poll) toast(e.message); }), loadOllama()]);
  if (state.ollamaBusy) return; // an install or start is running: keep its progress on screen
  if (state.view === 'chat' && !state.session?.messages?.length) renderMessages();
  if (state.view === 'settings') renderDefaultModel(); // only the model list: never wipe unsaved settings
  if (state.view === 'models') renderModelsView();
}
(async function boot() {
  applyLook();
  const profiles = await api('/api/profiles');
  if (profiles.need_choice) { showProfilePicker(profiles); return; }
  [state.status, state.settings] = await Promise.all([api('/api/status'), api('/api/settings')]);
  document.body.classList.toggle('not-admin', !isAdmin());
  renderProfileChip();
  // the language is a setting; the browser keeps a copy, so the page starts in it right away
  const lang = state.settings.language || '';
  if (lang !== sunakLangPref) {
    store.set('sunak-lang', lang);
    if (store.get('sunak-lang', '') === lang && sunakPickLang(lang) !== sunakLang) { location.reload(); return; }
  }
  applyLook();
  renderLook();
  renderKbToggle(); renderWebToggle();
  renderToolsToggle();
  renderMic();
  if (state.settings.reports_pending && state.settings.error_reports !== 'off') {
    toast(tr('{n} error report(s) waiting: Settings → Error reports', { n: state.settings.reports_pending }));
  }
  renderPersonaSelect();
  await Promise.all([refreshAll(), loadSessions()]);
  renderMessages();
  promptEl.focus();
  // pick up a newly started Ollama without reloading
  setInterval(() => { if (!state.models.length && !state.busy && !state.ollamaBusy) refreshAll(true); }, 8000);
  // the update check runs in the background after the start: look again a little later, then hourly
  loadUsage();
  checkUpdate();
  setTimeout(checkUpdate, 20000);
  setInterval(checkUpdate, 3600000);
  setTimeout(checkNewMail, 5000);
  setInterval(checkNewMail, MAIL_POLL);
  setTimeout(checkReminders, 3000);
  setInterval(checkReminders, REMINDER_POLL);
})();

/* composer options menu (drop-up): opens above the text field; closes on pick, outside click or Escape */
const optBtn = $('#optBtn'), optMenu = $('#optMenu');
function setOptMenu(open) {
  optMenu.classList.toggle('hidden', !open);
  optBtn.setAttribute('aria-expanded', String(open));
  if (open) optMenu.querySelector('.opt-item:not(.hidden)')?.focus();
}
function renderOptBadge() {
  const items = [...optMenu.querySelectorAll('.opt-item')].filter((b) => !b.classList.contains('hidden'));
  optBtn.classList.toggle('active', items.some((b) => b.getAttribute('aria-pressed') === 'true'));
  optBtn.classList.toggle('recording', !!$('#micBtn').classList.contains('recording'));
}
optBtn.onclick = () => setOptMenu(optMenu.classList.contains('hidden'));
optMenu.addEventListener('click', (e) => { if (e.target.closest('.opt-item')) setOptMenu(false); });
document.addEventListener('click', (e) => { if (!optMenu.classList.contains('hidden') && !e.target.closest('#optMenu, #optBtn')) setOptMenu(false); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !optMenu.classList.contains('hidden')) { setOptMenu(false); optBtn.focus(); } });
new MutationObserver(renderOptBadge).observe(optMenu, { subtree: true, attributes: true, attributeFilter: ['aria-pressed', 'class'] });
renderOptBadge();
