// TeamFlex Service Worker v3 — Network-First (캐시 없음)
// HTML/JS/CSS는 항상 네트워크에서 최신 버전을 받아옵니다.

const CACHE_NAME = 'teamflex-v3';

self.addEventListener('install', function(e) {
  self.skipWaiting();  // 새 SW 즉시 활성화
});

self.addEventListener('activate', function(e) {
  // 이전 캐시 전체 삭제
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(k) {
        console.log('[SW] 캐시 삭제:', k);
        return caches.delete(k);
      }));
    })
  );
  self.clients.claim();
});

// ── Fetch: 항상 네트워크 우선, 캐시 저장 안 함 ──────────────────
self.addEventListener('fetch', function(e) {
  // POST 요청은 그냥 통과
  if (e.request.method !== 'GET') return;

  // Supabase API 요청은 그냥 통과
  var url = e.request.url;
  if (url.indexOf('supabase') >= 0 || url.indexOf('googleapis') >= 0) return;

  e.respondWith(
    fetch(e.request, {cache: 'no-store'})
      .catch(function() {
        // 네트워크 없을 때만 캐시 fallback (아이콘 등)
        return caches.match(e.request);
      })
  );
});

// ── 푸시 알림 ────────────────────────────────────────────────────
self.addEventListener('push', function(e) {
  var d = e.data ? e.data.json() : {};
  var title = d.title || 'TeamFlex 공지';
  var opts = {
    body: d.body || '새 공지사항이 있습니다.',
    icon: d.icon || '/icons/icon-192.png',
    badge: d.badge || '/icons/icon-192.png',
    tag: d.tag || 'teamflex',
    renotify: true,
    requireInteraction: true,
    data: d.data || {}
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

// ── 알림 클릭 시 앱 열기 ──────────────────────────────────────────
self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({type:'window', includeUncontrolled:true}).then(function(cs) {
      for (var c of cs) {
        if (c.url && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow('/');
    })
  );
});
