import { CONFIG } from './config.js';

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmt = d => new Date(d).toLocaleString('pt-BR');
export const isOff = d => d.status === 'unavailable' || d.status === 'partial';

let lastErr = 0;
export function toast(msg, type = 'error') {
  let box = document.getElementById('toasts');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toasts';
    box.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm';
    document.body.append(box);
  }
  const tone = { error: 'bg-red-950 border-red-500 text-red-200', ok: 'bg-emerald-950 border-emerald-500 text-emerald-200', info: 'bg-slate-800 border-cyan-500 text-cyan-200' }[type];
  const el = document.createElement('div');
  el.className = `px-4 py-3 rounded-lg shadow-lg text-sm border ${tone}`;
  el.textContent = msg;
  box.append(el);
  setTimeout(() => el.remove(), 5000);
}

export async function api(path, { method = 'GET', body, quiet = false } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 15000);
  const headers = {};
  if (CONFIG.API_KEY) headers['X-API-Key'] = CONFIG.API_KEY;
  if (body) headers['Content-Type'] = 'application/json';
  try {
    const r = await fetch(CONFIG.BASE_URL + path, { method, headers, signal: ctrl.signal, body: body && JSON.stringify(body) });
    if (!r.ok) throw new Error(`HTTP ${r.status}${r.status === 404 ? ' (endpoint não existe na API)' : ''}`);
    return await r.json();
  } catch (e) {
    const m = e.name === 'AbortError' ? 'tempo esgotado' : e.message;
    if (!quiet && Date.now() - lastErr > 20000) { lastErr = Date.now(); toast(`API inacessível: ${m}`); }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const getEvents = () => JSON.parse(localStorage.getItem('events') || '[]');

// Compara com a leitura anterior e registra quedas e recuperações
function trackEvents(ds) {
  const prev = JSON.parse(localStorage.getItem('prev') || 'null');
  const ev = getEvents();
  const now = {};
  ds.forEach(d => { now[d.id] = d.status; });
  if (prev) ds.forEach(d => {
    const was = prev[d.id];
    if (!was || was === d.status) return;
    const wasOff = was === 'unavailable' || was === 'partial';
    if (wasOff !== isOff(d)) ev.unshift({ t: Date.now(), name: d.name, area: d.area, kind: isOff(d) ? 'falha' : 'recuperado' });
  });
  localStorage.setItem('prev', JSON.stringify(now));
  localStorage.setItem('events', JSON.stringify(ev.slice(0, 100)));
}

export async function loadDevices() {
  const list = await api(CONFIG.PATHS.devices);
  const ds = list.map(d => ({
    ...d,
    name: d.name || '(sem nome)',
    area: d.area || 'Sem cômodo',
    entities: d.entities || [],
    types: [...new Set((d.entities || []).map(e => e.split('.')[0]))],
    bad: d.unavailable_entities || [],
  }));
  trackEvents(ds);
  return { ds, at: new Date() };
}

export function nav(active) {
  const links = [['painel.html', 'Painel'], ['controle.html', 'Controle'], ['localidades.html', 'Localidades']];
  document.getElementById('nav').innerHTML = `
  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-40">
    <div class="max-w-7xl mx-auto px-4 h-14 flex items-center gap-2 overflow-x-auto">
      <span class="font-semibold text-cyan-400 whitespace-nowrap mr-2">◉ IoT Monitor</span>
      ${links.map(([h, l]) => `<a href="${h}" class="px-3 py-1.5 rounded-md text-sm whitespace-nowrap ${h === active ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-400 hover:text-slate-200'}">${l}</a>`).join('')}
      <button id="cfg" class="ml-auto text-slate-400 hover:text-slate-200 text-lg" title="Configurar API">⚙</button>
    </div>
  </header>`;
  document.getElementById('cfg').onclick = () => {
    const u = prompt('URL base da API:', CONFIG.BASE_URL);
    if (u === null) return;
    localStorage.setItem('baseUrl', u.trim().replace(/\/$/, ''));
    const k = prompt('API key (vazio = sem chave):', CONFIG.API_KEY);
    if (k !== null) localStorage.setItem('apiKey', k.trim());
    location.reload();
  };
}

export function auto(fn) {
  fn();
  return setInterval(fn, CONFIG.REFRESH_MS);
}
