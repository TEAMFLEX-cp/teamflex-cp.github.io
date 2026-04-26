// TeamFlex Service Worker v5 — Push 알림 최적화
const CACHE_NAME = 'teamflex-v5';

self.addEventListener('install', function(e) {
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(k) { return caches.delete(k); }));
    }).then(function() {
      return self.clients.claim();
    })
  );
});

// 네트워크 우선
self.addEventListener('fetch', function(e) {
  if (e.request.method !== 'GET') return;
  var url = e.request.url;
  if (url.indexOf('supabase') >= 0 || url.indexOf('googleapis') >= 0) return;
  e.respondWith(
    fetch(e.request, {cache: 'no-store'}).catch(function() {
      return caches.match(e.request);
    })
  );
});

// ── 푸시 알림 ── 태그를 타임스탬프로 매번 달리 해서 Android가 항상 소리를 냄
self.addEventListener('push', function(e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch(err) {}

  var title = d.title || 'TeamFlex 공지';
  var opts = {
    body:            d.body || '새 공지사항이 있습니다.',
    icon:            '/icons/icon-192.png',
    badge:           '/icons/icon-192.png',
    tag:             'tf-' + Date.now(),   // 매번 새 태그 → 항상 소리/진동
    renotify:        true,
    requireInteraction: true,
    silent:          false,                // 소리 명시적 허용
    vibrate:         [300, 150, 300, 150, 300],
    data:            d.data || {}
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

// 알림 클릭 → 앱 열기
self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({type:'window', includeUncontrolled:true}).then(function(cs) {
      for (var c of cs) {
        if (c.url && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow('/TeamFlex_기사포털.html');
    })
  );
});
