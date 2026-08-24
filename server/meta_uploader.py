#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# TeamFlex → 쿠팡(fly.coupang) 스케줄 자동 업로더
#   poller PC의 9223 크롬(로그인된 fly 세션)에 CDP로 붙어서:
#     스케줄 페이지 → [업로드] 모달 → <input type=file>에 파일 '직접 주입'(OS 파일창 안 뜸) → [업로드] 클릭
#   파일은 '업무 엑셀 업로드' 양식(변경리스트/전체리스트) 그대로.
#
# ★ 안전장치: DRY_RUN=True 면 파일 주입·모달 확인까지만 하고 '최종 업로드 클릭'은 생략.
#             /tmp/meta_*.png 스크린샷으로 각 단계 확인 후, 문제없으면 DRY_RUN=False 로 실제 반영.
#
# 사용:  python3 meta_uploader.py /path/to/변경리스트.xlsx
import json, time, sys, os, base64
import requests
try:
    import websocket   # pip install websocket-client
except ImportError:
    print("pip install websocket-client requests --break-system-packages"); sys.exit(1)

CDP_PORT  = 9223
SCHED_URL = "https://fly.coupang.com/ui/schedule"
DRY_RUN   = False    # 실반영 ON (2026-08-24 테스트 통과 후 전환)
LAST_RESULT = ''     # 마지막 업로드 결과 메시지(성공='OK', 실패=쿠팡 오류내역)

def log(m): print("[meta] " + str(m), flush=True)

def _open_new_schedule_tab():
    # ★ 신선 대시보드 탭을 절대 건드리지 않도록 '항상 새 탭'으로 스케줄 페이지를 연다.
    #    (기존 fly 탭을 재사용/이동하면 신선 스크랩이 깨지므로 금지)
    try:
        r = requests.put(f"http://localhost:{CDP_PORT}/json/new?{SCHED_URL}", timeout=8)
        time.sleep(4)
        info = r.json() if r.content else {}
        if info.get("webSocketDebuggerUrl"):
            return info
        # 폴백: 목록에서 방금 연 스케줄 탭 찾기
        for t in requests.get(f"http://localhost:{CDP_PORT}/json", timeout=5).json():
            if t.get("type") == "page" and "ui/schedule" in (t.get("url") or ""):
                return t
    except Exception as e:
        log("CDP(9223) 스케줄 새 탭 열기 실패 — fly 크롬이 안 떠 있음? " + str(e))
    return None

def _close_tab(tab_id):
    try:
        requests.get(f"http://localhost:{CDP_PORT}/json/close/{tab_id}", timeout=5)
        log("스케줄 탭 닫음: " + str(tab_id))
    except Exception:
        pass

class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=35, max_size=None)
        self._i = 0
    def send(self, method, params=None, timeout=35):
        self._i += 1; mid = self._i
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.ws.settimeout(timeout)
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(method + " 오류: " + json.dumps(msg["error"], ensure_ascii=False))
                return msg.get("result", {})
        raise TimeoutError(method)
    def js(self, expr, timeout=35):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout)
        return r.get("result", {}).get("value")
    def shot(self, path):
        try:
            r = self.send("Page.captureScreenshot", {"format": "png"}, 30)
            open(path, "wb").write(base64.b64decode(r["data"])); log("스크린샷 → " + path)
        except Exception as e:
            log("스크린샷 실패: " + str(e))
    def close(self):
        try: self.ws.close()
        except Exception: pass

