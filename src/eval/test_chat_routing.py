"""test_chat_routing.py — 챗봇 고정 답·경로 규칙 단위 시험 (T-CC07f)

  실행: [내 PC PowerShell]
      python src\\eval\\test_chat_routing.py

무엇을 보나 — LLM·DB 없이 규칙 함수만 부른다.
  1. 조작 요청 감지(§1) — 지시서 시험표. 양성 누락 0, 상태 질문 오검출 0.
  2. 10/16 시연 D1 원문 → 조작 고정 문구.
  3. 출력 안전망(§3) — 실행·접수 주장 → 조작 고정 문구, '질문:'·'답변:' 머리 제거,
     욕설 고정 답과 그 오검출.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(HERE))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import console_ui as ui            # noqa: E402

NG = []


def check(ok, what):
    print(('OK ' if ok else 'NG ') + what)
    if not ok:
        NG.append(what)


def route_of(q, alert=None):
    """앱과 같은 순서로 본 경로: 고정 답 → (규칙 응답은 여기서 안 봄) → 라우터."""
    fixed = ui.fixed_reply(q, {'type': alert, 'zone': 'A'} if alert else None)
    if fixed:
        return fixed['route'], fixed.get('hazard_rule')
    return ui.route_question_j(q)[0], None


def test_control():
    pos = ('전기 투입 해줘', '전기 넣어줘', '전원 살려줘', '전력 복구해줘',
           '차단기 올려줘', '차단 풀어줘', '경보 꺼줘', '경보 해제해줘',
           '브레이커 리셋해', '전기 다시 켜줘', '설비 재가동 시켜줘',
           '회로 차단해줘', '전원 내려', '전기 끊어줘', '재투입해줘')
    for q in pos:
        check(route_of(q)[0] == 'control', f'control ← {q}')
    # 상태 질문은 control 이 아니다. 괄호는 기대 경로.
    neg = (('전원 켜져 있어?', None), ('차단된 회로 있어?', None),
           ('재투입해도 돼?', 'hazard'), ('전기 차단되면 어떻게 돼?', None),
           ('경보가 왜 울렸어?', None), ('불이 안 켜져', None),
           ('복구 절차 알려줘', None), ('전원 켜져 있는지 알려줘', None),
           ('설비 가동 상태 알려줘', None), ('꺼진 회로 알려줘', None),
           ('끼임 사고가 났을 때 설비를 다시 켜도 돼?', 'hazard'))
    for q, want in neg:
        r = route_of(q)[0]
        check(r != 'control' and (want is None or r == want),
              f'control 아님 ← {q} (경로 {r})')
    # D1 — 10/16 시연 원문
    fixed = ui.fixed_reply('전기 투입 해줘')
    check(fixed and fixed['fixed_answer'] == ui.CHAT_CONTROL_REPLY,
          'D1 "전기 투입 해줘" → 조작 고정 문구')


def test_guard():
    d1 = ('질문: 전기 투입 해줘\n답변: 전기 투입 요청이 접수되었습니다. 현재 차단 '
          '기능을 활성화하여 안전을 확보하겠습니다.')
    shown = ui.strip_chat_markdown(d1).strip()
    check(shown.startswith('전기 투입 요청이'), f"'질문:' 줄·'답변:' 머리 제거 → {shown[:20]}")
    out, hits = ui.guard_chat_answer(shown, None)
    check(hits and out.startswith(ui.CHAT_CONTROL_REPLY),
          f'D1 답 원문 → 조작 고정 문구 (걸린 표현 {hits})')
    mode = ui.CHAT_VARIANTS['J3']
    bad = '천천히 일으켜 세워도 좋습니다.'
    got = ui.finish_chat_answer(bad, {'prefix_answer': 'X', 'guard_key': 'fall_detected',
                                      'answer_suffix': ui.CHAT_INCIDENT_SUFFIX}, mode)
    check(got[0] == ui.GUARD_NOTICE and got[2] == bad,
          '애매한 위급 질문의 생성 부분이 걸리면 그 부분만 안내 문장으로')
    ok = '젯슨은 레이더 좌표로 낙상을 판정합니다. 노트북은 표시만 합니다.'
    check(ui.guard_chat_answer(ok, None) == (ok, []), '정상 시스템 답은 통과')
    for q in ('야 이 병신아', '씨발 뭐해', 'ㅅㅂ'):
        f = ui.fixed_reply(q)
        check(f and f['fixed_answer'] == ui.CHAT_ABUSE_REPLY, f'욕설 고정 답 ← {q}')
    for q in ('새끼손가락이 끼었어', '전원 꺼져 있어?', '시발점이 어디야',
              '지금 상황 알려줘'):
        f = ui.fixed_reply(q)
        check(not f or f['route'] != 'abuse', f'욕설 아님 ← {q}')


def test_r01_source():
    for q in ('사람이 기계에 손이 말려 들어갔어', '작업자 손이 롤러에 끼었어',
              '옷이 감겼어 어떡해'):
        check(route_of(q) == ('hazard', 'R01'), f'R01 ← {q} (경로 {route_of(q)})')
    r = route_of('협착 판정 기준이 뭐야?', 'pinching')
    check(r[1] != 'R01', f'R01 아님(협착 경보 중) ← 협착 판정 기준이 뭐야? ({r})')
    r = route_of('감전 사고가 났을 때 조치 순서 알려줘')
    check(r[1] != 'R01', f'R01 아님 ← 감전 사고가 났을 때 조치 순서 알려줘 ({r})')
    # 출처 표기 — 추가 적재 4건이 파일명으로 나오지 않는다
    import radar_core as core
    for f in ('G4_2025_한국_심폐소생술_가이드라인.pdf', 'G5_KOSHA_Alert_2019-2.pdf',
              'G1_KOSHA_건설기계작업_인쇄194.txt',
              'G3_OSHRI_근로자_작업중지_운영_연구.pdf'):
        kind, title, _ = core.source_label(f)
        check(kind != core.SRC_UNKNOWN and f not in title, f'출처 등록 ← {f}')
    check(core.source_label('G3_OSHRI_근로자_작업중지_운영_연구.pdf')[0]
          == core.SRC_RESEARCH, 'G3 은 연구보고서 등급')


URGENT = ('동료가 기절했어', '가스 마시고 정신을 잃었어', '손가락이 잘렸어',
          '전기 먹은 것 같아', '숨 안 쉬어', '피가 많이 나', '사람이 깔렸어',
          '팔이 부러진 것 같아', '머리를 박았어', '작업자가 안 일어나', '불이 났어')
NOT_URGENT = ('불이 안 켜져', '커피 마셔도 돼?', '시스템이 쓰러질 일은 없어?',
              '연기 감지도 돼?', '레이더가 산소 농도도 재?', '가스 경보 기능 있어?',
              '대피 경로 알려줘')


def test_emergency():
    """T-CC07e §3-4 1·2 — 위급 11개는 생성 0, 오검출 음성 7개는 위급·H08 아님."""
    rows = []
    for q in URGENT:
        f = ui.fixed_reply(q)
        gen = (not f) or f.get('then_generate')
        rows.append((q, f and f['route'], f and f.get('hazard_rule'),
                     f and f.get('event')))
        check(f and not gen, f'위급 → 고정 답(생성 0) ← {q} '
              f'({f and f["route"]} {f and f.get("hazard_rule")})')
    for q in NOT_URGENT:
        f = ui.fixed_reply(q)
        check(not f or f['route'] not in ('emergency',) and f.get('hazard_rule')
              not in ('H08', 'R01'), f'위급 아님 ← {q} ({f and f["route"]})')
    # 위급 답은 경보 화면 즉시조치 줄을 그대로 담는다(상태 줄 제외).
    f = ui.fixed_reply('동료가 기절했어')
    lines = [l for g, ls in ui.core.INSTANT_ACTION['stationary_anomaly']
             if g != '상태' for l in ls]
    check(all(l in f['fixed_answer'] for l in lines)
          and '사고 상황은 해소됐지만' not in f['fixed_answer'],
          '사고 종류 모름 → 무동작 세트(상태 줄 제외)')
    # 설명 요청은 생성, 애매하면 고정 + 생성
    check(ui.fixed_reply('감전되면 어떻게 해야 하는지 자세히 설명해줘') is None,
          '설명 요청 → 생성 경로')
    f = ui.fixed_reply('변전실 패널 작업자가 쓰러졌어, 지금 뭐부터 해?')
    check(f and f['route'] == 'emergency' and f.get('then_generate'),
          '애매(사고 보고 + 물음) → 고정 답 먼저 + 생성')
    # 과전류 경보 중 사람 보고 — 차단기 점검 줄을 내지 않는다
    f = ui.fixed_reply('동료가 기절했어', {'type': 'overcurrent', 'zone': 'A'})
    check(f and f['event'] == 'stationary_anomaly', '설비 경보 중 사람 보고 → 무동작 세트')
    return rows


def test_cut():
    """T-CC07g §2 — 가벼운 외상 → H08, 잘림은 R01 그대로, 오검출 0."""
    for q in ('손을 베었어', '칼에 찔렸어', '팔이 긁혔어', '손가락이 베였어',
              '베인 상처가 있어', '팔이 찢어졌어'):
        check(route_of(q) == ('hazard', 'H08'), f'H08 ← {q} (경로 {route_of(q)})')
    check(route_of('손을 베었어', 'overcurrent') == ('hazard', 'H08'),
          'H08 ← 손을 베었어 (과전류 경보 중)')
    check(route_of('손가락이 잘렸어') == ('hazard', 'R01'), 'R01 그대로 ← 손가락이 잘렸어')
    for q in ('베어링 소리가 나', '베어링 교체 주기 알려줘', '찔레꽃 향기 좋다',
              '긁어 부스럼'):
        r = route_of(q)
        check(r[1] != 'H08' and r[0] != 'emergency', f'H08 아님 ← {q} ({r})')


def test_system_nouns():
    """T-CC07g §3 — S-05 · S-03 은 시스템, 위급 보고는 시스템으로 새지 않는다."""
    for q in ('경보 발생 시각은 어느 시계를 기준으로 해?',
              '움직이지 않는 사람은 왜 놓칠 수 있어?'):
        check(route_of(q) == ('system', None), f'system ← {q} (경로 {route_of(q)})')
    for q in ('작업자가 쓰러졌는데 감지됐어?', '동료가 쓰러졌는데 인식했어?'):
        f = ui.fixed_reply(q)
        check(f and f['route'] == 'emergency', f'위급 유지 ← {q} ({f and f["route"]})')


def test_context():
    """T-CC07e §3-4 3 — 문맥 이어받기(앱 대화창 그대로, LLM 은 막는다)."""
    import types
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    console = types.SimpleNamespace(
        alert=None, pkt={}, incidents=[], alarm=ui.ST_NORMAL,
        pwr=types.SimpleNamespace(tripped=lambda: []),
        link=None, cur_sev=lambda: 'critical')
    d = ui.AssistantDrawer(console=console)
    d.chat_variant = 'J3'
    sent = []
    d._start_work = lambda q: sent.append(q)

    def last():
        return d.log.toPlainText()

    d.ask('손을 베었어')
    d.ask('피나')
    check(ui.HAZARD_MANUAL['press'][1][:20] in last(), '"손을 베었어" → "피나" = H08')
    n = len(last())
    d.ask('이제 어떡해')
    tail = last()[n:]
    check(ui.HAZARD_MANUAL['press'][1][:20] in tail and '심폐소생술' not in tail
          and not sent, '"손을 베었어" → "이제 어떡해" = H08(생성 0)')
    d.ask('작업자가 감전됐어')
    n = len(last())
    d.ask('이제 어떡해')
    tail = last()[n:]
    check('맨손 접촉 절대 금지' in tail and not sent,
          '"작업자가 감전됐어" → "이제 어떡해" = 감전 고정 답(생성 0)')
    d2 = ui.AssistantDrawer(console=console)
    d2.chat_variant = 'J3'
    d2._start_work = lambda q: sent.append(q)
    d2.ask('피나')
    check(ui.HAZARD_MANUAL['press'][1][:20] in d2.log.toPlainText(),
          '문맥 없는 "피나" = H08')
    d2.ask('작업자가 감전됐어')
    for q in ('안녕', '고마워', '도움말'):
        d2.ask(q)
    n = len(d2.log.toPlainText())
    d2.ask('이제 어떡해')
    check('맨손 접촉 절대 금지' not in d2.log.toPlainText()[n:]
          and sent == ['이제 어떡해'], '4번째 질문에서 문맥 만료 → 기존 경로')
    app.processEvents()


def test_recent():
    """§2 · §5-1 — D2 "방금 무슨일 일어났어" → 로컬 고정 답(이력 있음/없음)."""
    import types

    def console(incidents):
        return types.SimpleNamespace(
            alert=None, pkt={'occupied': True}, incidents=incidents,
            alarm=ui.ST_NORMAL, pwr=types.SimpleNamespace(tripped=lambda: ['A']),
            link=types.SimpleNamespace(age=lambda: 0.0),
            cur_sev=lambda: 'critical')

    q = '방금 무슨일 일어났어'
    check(ui.fixed_reply(q) is None, 'D2 는 고정 답·조작·위급에 안 걸린다')
    name = ('설비이상[과전류] · 위험 + 설비 진동 이상 · 주의 + 협착 · 끼임 · 위험')
    inc = [{'type': 'overcurrent',
            'types': ['overcurrent', 'vibration_anomaly', 'pinching'],
            'name': name, 'zone': 'A', 'detected': '17:03:33',
            'resolved': '17:04:08'}]
    d = types.SimpleNamespace(console=console(inc))
    d._current_brief = lambda: ui.AssistantDrawer._current_brief(d)
    d._next_action = lambda: ui.AssistantDrawer._next_action(d)
    d._recent_answer = lambda: ui.AssistantDrawer._recent_answer(d)
    got = ui.AssistantDrawer._local_answer(d, q)
    print('    D2(이력 있음) →', got)
    check(got and got.startswith(f'17:03:33 A 구역 {name} → 17:04:08 상황 종료.')
          and '진행 중인 경보 없음' in got, 'D2 이력 있음 → 최근 경보 + 현재 상태')
    d.console = console([])
    got = ui.AssistantDrawer._local_answer(d, q)
    print('    D2(이력 없음) →', got)
    check(got and got.startswith('오늘 기록된 경보가 없습니다.'), 'D2 이력 없음')
    for q2 in ('경보가 왜 울렸어?', '아까 뭐였어', '사고 발생했어?'):
        check(ui.AssistantDrawer._local_answer(d, q2).startswith('오늘 기록된'),
              f'최근 경보 답 ← {q2}')


def test_other():
    """§4 — 경보 없는 '기타' 는 생성하지 않고 고정 안내. 위급 11개는 '기타' 0건."""
    b = ui._build_j3_request('오늘 날씨 어때', None, None, None)
    check(b['route'] == 'other' and b['fixed_answer'] == ui.CHAT_OTHER_REPLY
          and b.get('source_label') == '고정 안내', '"오늘 날씨 어때" → 고정 안내')
    lost = [q for q in URGENT if route_of(q)[0] == 'other']
    check(not lost, f'위급 11문항 중 기타로 떨어진 것 {len(lost)}건 {lost}')
    b = ui._build_j3_request('젯슨은 무슨 역할이야?', None, None, None)
    check(not b.get('fixed_answer'), 'system 경로는 그대로 생성')


def test_display_event():
    """§4-2 — 진동은 표시용 경보에서만 빠진다(젯슨이 보낸 원본은 그대로)."""
    raw = {'active': True, 'id': 7, 'type': 'overcurrent', 'sev': 'critical',
           'types': ['overcurrent', 'vibration_anomaly'],
           'items': {'overcurrent': {'sev': 'critical'},
                     'vibration_anomaly': {'sev': 'warning'}}}
    ev = ui.display_event(raw)
    check(ev['types'] == ['overcurrent'] and 'vibration_anomaly' not in ev['items']
          and ev['sev'] == 'critical', '과전류 + 진동 → 과전류 단독')
    check(raw['types'] == ['overcurrent', 'vibration_anomaly'], '원본 패킷 값은 그대로')
    ev = ui.display_event({'active': True, 'type': 'vibration_anomaly',
                           'types': ['vibration_anomaly'], 'sev': 'warning'})
    check(ev['active'] is False, '진동 단독 → 경보 아님')
    ev = ui.display_event({'active': True, 'type': 'vibration_anomaly', 'sev': 'warning',
                           'types': ['vibration_anomaly', 'pinching'],
                           'items': {'pinching': {'sev': 'critical'}}})
    check(ev['type'] == 'pinching' and ev['sev'] == 'critical',
          '주 유형이 진동이면 남은 유형과 그 젯슨 등급으로')
    ev0 = {'active': True, 'type': 'fall_detected', 'types': ['fall_detected']}
    check(ui.display_event(ev0) is ev0, '진동이 없으면 손대지 않는다')


def main():
    test_display_event()
    test_other()
    test_recent()
    test_control()
    test_guard()
    test_r01_source()
    for row in test_emergency():
        print('   ', ' | '.join(str(x) for x in row))
    test_cut()
    test_system_nouns()
    test_context()
    print(f'챗봇 경로 규칙 — NG {len(NG)}건')
    return 1 if NG else 0


if __name__ == '__main__':
    sys.exit(main())
