#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# meta_upload_jobs 큐를 폴링해서 meta_uploader로 쿠팡(fly.coupang) 스케줄에 업로드하는 워커.
#   앱에서 [전체]/[주차별]/[변경분] 버튼을 누르면 Supabase에 pending 작업이 쌓임 → 이 워커가 하나씩 처리.
#   meta_uploader.DRY_RUN=True 인 동안은 실제 반영 없이(파일 주입/모달까지만) 상태만 done 처리.
import time, base64, os, sys, datetime, importlib
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meta_uploader

SB_URL = "https://czpinyfirgvkhdfnvkls.supabase.co"
SB_KEY = "sb_publishable_pRqR_NjX5quStpY26IjHfw_YQAhtwoN"
H = {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "Content-Type": "application/json"}
POLL_SEC = 15

def log(m): print("[worker] " + str(m), flush=True)
def _now(): return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def _get_pending():
    try:
        r = requests.get(SB_URL + "/rest/v1/meta_upload_jobs?status=eq.pending&order=id.asc&limit=1",
                         headers=H, timeout=10)
        d = r.json() if r.status_code == 200 else []
        return d[0] if d else None
    except Exception as e:
        log("큐 조회 오류: " + str(e)); return None

def _patch(jid, fields):
    fields["updated_at"] = _now()
    try:
        requests.patch(SB_URL + f"/rest/v1/meta_upload_jobs?id=eq.{jid}",
                       headers={**H, "Prefer": "return=minimal"}, json=fields, timeout=10)
    except Exception as e:
        log(f"#{jid} 상태 업데이트 오류: {e}")

def process(job):
    jid = job["id"]
    log(f"작업 #{jid} [{job.get('kind')}] {job.get('week_start') or ''} 시작")
    _patch(jid, {"status": "running"})
    try:
        b64 = job.get("xlsx_b64") or ""
        if not b64:
            _patch(jid, {"status": "failed", "result": "빈 파일"}); return
        # 최신 uploader 코드 자동 반영 (워커 재시작 불필요 — 콘솔 안 열어도 됨)
        try: importlib.reload(meta_uploader)
        except Exception as e: log(f"reload 경고: {e}")
        # 파일을 정식 경로에 저장하고 그 파일을 불러서 업로드에 사용
        os.makedirs("/opt/teamflex/app/meta_files", exist_ok=True)
        safe_wk = str(job.get("week_start") or "wk").replace("/", "-")
        path = f"/opt/teamflex/app/meta_files/{safe_wk}_{job.get('kind')}_{jid}.xlsx"
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        log(f"파일 저장: {path} ({os.path.getsize(path)} bytes)")
        ok = meta_uploader.upload(path, job.get("week_start"), job.get("kind"))
        tag = " (DRY_RUN)" if meta_uploader.DRY_RUN else ""
        detail = getattr(meta_uploader, "LAST_RESULT", "") or ("OK" if ok else "FAIL")
        _patch(jid, {"status": "done" if ok else "failed", "result": (detail + tag)[:800]})
        log(f"작업 #{jid} 완료: {'OK' if ok else 'FAIL'}{tag}")
    except Exception as e:
        _patch(jid, {"status": "failed", "result": str(e)[:400]})
        log(f"작업 #{jid} 오류: {e}")

def main():
    log("메타 업로드 워커 시작 (DRY_RUN=%s, poll=%ss)" % (meta_uploader.DRY_RUN, POLL_SEC))
    while True:
        j = _get_pending()
        if j:
            process(j)
        else:
            time.sleep(POLL_SEC)

if __name__ == "__main__":
    main()
