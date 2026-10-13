/* Moneta 2.1: soltanto asset statici pubblici in cache. Nessuna API o sessione. */
'use strict';
const CACHE = 'moneta-static-v2.2.3';
const STATIC = new Set(['/','/index.html','/app.js','/styles.css','/manifest.webmanifest','/icons/moneta-192.png','/icons/moneta-512.png']);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll([...STATIC])).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('moneta-static-') && key !== CACHE).map(key => caches.delete(key)))),self.clients.claim()]));
});
self.addEventListener('fetch', event => {
  const request=event.request;
  if(request.method !== 'GET')return;
  const url=new URL(request.url);
  if(url.origin !== self.location.origin)return;
  if(!STATIC.has(url.pathname))return;
  if(url.pathname==='/'||url.pathname==='/index.html'){
    event.respondWith(fetch(request).then(reply=>reply.ok?reply:Promise.reject(Error('non disponibile'))).catch(()=>caches.match('/index.html')));
    return;
  }
  event.respondWith(fetch(request).then(response => {
    if(response.ok){const clone=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(request,clone)));}
    return response;
  }).catch(()=>caches.match(request)));
});
