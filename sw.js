// TeamFlex Service Worker v18 — 백그라운드 스케줄 체크 + Push 알림
const CACHE_NAME = 'teamflex-v79';
const SB_URL = 'https://czpinyfirgvkhdfnvkls.supabase.co';
const SB_KEY = 'sb_publishable_pRqR_NjX5quStpY26IjHfw_YQAhtwoN';

// ── 설치 / 활성화 ─────────────────────────────────────────────────────────────
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── 네트워크 우선 fetch ───────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = e.request.url;
  if (url.includes('supabase') || url.includes('googleapis')) return;
  e.respondWith(
    fetch(e.request, { cache: 'no-store' }).catch(() => caches.match(e.request))
  );
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
