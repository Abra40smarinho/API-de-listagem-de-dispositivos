import { CONFIG } from './config.js';

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmt = d => new Date(d).toLocaleString('pt-BR');
export const isOff = d => d.status === 'unavailable' || d.status === 'partial';

export const ago = t => {
  const m = Math.floor((Date.now() - t) / 60000);
  if (m < 1) return 'agora';
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} h` : `${Math.floor(h / 24)} d`;
};

// [rótulo, cor do texto, cor do ponto]
export const STATUS = {
  unavailable: ['Offline', 'text-red-400', 'bg-red-500'],
  partial: ['Parcial', 'text-amber-400', 'bg-amber-500'],
  ok: ['Online', 'text-emerald-400', 'bg-emerald-500'],
  no_entities: ['Sem estado', 'text-slate-400', 'bg-slate-500'],
};

export const pref = (k, def) => { try { const v = localStorage.getItem('pref_' + k); return v === null ? def : JSON.parse(v); } catch { return def; } };
export const setPref = (k, v) => localStorage.setItem('pref_' + k, JSON.stringify(v));

// A integração "demo" do HA cria dispositivos de mentira; dá para ocultá-los em todas as telas
export const visible = ds => (pref('hideDemo', true) ? ds.filter(d => !d.integrations.includes('demo')) : ds);

const live = ok => {
  const el = document.getElementById('live');
  if (el) el.className = `w-2 h-2 rounded-full shrink-0 ${ok ? 'bg-emerald-400' : 'bg-red-500'}`;
};

export function toast(msg, type = 'error') {
  let box = document.getElementById('toasts');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toasts';
    box.className = 'fixed top-14 right-4 z-50 flex flex-col gap-2 max-w-sm';
    document.body.append(box);
  }
  const tone = { error: 'bg-red-950 border-red-500 text-red-200', ok: 'bg-emerald-950 border-emerald-500 text-emerald-200', info: 'bg-slate-800 border-cyan-500 text-cyan-200' }[type];
  const el = document.createElement('div');
  el.className = `px-4 py-3 rounded-lg shadow-lg text-sm border ${tone}`;
  el.textContent = msg;
  box.append(el);
  setTimeout(() => el.remove(), 5000);
}

let lastErr = 0;
export async function api(path, { method = 'GET', body, quiet = false } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 15000);
  const headers = {};
  if (CONFIG.API_KEY) headers['X-API-Key'] = CONFIG.API_KEY;
  if (body) headers['Content-Type'] = 'application/json';
  try {
    const r = await fetch(CONFIG.BASE_URL + path, { method, headers, signal: ctrl.signal, body: body && JSON.stringify(body) });
    if (!r.ok) throw new Error(r.status === 401 ? 'chave inválida (clique em ⚙)' : `HTTP ${r.status}${r.status === 404 ? ' (endpoint não existe na API)' : ''}`);
    const data = await r.json();
    live(true);
    return data;
  } catch (e) {
    live(false);
    const m = e.name === 'AbortError' ? 'tempo esgotado' : e.message;
    if (!quiet && Date.now() - lastErr > 20000) { lastErr = Date.now(); toast(`API: ${m}`); }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const getEvents = () => JSON.parse(localStorage.getItem('events') || '[]');

// Registra quando cada dispositivo foi visto offline pela 1ª vez e as quedas/recuperações
function track(ds) {
  const read = (k, def) => JSON.parse(localStorage.getItem(k) || def);
  const prev = read('prev', 'null'), since = read('since', '{}'), ev = read('events', '[]');
  const now = {}, nsince = {};
  ds.forEach(d => {
    now[d.id] = d.status;
    if (isOff(d)) nsince[d.id] = since[d.id] || Date.now();
    d.since = nsince[d.id] || null;
    const was = prev && prev[d.id];
    if (was && was !== d.status) {
      const wasOff = was === 'unavailable' || was === 'partial';
      if (wasOff !== isOff(d)) ev.unshift({ t: Date.now(), name: d.name, integ: d.integ, kind: isOff(d) ? 'falha' : 'recuperado' });
    }
  });
  localStorage.setItem('prev', JSON.stringify(now));
  localStorage.setItem('since', JSON.stringify(nsince));
  localStorage.setItem('events', JSON.stringify(ev.slice(0, 100)));
}

export async function loadDevices() {
  const list = await api(CONFIG.PATHS.devices);
  const ds = list.map(d => {
    const entities = d.entities || [];
    const integrations = d.integrations || [];
    return {
      ...d,
      name: d.name || '(sem nome)',
      area: d.area || 'Sem cômodo',
      status: d.status || 'no_entities',
      entities,
      integrations,
      integ: integrations.join(', ') || '—',
      types: [...new Set(entities.map(e => e.split('.')[0]))],
      bad: d.unavailable_entities || [],
    };
  });
  track(ds);
  return { ds, at: new Date() };
}

export function nav(active) {
  const links = [['painel', '/', 'Painel'], ['controle', '/static/controle.html', 'Controle'], ['localidades', '/static/localidades.html', 'Localidades']];
  document.getElementById('nav').innerHTML = `
  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-40">
    <div class="max-w-[1400px] mx-auto px-4 h-12 flex items-center gap-2 overflow-x-auto">
      <span id="live" class="w-2 h-2 rounded-full shrink-0 bg-slate-500" title="Conexão com a API"></span>
      <span class="font-semibold text-slate-100 whitespace-nowrap mr-3">Monitor Home Assistant</span>
      ${links.map(([k, h, l]) => `<a href="${h}" class="px-3 py-1 rounded-md text-sm whitespace-nowrap ${k === active ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-400 hover:text-slate-200'}">${l}</a>`).join('')}
      <label class="ml-auto flex items-center gap-1.5 text-xs text-slate-400 whitespace-nowrap cursor-pointer"><input id="demo" type="checkbox" class="accent-indigo-500"> Ocultar demo</label>
      <button id="cfg" class="text-slate-400 hover:text-slate-200 text-lg" title="API key">⚙</button>
    </div>
  </header>`;
  const cb = document.getElementById('demo');
  cb.checked = pref('hideDemo', true);
  cb.onchange = () => { setPref('hideDemo', cb.checked); window.dispatchEvent(new Event('prefs')); };
  document.getElementById('cfg').onclick = () => {
    const k = prompt('API key (deixe vazio se a API não exigir):', CONFIG.API_KEY);
    if (k === null) return;
    localStorage.setItem('apiKey', k.trim());
    location.reload();
  };
}

export function auto(fn) {
  fn();
  return setInterval(fn, CONFIG.REFRESH_MS);
}
