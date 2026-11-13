export const CONFIG = {
  // Mesma origem do painel (a API serve o painel). A chave é pedida pelo botão ⚙.
  BASE_URL: localStorage.getItem('baseUrl') || window.API_BASE_URL || window.location.origin,
  API_KEY: localStorage.getItem('apiKey') || '',
  REFRESH_MS: 30000,
  PATHS: {
    devices: '/devices?include_states=true', // todos os dispositivos, já com "status"
    health: '/health',
    telegram: '/notifications/telegram',     // POST (a API ainda não tem)
    reconnect: '/devices/reconnect',         // POST (a API ainda não tem)
  },
  // Mude para true quando criar esses endpoints na API
  FEATURES: { telegram: false, reconnect: false },
};
