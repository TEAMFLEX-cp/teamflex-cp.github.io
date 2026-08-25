# teams_poller.py 각종요청 응답푸시 검증 + 전취건/분실건 라벨 보강 (비밀정보 없음)
import py_compile
P="/opt/teamflex/app/teams_poller.py"
s=open(P,encoding='utf-8').read()
has_fn   = "def push_notify_request_response" in s
has_call = "push_notify_request_response(row.get('requester_name'" in s
patched=False
if "'pretake':" not in s and "        'work': '업무 신청',\n    }" in s:
    s=s.replace("        'work': '업무 신청',\n    }",
                "        'work': '업무 신청',\n        'pretake': '전취건 반납 확인',\n        'lostret': '분실건 반납 확인',\n    }",1)
    open(P,'w',encoding='utf-8').write(s); patched=True
py_compile.compile(P,doraise=True)
print("HAS_FN=%s HAS_CALL=%s LABEL_PATCHED=%s"%(has_fn,has_call,patched))
