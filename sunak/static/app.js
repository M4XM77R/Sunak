'use strict';
/* Sunak – single-file frontend, no build step. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ACCENTS = ['#ff4fa3', '#ff2d7a', '#f472b6', '#e879f9', '#c084fc', '#fb7185', '#ff8fab', '#38bdf8'];
const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};

const state = { settings: null, models: [], modelErrors: [], sessions: [], session: null, view: 'chat',
  busy: null, attachments: [], doc: null, docUndo: null, status: null, ollama: null, pulls: {}, catFilter: 'fits' };

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: { 'X-Requested-With': 'sunak' } };
  if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  const r = await fetch(path, init);
  if (r.status === 401) { location.reload(); throw new Error('Login required'); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

async function stream(path, body, onEvent, signal) {
  const r = await fetch(path, { method: 'POST', signal, body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'sunak' } });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.error || `HTTP ${r.status}`);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
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
}

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
  const codes = [];
  s = esc(s).replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<em>$2</em>')
    .replace(/(^|[^_\w])_([^_\s][^_]*?)_(?!\w)/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(/\[(\d{1,2})\](?!\()/g, '<sup class="cite">[$1]</sup>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
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
        if (box) item = (box[1] === ' ' ? '☐ ' : '☑ ') + item.slice(box[0].length);
        items.push(`<li>${inline(item)}</li>`); i++;
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
    html += `<details class="think"${closed ? '' : ' open'}><summary>${closed ? 'Thought process' : 'Thinking…'}</summary>${blocks(t.trim())}</details>`;
    return '';
  });
  const parts = text.split(/^```/m);
  parts.forEach((part, idx) => {
    if (idx % 2 === 0) { html += blocks(part); return; }
    const nl = part.indexOf('\n');
    const lang = nl >= 0 ? part.slice(0, nl).trim() : '';
    const code = nl >= 0 ? part.slice(nl + 1).replace(/\n$/, '') : part;
    html += `<pre>${lang ? `<span class="lang">${esc(lang)}</span>` : ''}<button class="copy" type="button">Copy</button><code>${esc(code)}</code></pre>`;
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
  const theme = store.get('sunak-theme', state.settings?.theme || 'dark');
  const accent = state.settings?.accent || store.get('sunak-accent', ACCENTS[0]);
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.setProperty('--accent', accent);
  $('meta[name="theme-color"]').content = accent;
  store.set('sunak-accent', accent);
}
$('#themeBtn').onclick = () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  store.set('sunak-theme', next);
  applyLook();
};

/* ---------------- Navigation ---------------- */
const TITLES = { chat: 'Chat', compare: 'Compare models', research: 'Deep Research', documents: 'Documents', notes: 'Notes & Memory', models: 'Models', settings: 'Settings' };
function show(view) {
  state.view = view;
  $$('.nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
  $('#viewTitle').textContent = view === 'chat' && state.session ? state.session.title : TITLES[view];
  $('#modelSelect').classList.toggle('hidden', ['notes', 'settings', 'compare', 'models'].includes(view));
  closeSidebar();
  if (view === 'documents') loadDocs();
  if (view === 'notes') loadNotes();
  if (view === 'settings') renderSettings();
  if (view === 'compare') renderCompareModels();
  if (view === 'models') { renderModelsView(); loadOllama(); }
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
  if (!state.models.length) sel.append(el('option', { value: '' }, 'No model installed'));
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

/* ---------------- Sessions ---------------- */
async function loadSessions() {
  state.sessions = await api('/api/sessions');
  renderSessions();
}
function renderSessions() {
  const f = $('#sessionFilter').value.toLowerCase();
  const box = $('#sessions');
  box.innerHTML = '';
  for (const s of state.sessions.filter((x) => x.title.toLowerCase().includes(f))) {
    box.append(el('div', { class: `session${state.session?.id === s.id ? ' active' : ''}`, onclick: () => openSession(s.id) },
      el('span', { class: 't', title: s.title }, s.title),
      el('button', { class: 'x', title: 'Delete', onclick: async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete “${s.title}”?`)) return;
        await api(`/api/sessions/${s.id}`, { method: 'DELETE' });
        if (state.session?.id === s.id) newChat();
        loadSessions();
      } }, '✕')));
  }
}
$('#sessionFilter').oninput = renderSessions;

async function openSession(id) {
  state.session = await api(`/api/sessions/${id}`);
  syncModelSelect();
  renderMessages();
  renderSessions();
  show('chat');
}
function newChat() {
  state.session = null;
  state.attachments = [];
  renderAttachments();
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
      'Plan a 3-day trip to Stockholm', 'Give me 5 dinner ideas with pasta and spinach'];
    box.append(el('div', { class: 'suggestions' }, ideas.map((t) => el('button', { onclick: () => { $('#prompt').value = t; send(); } }, t))));
  }
  return box;
}

function setupCard() {
  const o = state.ollama;
  if (!o || !o.running) {
    return el('div', { class: 'card' }, el('h3', {}, 'Let’s get a model running'), ollamaBanner(),
      el('p', { class: 'muted small' }, 'Prefer the cloud? ', el('a', { href: '#', onclick: (e) => { e.preventDefault(); show('settings'); } }, 'Add an API key in Settings'), '.'));
  }
  const rec = state.status?.recommended || { model: 'qwen3:4b', size: '2.6 GB' };
  const ram = state.status?.ram_gb ? `${state.status.ram_gb} GB RAM detected. ` : '';
  return el('div', { class: 'card' }, el('h3', {}, 'Download your first model'),
    el('p', { class: 'muted' }, `${ram}Recommended for your computer: `, el('b', {}, rec.model), ` (${rec.size}).`),
    el('div', { class: 'row' }, pullButton(rec.model, `Download ${rec.model}`),
      el('button', { class: 'btn', onclick: () => show('models') }, 'Browse models')));
}

function messageEl(m, i, msgs) {
  const isUser = m.role === 'user';
  const body = el('div', { class: 'body' });
  if (isUser) body.append(el('div', { class: 'bubble' }, m.content));
  else body.append(el('div', { class: 'md', html: md(m.content) }));
  const meta = el('div', { class: 'meta' });
  meta.append(el('button', { onclick: () => navigator.clipboard.writeText(m.content.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').trim()).then(() => toast('Copied')) }, 'Copy'));
  if (!state.busy && m.id) {
    if (isUser) meta.append(el('button', { onclick: () => editMessage(m) }, 'Edit'));
    if (!isUser && i === msgs.length - 1) meta.append(el('button', { onclick: () => regenerate(m) }, 'Regenerate'));
  }
  if (!isUser && m.model) meta.append(el('span', {}, m.model.split('::')[1] || m.model));
  body.append(meta);
  return el('div', { class: `msg ${m.role}` }, el('div', { class: 'avatar' }, isUser ? '🙂' : '⛵'), body);
}

function renderMessages() {
  const box = $('#messages');
  box.innerHTML = '';
  const msgs = state.session?.messages || [];
  if (!msgs.length) { box.append(welcome()); return; }
  msgs.forEach((m, i) => box.append(messageEl(m, i, msgs)));
  box.scrollTop = box.scrollHeight;
}

/* ---------------- Sending ---------------- */
const promptEl = $('#prompt');
function autosize() { promptEl.style.height = 'auto'; promptEl.style.height = `${Math.min(promptEl.scrollHeight, 240)}px`; }
promptEl.addEventListener('input', autosize);
promptEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
$('#composer').onsubmit = (e) => { e.preventDefault(); state.busy ? state.busy.abort() : send(); };

async function send() {
  if (state.busy) return;
  let text = promptEl.value.trim();
  if (!text && !state.attachments.length) return;
  if (!currentModel()) { toast('Install or connect a model first'); show('settings'); return; }
  if (state.attachments.length) {
    text = state.attachments.map((a) => `File \`${a.name}\`:\n\`\`\`\n${a.text}\n\`\`\``).join('\n\n') + (text ? `\n\n${text}` : '');
  }
  promptEl.value = ''; autosize();
  state.attachments = []; renderAttachments();
  if (!state.session) {
    state.session = await api('/api/sessions', { method: 'POST', body: { model: currentModel() } });
    state.session.messages = [];
  }
  await runChat({ content: text }, { role: 'user', content: text });
}

async function runChat(payload, localUserMsg) {
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
  let raw = '', thinking = false, pending = false, error = null;
  const paint = () => {
    pending = false;
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
    target.innerHTML = md(raw);
    if (nearBottom) box.scrollTop = box.scrollHeight;
  };
  try {
    await stream('/api/chat', { session_id: s.id, model: currentModel(), ...payload }, (ev) => {
      if (ev.type === 'start') { s.title = ev.title; $('#viewTitle').textContent = ev.title; }
      else if (ev.type === 'think') { if (!thinking) { raw += '<think>'; thinking = true; } raw += ev.t; }
      else if (ev.type === 'text') { if (thinking) { raw += '</think>\n\n'; thinking = false; } raw += ev.t; }
      else if (ev.type === 'error') error = ev.error;
      if (!pending) { pending = true; requestAnimationFrame(paint); }
    }, ctrl.signal);
  } catch (e) {
    if (e.name !== 'AbortError') error = e.message;
  }
  state.busy = null;
  $('#sendBtn').textContent = 'Send';
  try { state.session = await api(`/api/sessions/${s.id}`); } catch (e) { /* keep local copy */ }
  renderMessages();
  if (error) $('#messages').append(el('div', { class: 'msg' }, el('div', { class: 'avatar' }, '⚠️'), el('div', { class: 'body err' }, error)));
  $('#messages').scrollTop = $('#messages').scrollHeight;
  loadSessions();
}

function regenerate(m) {
  state.session.messages = state.session.messages.filter((x) => x.id < m.id);
  runChat({ truncate_from: m.id });
}
function editMessage(m) {
  const text = prompt('Edit your message:', m.content);
  if (text === null || !text.trim()) return;
  state.session.messages = state.session.messages.filter((x) => x.id < m.id);
  runChat({ truncate_from: m.id, content: text.trim() }, { role: 'user', content: text.trim() });
}

/* attachments: text files are inlined into the prompt */
$('#fileInput').onchange = async (e) => {
  for (const f of e.target.files) {
    if (f.size > 300000) { toast(`${f.name} is too big (max 300 KB)`); continue; }
    const text = await f.text();
    if (/\u0000/.test(text.slice(0, 2000))) { toast(`${f.name} is not a text file`); continue; }
    state.attachments.push({ name: f.name, text });
  }
  e.target.value = '';
  renderAttachments();
};
function renderAttachments() {
  const box = $('#attachments');
  box.innerHTML = '';
  state.attachments.forEach((a, i) => box.append(el('span', { class: 'chip' }, `📄 ${a.name}`,
    el('button', { type: 'button', onclick: () => { state.attachments.splice(i, 1); renderAttachments(); } }, '✕'))));
}

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
    box.append(el('span', {}, `● Ollama ${o.version || ''} is running`), el('span', { class: 'muted small' }, ` · ${o.models.length} model${o.models.length === 1 ? "" : "s"} · ${o.base_url}`));
    return box;
  }
  box.classList.add('warn-banner');
  if (!o.local) {
    box.append(el('p', {}, `Can’t reach Ollama at ${o.base_url}. Make sure it runs on that computer.`),
      el('button', { class: 'btn primary', onclick: refreshAll }, 'Check again'));
  } else if (o.installed) {
    const btn = el('button', { class: 'btn primary', onclick: async () => {
      btn.disabled = true; btn.textContent = 'Starting…';
      try { await api('/api/ollama/start', { method: 'POST', body: {} }); toast('Ollama started'); await refreshAll(); }
      catch (e) { toast(e.message); btn.disabled = false; btn.textContent = 'Start Ollama'; }
    } }, 'Start Ollama');
    box.append(el('p', {}, 'Ollama is installed but not running.'), btn);
  } else if (o.install.automatic) {
    const log = el('pre', { class: 'install-log hidden' });
    const btn = el('button', { class: 'btn primary', onclick: async () => {
      btn.disabled = true; btn.textContent = 'Installing…'; log.classList.remove('hidden');
      let failed = null;
      try {
        await stream('/api/ollama/install', {}, (ev) => {
          if (ev.type === 'status') { log.textContent += ev.t + '\n'; log.scrollTop = log.scrollHeight; }
          if (ev.type === 'error') failed = ev.error;
        });
      } catch (e) { failed = e.message; }
      if (failed) { toast(failed); btn.disabled = false; btn.textContent = 'Install Ollama'; return; }
      toast('Ollama installed');
      await api('/api/ollama/start', { method: 'POST', body: {} }).catch(() => {});
      await refreshAll();
    } }, 'Install Ollama');
    box.append(el('p', {}, 'Ollama runs AI models on your computer. It is free and installs in a minute.'), btn,
      el('span', { class: 'muted small' }, ` (${o.install.command})`), log);
  } else if (o.install.method === 'script') {
    box.append(el('p', {}, 'Ollama runs AI models on your computer. Install it with this command in a terminal, then click “Check again”:'),
      el('div', { class: 'cmd' }, el('code', {}, o.install.command),
        el('button', { class: 'btn', onclick: () => navigator.clipboard.writeText(o.install.command).then(() => toast('Copied')) }, 'Copy')),
      el('button', { class: 'btn primary', onclick: refreshAll }, 'Check again'));
  } else {
    box.append(el('p', {}, 'Ollama runs AI models on your computer. Download and open it, then click “Check again”.'),
      el('a', { class: 'btn primary', href: o.install.command, target: '_blank', rel: 'noopener' }, 'Download Ollama'), ' ',
      el('button', { class: 'btn', onclick: refreshAll }, 'Check again'));
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
          p.label = `${p.pct}% · ${gb(ev.completed)} of ${gb(ev.total)}`;
        } else p.label = ev.status;
        updatePullWidgets();
      }, ctrl.signal);
    } catch (e) {
      if (e.name === 'AbortError') { delete state.pulls[name]; updatePullWidgets(); toast(`Download of ${name} cancelled`); return; }
      failed = e.message;
    }
    delete state.pulls[name];
    if (failed) { toast(`Download failed: ${failed}`); updatePullWidgets(); return; }
    store.set('sunak-model', `ollama::${name}`);
    toast(`${name} is ready ✓`);
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
  const name = wrap.dataset.slot;
  wrap.innerHTML = '';
  if (state.pulls[name]) wrap.append(pullWidget(name));
  else if (isInstalled(name)) wrap.append(el('button', { class: 'btn', onclick: () => useModel(name) }, 'Chat with it →'));
  else wrap.append(el('button', { class: 'btn primary', onclick: () => startPull(name) }, wrap.dataset.label));
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

function renderModelsView() {
  const o = state.ollama;
  const banner = $('#ollamaBanner');
  banner.innerHTML = '';
  banner.append(ollamaBanner());
  const list = $('#installedList');
  list.innerHTML = '';
  if (!o?.models?.length) list.append(el('p', { class: 'muted' }, o?.running ? 'No models yet. Pick one below.' : '–'));
  for (const m of o?.models || []) {
    list.append(el('div', { class: 'model-row' },
      el('span', { class: 'n' }, el('b', {}, m.name), el('span', { class: 'muted small' }, [m.parameters, m.quantization].filter(Boolean).map((x) => ` · ${x}`).join(''))),
      el('span', { class: 'muted small' }, gb(m.size)),
      el('button', { class: 'btn', onclick: () => useModel(m.name) }, 'Chat'),
      el('button', { class: 'btn danger', title: 'Delete from disk', onclick: async () => {
        if (!confirm(`Delete ${m.name} from disk?`)) return;
        try { await api('/api/models/delete', { method: 'POST', body: { model: `ollama::${m.name}` } }); toast('Deleted'); await refreshAll(); }
        catch (e) { toast(e.message); }
      } }, '🗑')));
  }
  const filters = { fits: 'Fits my computer', all: 'All', chat: 'Chat', reasoning: 'Reasoning', coding: 'Coding' };
  const fbox = $('#catFilters');
  fbox.innerHTML = '';
  for (const [k, label] of Object.entries(filters)) {
    fbox.append(el('button', { class: `chip-btn${state.catFilter === k ? ' on' : ''}`, onclick: () => { state.catFilter = k; renderModelsView(); } }, label));
  }
  const cat = $('#catalog');
  cat.innerHTML = '';
  const f = state.catFilter;
  const items = (o?.catalog || []).filter((m) => f === 'all' || (f === 'fits' ? m.fits : m.tags.includes(f)));
  if (!items.length) cat.append(el('p', { class: 'muted' }, o ? 'Nothing in this category fits your computer. Try “All”.' : ''));
  for (const m of items) {
    cat.append(el('div', { class: 'model-card' },
      el('div', { class: 'mc-head' }, el('b', {}, m.title), el('span', { class: `badge ${m.fits ? 'fit' : 'nofit'}` }, m.fits ? '✓ fits' : 'needs more RAM')),
      el('code', { class: 'small' }, m.name),
      el('p', { class: 'muted small' }, m.description),
      el('div', { class: 'mc-foot' }, el('span', { class: 'small' }, `≈ ${m.size_gb} GB`), ...m.tags.map((t) => el('span', { class: 'chip' }, t))),
      o?.running ? pullButton(m.name) : null));
  }
  updatePullWidgets();
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
      else if (ev.type === 'error') { c.out.classList.remove('typing'); c.raw += `\n\n**Error:** ${ev.error}`; c.info.textContent = 'failed'; }
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
  return `${researchText.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').trim()}\n\n## Sources\n${links}\n`;
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
  docs.forEach((d) => list.append(el('div', { class: `doc-item${state.doc?.id === d.id ? ' active' : ''}`, onclick: () => openDoc(d.id) }, d.title)));
}
async function openDoc(id) {
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
  const d = await api('/api/documents', { method: 'POST', body: { title: 'Untitled', content: '' } });
  await openDoc(d.id);
  $('#docTitle').select();
};
let docTimer = null;
function docChanged() { $('#docSaved').textContent = 'Editing…'; clearTimeout(docTimer); docTimer = setTimeout(saveDocNow, 700); }
async function saveDocNow() {
  clearTimeout(docTimer); docTimer = null;
  if (!state.doc) return;
  const title = $('#docTitle').value.trim() || 'Untitled', content = $('#docContent').value;
  if (title === state.doc.title && content === state.doc.content) return;
  state.doc = await api(`/api/documents/${state.doc.id}`, { method: 'PUT', body: { title, content } });
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
  if (!state.doc || !confirm(`Delete “${state.doc.title}”?`)) return;
  await api(`/api/documents/${state.doc.id}`, { method: 'DELETE' });
  state.doc = null;
  $('#docEditor').classList.add('hidden'); $('#docEmpty').classList.remove('hidden');
  loadDocs();
};
$('#docAiForm').onsubmit = async (e) => {
  e.preventDefault();
  const instruction = $('#docAi').value.trim();
  if (!instruction || !state.doc) return;
  const ta = $('#docContent');
  setPreview(false);
  const before = ta.value;
  let start = ta.selectionStart, end = ta.selectionEnd;
  const selection = before.slice(start, end);
  if (!selection) { start = 0; end = before.length; }
  const btn = $('#docAiForm button'); btn.disabled = true; btn.textContent = 'Working…';
  let out = '', failed = null;
  try {
    await stream('/api/documents/ai', { instruction, content: before, selection, model: currentModel() }, (ev) => {
      if (ev.type === 'text') { out += ev.t; ta.value = before.slice(0, start) + out + before.slice(end); }
      else if (ev.type === 'error') failed = ev.error;
    });
  } catch (err) { failed = err.message; }
  btn.disabled = false; btn.textContent = 'Apply';
  if (failed) { ta.value = before; toast(`AI error: ${failed}`); return; }
  ta.value = before.slice(0, start) + out.replace(/^```\w*\n([\s\S]*?)\n```\s*$/, '$1') + before.slice(end);
  $('#docAi').value = '';
  docChanged();
  toast('AI edit applied', { label: 'Undo', fn: () => { ta.value = before; docChanged(); } });
};

/* ---------------- Notes ---------------- */
async function loadNotes() {
  const notes = await api('/api/notes');
  const box = $('#noteList');
  box.innerHTML = '';
  if (!notes.length) box.append(el('p', { class: 'muted' }, 'No notes yet.'));
  for (const n of notes) {
    const c = el('div', { class: 'c', contenteditable: 'true', spellcheck: 'false' }, n.content);
    c.onblur = () => { const v = c.textContent.trim(); if (v && v !== n.content) { n.content = v; api(`/api/notes/${n.id}`, { method: 'PATCH', body: { content: v } }).then(() => toast('Saved')); } };
    box.append(el('div', { class: `note${n.is_memory ? ' memory' : ''}` }, c, el('div', { class: 'tools' },
      el('label', { class: 'check', title: 'Remember in chats' }, el('input', { type: 'checkbox', checked: !!n.is_memory,
        onchange: async (e) => { await api(`/api/notes/${n.id}`, { method: 'PATCH', body: { is_memory: e.target.checked } }); loadNotes(); } }), 'memory'),
      el('button', { class: 'icon-btn', title: 'Delete', onclick: async () => { await api(`/api/notes/${n.id}`, { method: 'DELETE' }); loadNotes(); } }, '🗑'))));
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
function renderSettings() {
  const s = state.settings;
  const dm = $('#defaultModel');
  dm.innerHTML = '';
  dm.append(el('option', { value: '' }, 'Last used model'), state.models.map((m) => el('option', { value: m.id, selected: s.default_model === m.id }, `${m.name} (${m.provider_name})`)));
  draftProviders = s.providers.map((p) => ({ ...p }));
  renderProviders();
  $('#sysPrompt').value = s.system_prompt;
  $('#temperature').value = s.temperature;
  $('#tempVal').textContent = s.temperature;
  $('#useMemory').checked = s.use_memory;
  const sw = $('#swatches');
  sw.innerHTML = '';
  ACCENTS.forEach((c) => sw.append(el('button', { class: c === s.accent ? 'on' : '', style: `background:${c}`, title: c,
    onclick: () => { s.accent = c; applyLook(); renderSettings(); } })));
  $('#logoutBtn').classList.toggle('hidden', !s.password_set);
  $('#aboutLine').textContent = `Sunak ${state.status?.version || ''} · ${state.status?.ram_gb ? state.status.ram_gb + ' GB RAM' : ''}`;
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
      el('select', { onchange: bind('type') }, el('option', { value: 'ollama', selected: p.type === 'ollama' }, 'Ollama'),
        el('option', { value: 'openai', selected: p.type === 'openai' }, 'OpenAI-compatible')),
      el('input', { value: p.base_url, placeholder: 'Base URL', oninput: bind('base_url') }),
      el('input', { value: p.api_key || '', placeholder: 'API key (optional)', type: 'password', oninput: bind('api_key') }),
      el('span', { class: `status ${err ? 'bad' : 'ok'}`, title: err?.error || '' }, err ? '● offline' : p.id ? `● ${count} models` : ''),
      el('button', { class: 'icon-btn', title: 'Remove', onclick: () => { draftProviders.splice(i, 1); renderProviders(); } }, '✕')));
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
$('#saveSettings').onclick = async () => {
  const s = state.settings;
  try {
    state.settings = await api('/api/settings', { method: 'PUT', body: {
      providers: draftProviders.filter((p) => p.base_url.trim()), system_prompt: $('#sysPrompt').value,
      temperature: parseFloat($('#temperature').value), use_memory: $('#useMemory').checked,
      accent: s.accent, default_model: $('#defaultModel').value,
    } });
    applyLook();
    await loadModels();
    renderSettings();
    $('#settingsMsg').textContent = 'Saved ✓';
    setTimeout(() => ($('#settingsMsg').textContent = ''), 2000);
  } catch (e) { toast(e.message); }
};
$('#savePassword').onclick = async () => {
  const pw = $('#password').value;
  if (pw && pw.length < 4) return toast('Use at least 4 characters');
  if (!pw && !confirm('Remove the password?')) return;
  state.settings = await api('/api/settings', { method: 'PUT', body: { password: pw } });
  $('#password').value = '';
  toast(pw ? 'Password set. Log in again on other devices.' : 'Password removed');
  if (pw) location.reload();
  else renderSettings();
};
$('#logoutBtn').onclick = async () => { await api('/api/logout', { method: 'POST' }); location.reload(); };

/* ---------------- Boot ---------------- */
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); newChat(); }
  if (e.key === 'Escape') closeSidebar();
});
async function refreshAll() {
  await Promise.all([loadModels().catch((e) => toast(e.message)), loadOllama()]);
  if (state.view === 'chat' && !state.session?.messages?.length) renderMessages();
  if (state.view === 'settings') renderSettings();
  if (state.view === 'models') renderModelsView();
}
(async function boot() {
  applyLook();
  [state.status, state.settings] = await Promise.all([api('/api/status'), api('/api/settings')]);
  applyLook();
  await Promise.all([refreshAll(), loadSessions()]);
  renderMessages();
  promptEl.focus();
  // pick up a newly started Ollama without reloading
  setInterval(() => { if (!state.models.length && !state.busy) refreshAll(); }, 8000);
})();