def upload(file_path, target_week=None, kind=None):
    global LAST_RESULT
    # 주차별/전체(전체교체)는 '당일 포함 주차' 금지 (방어) — KST 기준
    if kind in ("week", "full") and target_week:
        import datetime as _dt
        _kst = (_dt.datetime.utcnow() + _dt.timedelta(hours=9)).strftime("%Y-%m-%d")
        try:
            _ws = _dt.datetime.strptime(str(target_week)[:10], "%Y-%m-%d")
            _we = (_ws + _dt.timedelta(days=6)).strftime("%Y-%m-%d")
            if str(target_week)[:10] <= _kst <= _we:
                LAST_RESULT = "당일 포함 주차는 주차별/전체 업로드 불가(초기화 위험) — 다음 주차부터만 가능"
                log("[FAIL] " + LAST_RESULT); return False
        except Exception:
            pass
    file_path = os.path.abspath(file_path)
    if not os.path.exists(file_path):
        log("파일이 없습니다: " + file_path); return False
    tab = _open_new_schedule_tab()
    if not tab:
        return False
    tab_id = tab.get("id")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.send("Page.enable"); cdp.send("DOM.enable"); cdp.send("Runtime.enable")

        # 1) 이 탭은 이미 스케줄 페이지로 열렸음 → 로딩 대기(안 열렸으면 재이동)
        time.sleep(3)
        cur = ""
        try: cur = cdp.js("location.href") or ""
        except Exception: pass
        if "ui/schedule" not in cur:
            cdp.send("Page.navigate", {"url": SCHED_URL}); time.sleep(6)
        cdp.shot("/tmp/meta_1_page.png")

        # 1.4) 로그인 페이지면 즉시 중단 (세션 로그아웃) — 절대 false 성공/재로그인 유발 안 함
        loginpg = cdp.js("(()=>{const u=location.href||'';const t=(document.body&&document.body.innerText)||'';"
                         "const hasPw=!![...document.querySelectorAll('input')].find(i=>i.type==='password');"
                         "if(/login|auth|signin|sso|realms/i.test(u)||(hasPw&&/아이디|로그인|비밀번호/.test(t)))return 'LOGIN';return 'OK';})()")
        if loginpg == 'LOGIN':
            LAST_RESULT = "fly.coupang 로그아웃 상태 — poller에서 재로그인 필요(업로드 중단)"
            log("[FAIL] " + LAST_RESULT); return False

        # 1.5) 주차 이동 + 캠프 전체선택 + 검색 (target_week 지정 시에만)
        #      쿠팡은 '화면에 선택된 주차'에만 업로드가 반영되므로, 반드시 목표 주차로 맞춘다.
        def _read_week():
            try:
                return cdp.js("(()=>{const ins=[...document.querySelectorAll('input')];"
                              "let i=ins.find(x=>(x.placeholder||'')==='Select week');"
                              "let v=i?(i.value||i.title||''):'';"
                              "if(!/^\\d{4}-\\d{2}-\\d{2}/.test(v)){const r=ins.find(x=>/^\\d{4}-\\d{2}-\\d{2}\\s*-/.test(x.value||''));v=r?(r.value||''):'';}"
                              "const m=(v||'').match(/(\\d{4}-\\d{2}-\\d{2})/);return m?m[1]:null;})()")
            except Exception:
                return None
        # 실제 마우스 이벤트 헬퍼 (React/antd 피커·셀렉트는 JS 합성클릭에 반응 안 함 → CDP Input 사용)
        def _rclick_xy(x, y):
            cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
            cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
        def _box(selector):
            return cdp.js("(()=>{const e=document.querySelector(" + repr(selector) + ");if(!e)return null;"
                          "const r=e.getBoundingClientRect();if(r.width<1||r.height<1)return null;"
                          "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()")
        def _rclick_sel(selector):
            b = _box(selector)
            if not b: return False
            _rclick_xy(b["x"], b["y"]); return True
        _NORM = ("const norm=s=>{const m=String(s||'').match(/(\\d{4})\\D+(\\d{1,2})\\D+(\\d{1,2})/);"
                 "return m?(m[1]+'-'+('0'+m[2]).slice(-2)+'-'+('0'+m[3]).slice(-2)):'';};")

        if target_week:
            target_week = str(target_week)[:10]
            cur_wk = _read_week()
            log("현재 주차: %s / 목표 주차: %s" % (cur_wk, target_week))
            # 주차 피커 실제 클릭 → 달력 드롭다운 열기
            if not (_rclick_sel("input[placeholder='Select week']") or _rclick_sel(".ant-picker")):
                LAST_RESULT = "주차 피커 없음"; log("[FAIL] " + LAST_RESULT); return False
            time.sleep(1.3)
            has = cdp.js("document.querySelectorAll('.ant-picker-cell-in-view').length")
            if not has:
                _rclick_sel(".ant-picker"); time.sleep(1.3)
                has = cdp.js("document.querySelectorAll('.ant-picker-cell-in-view').length")
            if not has:
                LAST_RESULT = "주차 달력 열기 실패"; log("[FAIL] " + LAST_RESULT); return False
            picked = False
            for _i in range(24):
                b = cdp.js("(()=>{const tw=" + repr(target_week) + ";" + _NORM +
                           "const c=[...document.querySelectorAll('.ant-picker-cell-in-view')].find(c=>norm(c.getAttribute('title'))===tw);"
                           "if(!c)return null;const t=c.querySelector('.ant-picker-cell-inner')||c;const r=t.getBoundingClientRect();"
                           "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()")
                if b:
                    _rclick_xy(b["x"], b["y"]); picked = True; break
                first = cdp.js("(()=>{const tw=" + repr(target_week) + ";" + _NORM +
                               "const iv=[...document.querySelectorAll('.ant-picker-cell-in-view')].map(c=>norm(c.getAttribute('title'))).filter(Boolean).sort();"
                               "return iv[0]||'';})()")
                if not first:
                    LAST_RESULT = "달력 셀 없음"; log("[FAIL] " + LAST_RESULT); return False
                sel = ".ant-picker-header-next-btn" if first < target_week else ".ant-picker-header-prev-btn"
                if not _rclick_sel(sel):
                    LAST_RESULT = "달 이동 버튼 없음 (%s)" % sel; log("[FAIL] " + LAST_RESULT); return False
                time.sleep(0.7)
            time.sleep(1.0)
            cur_wk = _read_week()
            if not picked or cur_wk != target_week:
                LAST_RESULT = "주차 선택 실패 (현재 %s, 목표 %s)" % (cur_wk, target_week)
                log("[FAIL] " + LAST_RESULT); return False
            log("[OK] 주차 도달: " + str(cur_wk))
            # 캠프 전체선택 (실제 클릭)
            opened = _rclick_sel(".ant-select-multiple") or _rclick_sel(".ant-tree-select") or _rclick_sel(".ant-select")
            time.sleep(1.0)
            allbox = cdp.js("(()=>{const o=[...document.querySelectorAll('.ant-select-tree-title,.ant-select-item-option-content,span,label')]"
                            ".find(e=>/^전체선택$/.test((e.textContent||'').trim()));if(!o)return null;"
                            "const node=o.closest('.ant-select-tree-treenode')||o.closest('.ant-select-item')||o;"
                            "const cb=node.querySelector('.ant-select-tree-checkbox,.ant-checkbox')||o;const r=cb.getBoundingClientRect();"
                            "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()")
            if allbox:
                _rclick_xy(allbox["x"], allbox["y"]); log("캠프 전체선택 클릭")
            else:
                log("캠프 전체선택 항목 못 찾음(열림=%s)" % opened)
            time.sleep(0.6)
            try:
                cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "windowsVirtualKeyCode": 27})
                cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "windowsVirtualKeyCode": 27})
            except Exception: pass
            time.sleep(0.5)
            # 검색 (실제 클릭)
            sb = cdp.js("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/검색/.test(x.textContent||''));"
                        "if(!b)return null;const r=b.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()")
            if sb:
                _rclick_xy(sb["x"], sb["y"]); log("검색 클릭")
            else:
                log("검색 버튼 못 찾음")
            time.sleep(3)
            cur2 = _read_week()
            if cur2 != target_week:
                LAST_RESULT = "검색 후 주차 불일치: %s (목표 %s)" % (cur2, target_week)
                log("[FAIL] " + LAST_RESULT); return False
            # ★ 주차별/전체(전체교체)는 업로드 전 '초기화'로 그 주차 기존 스케줄을 비운다 (변경분은 초기화 금지)
            if kind in ("week", "full"):
                rz = cdp.js("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/초\\s*기\\s*화/.test(x.textContent||''));"
                            "if(!b)return null;const r=b.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()")
                if rz:
                    _rclick_xy(rz["x"], rz["y"]); log("초기화 클릭 (주차별/전체 전체교체)"); time.sleep(1.5)
                    # 초기화 확인 다이얼로그가 뜨면 확인
                    cdp.js("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^(확인|예|네|초기화)$/.test((x.textContent||'').trim())||/초기화하시겠|비우시겠/.test(x.textContent||''));if(b){b.click();return 1;}return 0;})()")
                    time.sleep(2)
                else:
                    log("초기화 버튼 못 찾음 — 초기화 없이 진행")
            cdp.shot("/tmp/meta_15_ready.png")

        # 2~5) 업로드 모달 → 파일 주입 → 최종 업로드 → 결과 판별
        #       '동일 영업점 다른 사용자가 업로드 중'(잠금 400)은 잠깐 뒤 재시도로 자동 극복
        for attempt in range(4):
            if attempt > 0:
                log("업로드 잠금 → 10초 대기 후 재시도 (%d/3)" % attempt)
                try:
                    for _e in range(2):
                        cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "windowsVirtualKeyCode": 27})
                        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "windowsVirtualKeyCode": 27})
                except Exception: pass
                time.sleep(10)
            # 2) 상단 [업로드] 버튼 클릭 (다운로드 제외)
            r = cdp.js(r"""(()=>{const bs=[...document.querySelectorAll('button')]
                .filter(b=>/업\s*로\s*드/.test(b.textContent)&&!/다운/.test(b.textContent));
                if(!bs.length)return 'NO_UPLOAD_BTN'; bs[0].click(); return 'CLICK_OK';})()""")
            log("상단 업로드 버튼: " + str(r)); time.sleep(2)
            if attempt == 0: cdp.shot("/tmp/meta_2_modal.png")
            # 3) 파일 input '직접 주입'
            doc  = cdp.send("DOM.getDocument", {"depth": -1})
            root = doc["root"]["nodeId"]
            q    = cdp.send("DOM.querySelector", {"nodeId": root, "selector": "input[type=file]"})
            node = q.get("nodeId", 0)
            if not node:
                log("파일 input(input[type=file])을 못 찾았습니다.")
                cdp.shot("/tmp/meta_err_noinput.png")
                LAST_RESULT = "업로드 모달 파일칸 없음"; return False
            cdp.send("DOM.setFileInputFiles", {"files": [file_path], "nodeId": node})
            log("파일 주입 완료: " + file_path); time.sleep(2)
            if attempt == 0: cdp.shot("/tmp/meta_3_file.png")
            # 4) 최종 업로드
            if DRY_RUN:
                log("DRY_RUN=True → 최종 '업로드' 클릭 생략(실제 반영 안 함).")
                return True
            r2 = cdp.js(r"""(()=>{const bs=[...document.querySelectorAll('button')]
                .filter(b=>b.textContent.trim()==='업로드'); if(!bs.length)return 'NO_CONFIRM';
                bs[bs.length-1].click(); return 'CONFIRM_OK';})()""")
            log("모달 업로드 클릭: " + str(r2)); time.sleep(4)
            # 4b) '입력하신 입차 일정을 다시 확인해 주세요' 경고 → '네, 확인했습니다' 클릭(필수: 이걸 눌러야 그리드 반영)
            ack = cdp.js("(()=>{const b=[...document.querySelectorAll('button')]"
                         ".find(x=>/확인했습니다|네[,\\s]*확인/.test((x.textContent||'')));"
                         "if(!b)return 'NO_ACK';const r=b.getBoundingClientRect();"
                         "window.__ackxy={x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};return 'ACK';})()")
            if ack == 'ACK':
                axy = cdp.js("window.__ackxy")
                if axy: _rclick_xy(axy["x"], axy["y"]); log("‘네, 확인했습니다’ 클릭")
                time.sleep(3)
            cdp.shot("/tmp/meta_4_done.png")
            # 4c) 잠금/실패 판별
            res = cdp.js(r"""(()=>{const t=(document.body&&document.body.innerText)||'';
                if(/다른 사용자가 업로드|잠시 후 다시|영업점의 다른 사용자/.test(t)){
                  const m=t.replace(/\s+/g,' ').match(/[^.]*(다른 사용자가 업로드|잠시 후 다시)[^.]*\.?/);
                  return 'LOCK::'+((m?m[0]:'업로드 잠금').slice(0,200));}
                if(/저장에 실패|업로드.*실패|오류내역|존재하지 않는 아이디|벤더 소속이 아/.test(t)){
                  const nodes=[...document.querySelectorAll('*')];let box=null;
                  for(const e of nodes){const x=e.textContent||'';
                    if(/오류내역|존재하지 않는 아이디|저장에 실패/.test(x)&&x.length<1200){box=e;break;}}
                  const msg=(box?box.textContent:'업로드 실패').replace(/\s+/g,' ').trim().slice(0,700);
                  return 'FAIL::'+msg;}
                return 'DONE';})()""")
            if isinstance(res, str) and res.startswith('LOCK::'):
                log("엑셀 업로드 결과: ⏳ 잠금 → " + res[6:]); continue
            if isinstance(res, str) and res.startswith('FAIL::'):
                LAST_RESULT = res[6:]
                log("엑셀 업로드 결과: ❌ 실패 → " + LAST_RESULT); return False
            # 5) 엑셀 업로드는 '네, 확인했습니다' 단계에서 이미 반영/저장됨.
            #    '스케줄 저장하기'는 활성일 때만 추가로 눌러 커밋(비활성=이미 반영됨=정상, 실패 아님)
            time.sleep(1.5)
            svb = cdp.js("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/스케줄\\s*저장/.test(x.textContent||''));"
                         "if(!b)return null;const dis=b.disabled||b.getAttribute('disabled')!=null||/disabled/.test(String(b.className));"
                         "const r=b.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),disabled:!!dis};})()")
            if svb and not svb.get("disabled"):
                _rclick_xy(svb["x"], svb["y"]); log("스케줄 저장하기 클릭(활성)"); time.sleep(2)
                cdp.js("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^(확인|저장|저장하기|예|네)$/.test((x.textContent||'').trim())||/확인했습니다|저장하시겠/.test(x.textContent||''));if(b)b.click();return 1;})()")
                time.sleep(5)
                cdp.shot("/tmp/meta_5_saved.png")
                sres = cdp.js(r"""(()=>{const t=(document.body&&document.body.innerText)||'';
                    if(/다른 사용자가 업로드|잠시 후 다시|영업점의 다른 사용자/.test(t))return 'LOCK';
                    if(/저장.*실패|실패하였습니다|마감.*불가|저장.*불가|불가능/.test(t)){
                      const m=t.replace(/\s+/g,' ').match(/[^.]*(실패|마감|불가)[^.]*\.?/);
                      return 'FAIL::'+((m?m[0]:'저장 실패').slice(0,200));}
                    return 'OK';})()""")
                if isinstance(sres, str) and sres.startswith('LOCK'):
                    log("저장 잠금 → 재시도"); continue
                if isinstance(sres, str) and sres.startswith('FAIL::'):
                    LAST_RESULT = "저장 실패: " + sres[6:]; log("[FAIL] " + LAST_RESULT); return False
                LAST_RESULT = '저장 완료'; log("스케줄 저장 결과: ✅ 저장 완료"); return True
            # 저장 버튼이 비활성/없음 → 업로드 '확인' 단계에서 이미 반영됨(정상)
            cdp.shot("/tmp/meta_5_saved.png")
            LAST_RESULT = '업로드 반영 완료' if ack == 'ACK' else '반영 처리됨(확인창 미표시)'
            log("✅ " + LAST_RESULT + " (저장버튼 비활성=이미 반영)"); return True
        # 재시도 소진(잠금 지속)
        LAST_RESULT = "업로드 잠금 지속: 동일 영업점의 다른 사용자가 업로드 중(잠시 후 다시)"
        log("[FAIL] " + LAST_RESULT); return False
    finally:
        cdp.close()
        if tab_id: _close_tab(tab_id)

if __name__ == "__main__":
    fp = sys.argv[1] if len(sys.argv) > 1 else ""
    wk = sys.argv[2] if len(sys.argv) > 2 else None
    if not fp:
        print("사용법: python3 meta_uploader.py <업로드할_엑셀_경로> [목표주차 YYYY-MM-DD]"); sys.exit(1)
    ok = upload(fp, wk)
    print("RESULT:", "OK" if ok else "FAIL", "(DRY_RUN=%s)" % DRY_RUN, "| LAST_RESULT:", LAST_RESULT)
