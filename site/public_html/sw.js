// Service worker mínimo: só torna o site instalável (PWA). API nunca vai para cache.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()))
self.addEventListener('fetch', () => {})
