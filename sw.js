// TeamFlex Service Worker v347 — v346 원복(잘못된 consignment 필드로 PDD미스 판정 오류 → 복구)
const CACHE_NAME = 'teamflex-v592';
const SB_URL = 'https://czpinyfirgvkhdfnvkls.supabase.co';
const SB_KEY = 'sb_publishable_pRqR_NjX5quStpY26IjHfw_YQAhtwoN';

// ── 설치 / 활성화 ─────────────────────────────────────────────────────────────
// [프리즈 방지] 설치 시 앱 셸(HTML)을 현재 버전 캐시에 미리 담아둔다.
//   → 업데이트 직후 reload 시 네트워크가 느려도 캐시로 즉시 렌더(로고 멈춤 방지).
self.addEventListener('install', e => {
  e.waitUntil((async () => {
    try {
      const c = await caches.open(CACHE_NAME);
      await Promise.all(['/', '/index.html', '/TeamFlex_기사포털.html']
        .map(u => c.add(u).catch(() => {})));
    } catch (_) {}
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      // [프리즈 방지] 현재 버전 캐시는 남기고(방금 담은 셸 보존) 옛 버전만 삭제.
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = e.request.url;
  if (url.includes('supabase') || url.includes('googleapis')) return;

  // HTML 문서: 캐시 우선(즉시 로드) + 백그라운드 갱신. 단 '</html>'로 끝나는 정상 응답만 캐시 저장.
  //   → 접속은 항상 즉시(네트워크 대기 X = 스플래시 멈춤 방지), 절단된 파일은 캐시에 안 박힘.
  const isDoc = e.request.mode === 'navigate' || url.indexOf('TeamFlex_') >= 0 || url.endsWith('.html') || url.endsWith('/');
  if (isDoc) {
    // [프리즈 방지·핵심] 캐시 우선 — 캐시에 셸이 있으면 '대기 0'으로 즉시 렌더(로고 멈춤 원천 차단).
    //   최신본은 백그라운드로 받아 캐시에 갱신 → 다음 실행 때 반영. 새 배포는 SW 버전업→reload로 즉시 적용.
    //   캐시가 아예 없을 때만(최초 설치·프리캐시 실패) 네트워크를 기다리되 8초 타임아웃으로 무한 hang 차단.
    e.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(e.request);
      const netP = fetch(e.request).then(resp => {
        if (resp && resp.ok) {
          resp.clone().text().then(txt => {
            if (txt.indexOf('</html>') >= 0) cache.put(e.request, resp.clone()).catch(() => {});
          }).catch(() => {});
        }
        return resp;
      }).catch(() => null);
      if (cached) return cached;                     // 캐시 있으면 즉시
      const net = await Promise.race([netP, new Promise(r => setTimeout(() => r(null), 8000))]);
      return net || new Response('<!doctype html><meta charset="utf-8"><body style="font-family:sans-serif;text-align:center;padding:44px;color:#33475b"><h2>TeamFlex</h2><p>네트워크 연결 후 새로고침 해주세요.</p></body>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    })());
    return;
  }

  // 그 외 정적 자원: 캐시 우선(stale-while-revalidate)
  e.respondWith((async () => {
    try {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(e.request);
      const netP = fetch(e.request).then(resp => {
        if (resp && resp.ok && resp.type === 'basic') { try { cache.put(e.request, resp.clone()); } catch (_) {} }
        return resp;
      }).catch(() => null);
      return cached || (await netP) || cached;
    } catch (_) {
      return fetch(e.request).catch(() => caches.match(e.request));
    }
  })());
});

// ── IndexedDB 헬퍼 ───────────────────────────────────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('TeamFlex_SW', 1);
    req.onupgradeneeded = e => {
      if (!e.target.result.objectStoreNames.contains('store'))
        e.target.result.createObjectStore('store');
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}
async function dbGet(key) {
  const db = await openDB();
  return new Promise((res, rej) => {
    const r = db.transaction('store', 'readonly').objectStore('store').get(key);
    r.onsuccess = e => res(e.target.result);
    r.onerror = rej;
  });
}
async function dbSet(key, value) {
  const db = await openDB();
  return new Promise((res, rej) => {
    const r = db.transaction('store', 'readwrite').objectStore('store').put(value, key);
    r.onsuccess = () => res();
    r.onerror = rej;
  });
}

// ── 앱 → SW 메시지 수신 ──────────────────────────────────────────────────────
self.addEventListener('message', async e => {
  const data = e.data;
  if (!data) return;

  if (data.type === 'USER_LOGIN') {
    await dbSet('userInfo', data.user);
  } else if (data.type === 'SNAPSHOT_UPDATE') {
    await dbSet('snap_' + data.userName, data.snapshot);
    await dbSet('lastCheck_' + data.userName, new Date().toISOString());
  }
});

// ── 주기적 백그라운드 체크 (앱 꺼진 상태에서도 동작) ──────────────────────────
self.addEventListener('periodicsync', e => {
  if (e.tag === 'tf-schedule-check') {
    e.waitUntil(checkScheduleInBackground());
  }
});

async function checkScheduleInBackground() {
  const userInfo = await dbGet('userInfo');
  if (!userInfo) return;

  const { name, role } = userInfo;
  const today = new Date().toISOString().slice(0, 10);

  // Supabase REST API 직접 조회
  let url = `${SB_URL}/rest/v1/weekly_schedules?work_date=gte.${today}&select=work_date,driver_name,route,grp_leaders,synced_at&order=work_date.asc`;
  if (role === 'driver') url += `&driver_name=eq.${encodeURIComponent(name)}`;

  const resp = await fetch(url, {
    headers: { 'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY }
  }).catch(() => null);
  if (!resp || !resp.ok) return;

  let rows = await resp.json();

  // 조장/팀장: grp_leaders 필터
  if (role === 'sub' || role === 'leader') {
    rows = rows.filter(r => {
      let gl = [];
      try { gl = typeof r.grp_leaders === 'string' ? JSON.parse(r.grp_leaders || '[]') : (r.grp_leaders || []); } catch (e) {}
      return gl.includes(name);
    });
  }

  // 현재 스냅샷
  const currSnap = {};
  rows.forEach(r => { currSnap[r.work_date + '|' + r.route] = r.driver_name || ''; });

  // 이전 스냅샷 & 마지막 체크 시간
  const prevSnap = await dbGet('snap_' + name) || {};
  const lastCheck = await dbGet('lastCheck_' + name) || '';

  // 스냅샷 업데이트
  await dbSet('snap_' + name, currSnap);
  await dbSet('lastCheck_' + name, new Date().toISOString());

  if (Object.keys(prevSnap).length === 0) return; // 첫 실행 → 기준값만 저장

  // 변경 감지 (오늘 이전 날짜는 무시 — 날짜 경계 오탐 방지)
  const allKeys = new Set([...Object.keys(prevSnap), ...Object.keys(currSnap)]);
  const changes = [];

  for (const key of allKeys) {
    const [workDate, route] = key.split('|');
    if (workDate < today) continue; // 과거 날짜 건너뜀

    const oldD = prevSnap[key] || '';
    const newD = currSnap[key] || '';
    if (oldD === newD) continue;

    let relevant = false;
    if (role === 'admin' || role === 'leader' || role === 'sub') relevant = true;
    else if (role === 'driver') relevant = (name === oldD || name === newD);
    if (!relevant) continue;

    changes.push({ workDate, route, oldDriver: oldD, newDriver: newD });
  }

  if (changes.length === 0) return;

  // 알림 텍스트 생성
  const lines = changes.slice(0, 4).map(c => {
    const [, m, d] = (c.workDate || '').split('-');
    const ds = parseInt(m) + '월 ' + parseInt(d) + '일';
    let ch = '';
    if (c.oldDriver && c.newDriver && c.oldDriver !== c.newDriver)
      ch = c.oldDriver + ' → ' + c.newDriver;
    else if (c.newDriver) ch = c.newDriver + ' 신규 배정';
    else ch = c.oldDriver + ' 배정 취소';
    return ds + ' [' + (c.route || '') + '] ' + ch;
  });
  if (changes.length > 4) lines.push('외 ' + (changes.length - 4) + '건 더');

  // 스케줄 변경 알림 임시 비활성화
  return;
    await self.registration.showNotification('📅 업무 변경 알림 ' + changes.length + '건', {
    body: lines.join('\n'),
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: 'tf-sched-' + Date.now(),
    renotify: true,
    requireInteraction: true,
    data: { url: '/TeamFlex_기사포털.html' }
  });
}

// ── 서버 Push 수신 ────────────────────────────────────────────────────────────
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) {}

  const title = d.title || 'TeamFlex 공지';
  const opts = {
    body:               d.body || '새 알림이 있습니다.',
    icon:               '/icons/icon-192.png',
    badge:              '/icons/icon-192.png',
    tag:                'tf-' + Date.now(),
    renotify:           true,
    requireInteraction: true,
    silent:             false,
    data:               d.data || {}
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

// ── 알림 클릭 → 앱 열기 ──────────────────────────────────────────────────────
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const targetUrl = (e.notification.data && e.notification.data.url)
    ? e.notification.data.url
    : '/TeamFlex_기사포털.html';

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
      for (const c of cs) {
        if (c.url && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});

// ── 푸시 구독 자동 갱신 (브라우저가 구독을 교체/만료시킬 때) ──────────────────
// 죽은 구독을 그대로 두지 않고, SW가 즉시 새 엔드포인트를 서버에 저장 + 옛것 삭제.
const VAPID_PUBLIC_KEY = 'BLzatW0XMphfRY8rlynT8AIwZPHk-z5IdTWREp37m7QLJOn04RR1YIU3AG9BVuZnYFIZOqypxe9SLUJLgKCq15w';
function _b64ToU8(b64) {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const s = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(s);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}
self.addEventListener('pushsubscriptionchange', e => {
  e.waitUntil((async () => {
    try {
      const userInfo = await dbGet('userInfo').catch(() => null);
      const driver_name = (userInfo && userInfo.name) || '';
      const role = (userInfo && userInfo.role) || 'driver';
      let appKey;
      try { appKey = e.oldSubscription && e.oldSubscription.options && e.oldSubscription.options.applicationServerKey; } catch (_) {}
      const newSub = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: appKey || _b64ToU8(VAPID_PUBLIC_KEY)
      });
      const k = newSub.getKey('p256dh'), a = newSub.getKey('auth');
      const p256dh = btoa(String.fromCharCode(...new Uint8Array(k)));
      const auth = btoa(String.fromCharCode(...new Uint8Array(a)));
      await fetch(SB_URL + '/rest/v1/push_subscriptions?on_conflict=endpoint', {
        method: 'POST',
        headers: { apikey: SB_KEY, 'Authorization': 'Bearer ' + SB_KEY, 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates' },
        body: JSON.stringify({ endpoint: newSub.endpoint, p256dh: p256dh, auth: auth, driver_name: driver_name, role: role })
      });
      if (e.oldSubscription && e.oldSubscription.endpoint) {
        await fetch(SB_URL + '/rest/v1/push_subscriptions?endpoint=eq.' + encodeURIComponent(e.oldSubscription.endpoint), {
          method: 'DELETE', headers: { apikey: SB_KEY, 'Authorization': 'Bearer ' + SB_KEY }
        });
      }
    } catch (err) { /* 갱신 실패는 다음 앱 열기 때 subscribePush가 재저장하므로 무시 */ }
  })());
});
