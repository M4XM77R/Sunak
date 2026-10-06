'use strict';
/* Interface languages. English is the source: each language file (lang-de.js, …) maps the English text
   to its translation, "{name}" marks a part that changes (a file name, a number). Loaded in <head> after
   the language files: text is translated as it appears in the page (the HTML and everything app.js
   draws), user content (chats, mails, documents, file names …) never. Server messages are translated
   when the language file knows them; others stay English. */
const SUNAK_LANG_NAMES = { en: 'English' };
const sunakDicts = window.SUNAK_LANGS || {};
for (const [code, d] of Object.entries(sunakDicts)) SUNAK_LANG_NAMES[code] = d.name;

// "" = the browser's language if Sunak has it, else English
function sunakPickLang(pref) {
  if (pref && SUNAK_LANG_NAMES[pref]) return pref;
  for (const l of navigator.languages || [navigator.language || 'en']) {
    const base = String(l).slice(0, 2).toLowerCase();
    if (SUNAK_LANG_NAMES[base]) return base;
  }
  return 'en';
}
let sunakLangPref = '';
try { sunakLangPref = localStorage.getItem('sunak-lang') || ''; } catch (e) { /* private mode */ }
const sunakLang = sunakPickLang(sunakLangPref);
document.documentElement.lang = sunakLang;
const sunakStrings = (sunakLang !== 'en' && sunakDicts[sunakLang]?.strings) || {};

// keys with {placeholders} also match text with the values filled in (messages from the server), unless
// they are too general for that ("{n} files", "Remove {name}"): those are only for tr() in app.js
const sunakPatterns = [];
for (const [key, value] of Object.entries(sunakStrings)) {
  if (!/\{\w+\}/.test(key) || key.replace(/\{\w+\}/g, '').length < 10) continue;
  const names = [];
  const re = key.split(/(\{\w+\})/).map((part, i) => {
    if (i % 2) { names.push(part.slice(1, -1)); return '([\\s\\S]+?)'; }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('');
  sunakPatterns.push({ re: new RegExp(`^${re}$`), names, value, fixed: key.replace(/\{\w+\}/g, '').length });
}
sunakPatterns.sort((a, b) => b.fixed - a.fixed); // the most specific first: "Download of {name} cancelled" before "Download {name}"
function sunakFill(s, vars) {
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
}
// explicit translation in app.js: tr('Delete “{title}”?', { title })
function tr(s, vars) {
  return sunakFill(sunakStrings[s] ?? s, vars);
}
// with a count: trn(n, '{n} file', '{n} files')
function trn(n, one, many, vars) {
  return tr(n === 1 ? one : many, { n, ...vars });
}
// text as it appears in the page
function sunakTranslate(s) {
  if (!s || sunakLang === 'en') return s;
  const hit = sunakStrings[s];
  if (hit !== undefined) return hit;
  for (const p of sunakPatterns) {
    const m = p.re.exec(s);
    if (!m) continue;
    const vars = {};
    p.names.forEach((n, i) => (vars[n] = m[i + 1]));
    return sunakFill(p.value, vars);
  }
  return s;
}

// user content: its text is never translated (attributes like a delete button's title still are) …
const SUNAK_SKIP_TEXT = '[data-no-i18n], script, style, textarea, pre, code, .md, .bubble, .session, .mi-from, .mi-subj, '
  + '.mail-subject, .mail-head, .mail-body, #mailFrom, .kb-name, .kb-hit, #kbPreview, .sources, #attachments, #docList, '
  + '.note .c, #compareModels, .compare-col h3, .model-row .n, .model-card b, #modelSelect, #personaSelect, #mailAccount, '
  + '#viewTitle, .provider b, .dl b';
// … nor these attributes
const SUNAK_SKIP_ATTR = '[data-no-i18n], .md, .bubble, pre, code, .session .t, .mi-from, .mi-subj';
const SUNAK_ATTRS = ['title', 'placeholder', 'aria-label'];

function sunakText(node) {
  const raw = node.nodeValue, s = raw.trim();
  if (!s) return;
  const out = sunakTranslate(s);
  if (out === s) return;
  const i = raw.indexOf(s);
  node.nodeValue = raw.slice(0, i) + out + raw.slice(i + s.length);
}
function sunakAttr(e, a) {
  const v = e.getAttribute(a);
  if (!v) return;
  const out = sunakTranslate(v.trim());
  if (out !== v.trim()) e.setAttribute(a, out);
}
function sunakWalk(e, noText, noAttr) {
  noText = noText || e.matches(SUNAK_SKIP_TEXT);
  noAttr = noAttr || e.matches(SUNAK_SKIP_ATTR);
  if (noText && noAttr) return;
  if (!noAttr) for (const a of SUNAK_ATTRS) sunakAttr(e, a);
  for (const c of e.childNodes) {
    if (c.nodeType === 1) sunakWalk(c, noText, noAttr);
    else if (c.nodeType === 3 && !noText) sunakText(c);
  }
}
function sunakAdded(target, node) {
  const noText = !!target.closest(SUNAK_SKIP_TEXT), noAttr = !!target.closest(SUNAK_SKIP_ATTR);
  if (node.nodeType === 1) sunakWalk(node, noText, noAttr);
  else if (node.nodeType === 3 && !noText) sunakText(node);
}

if (sunakLang !== 'en') {
  new MutationObserver((records) => {
    for (const r of records) {
      const target = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (!target) continue;
      if (r.type === 'attributes') { if (!target.closest(SUNAK_SKIP_ATTR)) sunakAttr(target, r.attributeName); }
      else r.addedNodes.forEach((n) => { if (n.isConnected) sunakAdded(target, n); });
    }
  }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: SUNAK_ATTRS });
  document.addEventListener('DOMContentLoaded', () => sunakWalk(document.body, false, false));
  // the browser's own dialogs
  for (const k of ['alert', 'confirm', 'prompt']) {
    const native = window[k].bind(window);
    window[k] = (msg, ...rest) => native(sunakTranslate(String(msg ?? '')), ...rest);
  }
}
