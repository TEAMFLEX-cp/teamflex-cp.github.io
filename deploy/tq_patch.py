import io, subprocess, shutil, sys, datetime
F='/opt/teamflex/app/teams_poller.py'
PY='/opt/teamflex/venv/bin/python'
OLD="    rows = []; tw = tsc = td = 0\n    for r in (routes or []):\n        w = int(r.get('consignment', 0) or 0)          # 실제 위탁(API 값)\n        sc = int(r.get('scan', 0) or 0)                 # 스캔\n        d = int(r.get('completed', 0) or 0) + int(r.get('undelivered', 0) or 0)   # 완료 = 완료+미배송\n        nm = _majority(r.get('route', '')) or _strip(r.get('worker', '') or '')\n        rows.append({'route': _abbr(r.get('route', '')), 'name': nm, 'w': w, 's': sc, 'd': d})\n        tw += w; tsc += sc; td += d"
NEW="    rows = []; tw = tsc = td = 0\n    def _tq_owner(sub):\n        o = rmap.get(sub) or (rmap.get(sub[:4]) if len(sub) >= 4 else None)\n        return _strip(o) if o else None\n    for r in (routes or []):\n        w = int(r.get('consignment', 0) or 0)          # 실제 위탁(API 값)\n        sc = int(r.get('scan', 0) or 0)                 # 스캔\n        d = int(r.get('completed', 0) or 0) + int(r.get('undelivered', 0) or 0)   # 완료 = 완료+미배송\n        tw += w; tsc += sc; td += d                     # 총합은 원본 기준(스플릿 무관)\n        raw = r.get('route', '')\n        subs = [x.strip() for x in _re.split(r'[,\\s]+', (raw or '').strip()) if x.strip()]\n        driver_subs = {}; unassigned = []\n        for sub in (subs if subs else [raw]):\n            o = _tq_owner(sub)\n            if o: driver_subs.setdefault(o, []).append(sub)\n            else: unassigned.append(sub)\n        total_sub = len(subs) if subs else 1\n        if not driver_subs:\n            # 배차표 매핑 실패 → 무인조회 worker 이름 폴백(없으면 빈칸)\n            rows.append({'route': _abbr(raw), 'name': _strip(r.get('worker', '') or ''), 'w': w, 's': sc, 'd': d})\n        elif len(driver_subs) == 1 and not unassigned:\n            rows.append({'route': _abbr(raw), 'name': list(driver_subs.keys())[0], 'w': w, 's': sc, 'd': d})\n        else:\n            # ── 복합: 신선처럼 기사별 라우트 비율로 물량 분배 → 각 기사 박스로 표시 ──\n            for drv, drs in driver_subs.items():\n                ratio = len(drs) / total_sub\n                rows.append({'route': _abbr(', '.join(drs)), 'name': drv,\n                             'w': round(w * ratio), 's': round(sc * ratio), 'd': round(d * ratio)})\n            if unassigned:\n                ur = len(unassigned) / total_sub\n                rows.append({'route': _abbr(', '.join(unassigned)), 'name': '혼합',\n                             'w': round(w * ur), 's': round(sc * ur), 'd': round(d * ur)})"
patched=False
s=io.open(F,encoding='utf-8').read()
if '복합: 신선처럼 기사별 라우트 비율' in s:
    print('ALREADY_PATCHED')
else:
    c=s.count(OLD)
    if c!=1:
        print('OLD_BLOCK_NOT_FOUND count='+str(c)+' ABORT'); sys.exit(1)
    io.open('/tmp/teams_poller_new.py','w',encoding='utf-8').write(s.replace(OLD,NEW,1))
    r=subprocess.run([PY,'-m','py_compile','/tmp/teams_poller_new.py'],capture_output=True,text=True)
    if r.returncode!=0:
        print('COMPILE_FAIL',r.stderr[:600]); sys.exit(1)
    bak=F+'.bak_tqsplit_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy(F,bak); shutil.move('/tmp/teams_poller_new.py',F); patched=True
    print('PATCH_OK backup='+bak)
if patched:
    unit=None
    allu=subprocess.run(['bash','-lc',"systemctl list-units --type=service --all --no-legend 2>/dev/null | awk '{print $1}'"],capture_output=True,text=True).stdout.split()
    cand=[u for u in allu if any(k in u.lower() for k in ('poll','teamflex','teams','tf-','fresh'))]
    for u in cand:
        es=subprocess.run(['systemctl','show',u,'-p','ExecStart'],capture_output=True,text=True).stdout
        if 'teams_poller.py' in es: unit=u; break
    if unit:
        subprocess.run(['systemctl','restart',unit]); print('RESTARTED_UNIT='+unit)
    else:
        subprocess.run(['pkill','-f','teams_poller.py']); print('PKILLED_fallback')
print('DONE')
