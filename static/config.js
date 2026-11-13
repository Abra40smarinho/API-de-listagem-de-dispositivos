// URL base e chave podem ser trocadas pelo botão ⚙ do menu (ficam no localStorage).
export const CONFIG = {
  BASE_URL: localStorage.getItem('baseUrl') || window.API_BASE_URL || window.location.origin,
  API_KEY: localStorage.getItem('apiKey') || '',
  REFRESH_MS: 30000,
  PATHS: {
    devices: '/devices?include_states=true', // traz status de todos os dispositivos
    health: '/health',
    telegram: '/notifications/telegram',     // POST (precisa existir na API)
    reconnect: '/devices/reconnect',         // POST (precisa existir na API)
  },
};
