"""기준·알림 설정: 사내 관리기준 · SPC/진단 설정 · 알림 채널 · KS 근거."""

import pandas as pd
import streamlit as st

from qms.notify import NotifyConfig, format_message, load_config, save_config, send_email, send_webhook
from qms.spc import RULE_NAMES
from qms.standards import DEFAULT_SETTINGS, KS_ISO679, KS_L5201, USER_STANDARDS_PATH, Limits, save_registry, save_settings
from qms.ui import get_ctx, refresh, sidebar

ctx = get_ctx()
sidebar(ctx)
reg = ctx.registry
st.title("⚙️ 기준·알림 설정")
tab1, tab2, tab3, tab4 = st.tabs(["사내 관리기준", "SPC·진단 설정", "알림 채널", "KS 규격 근거"])

with tab1:
    st.markdown("**사내 관리기준(하한·상한·목표)** 을 공장 기준으로 수정하세요. KS 값은 규격이므로 수정할 수 없습니다. "
                "기본값은 업계 경험칙 초기값입니다.")
    rows = []
    for it in reg.all():
        if it.prediction:
            continue
        for prod, lim in (list(it.limits.items()) or [("*", Limits())]):
            rows.append({"key": it.key, "적용": prod, "공정": it.stage, "항목": it.name, "단위": it.unit,
                         "KS 하한": lim.ks_min, "KS 상한": lim.ks_max, "사내 하한": lim.lsl, "사내 상한": lim.usl,
                         "목표": lim.target, "근거": it.ks_ref or it.basis})
    df = pd.DataFrame(rows)
    for col in ("KS 하한", "KS 상한", "사내 하한", "사내 상한", "목표"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    stage_f = st.multiselect("공정 필터", sorted(df["공정"].unique()), default=[], placeholder="전체 공정")
    view = df[df["공정"].isin(stage_f)] if stage_f else df
    edited = st.data_editor(view, hide_index=True, height=520, key="std_editor",
                            disabled=["key", "적용", "공정", "항목", "단위", "KS 하한", "KS 상한", "근거"],
                            column_config={"key": st.column_config.TextColumn("코드", width="small"),
                                           "적용": st.column_config.TextColumn("품종", help="* = 전 품종 공통")})
    c1, c2 = st.columns([1, 1])
    if c1.button("저장", type="primary"):
        overrides = {}
        for _, r in edited.iterrows():
            overrides.setdefault(r["key"], {})[r["적용"]] = {"lsl": r["사내 하한"], "usl": r["사내 상한"], "target": r["목표"]}
        reg.apply_overrides(overrides)
        save_registry(reg)
        refresh()
        st.success("저장했습니다. 알림·진단이 새 기준으로 다시 계산됩니다.")
        st.rerun()
    if c2.button("기본값으로 되돌리기"):
        USER_STANDARDS_PATH.unlink(missing_ok=True)
        refresh()
        st.rerun()

with tab2:
    s = dict(ctx.settings)
    with st.form("spc_form"):
        st.markdown("**SPC 기준기간** — 공정이 안정적이었던 기간으로 지정하세요(관리한계 계산 기준).")
        c1, c2, c3 = st.columns(3)
        mode = c1.radio("지정 방식", ["데이터 시작부터 N일", "기간 직접 지정"],
                        index=1 if s.get("baseline_start") else 0)
        days = c2.number_input("N(일)", 7, 365, int(s.get("baseline_days", 30)))
        period = ctx.store.period()
        rng = c3.date_input("기간", value=(pd.Timestamp(s["baseline_start"]).date() if s.get("baseline_start") else period[0].date(),
                                          pd.Timestamp(s["baseline_end"]).date() if s.get("baseline_end") else (period[0] + pd.Timedelta(days=30)).date()))
        st.markdown("**판정규칙** (전역 활성화 — 항목별 허용 규칙과 교집합 적용)")
        rules = st.multiselect("활성 규칙", list(RULE_NAMES), default=s.get("enabled_rules", ["R1", "R2", "R3"]),
                               format_func=lambda r: f"{r}: {RULE_NAMES[r].format(run=s.get('run_length', 9), trend=s.get('trend_length', 6))}")
        c4, c5, c6 = st.columns(3)
        run_l = c4.number_input("R2 연속 점 수", 6, 15, int(s.get("run_length", 9)))
        trend_l = c5.number_input("R3 연속 상승/하강 점 수", 5, 10, int(s.get("trend_length", 6)))
        ev_days = c6.number_input("원인 진단 비교 기준(이벤트 직전 N일)", 3, 60, int(s.get("evidence_baseline_days", 14)))
        if st.form_submit_button("저장", type="primary"):
            s.update(baseline_days=int(days), enabled_rules=rules, run_length=int(run_l), trend_length=int(trend_l),
                     evidence_baseline_days=int(ev_days))
            if mode == "기간 직접 지정" and isinstance(rng, (list, tuple)) and len(rng) == 2:
                s.update(baseline_start=str(rng[0]), baseline_end=str(rng[1]))
            else:
                s.update(baseline_start=None, baseline_end=None)
            save_settings(s)
            refresh()
            st.success("저장했습니다.")
            st.rerun()
    if st.button("SPC 설정 기본값 복원"):
        save_settings(dict(DEFAULT_SETTINGS))
        refresh()
        st.rerun()

with tab3:
    cfg = load_config()
    st.markdown("비밀번호·웹훅 URL은 화면에 저장하지 않습니다. `.streamlit/secrets.toml`의 `[notify]` 섹션"
                "(smtp_password, webhook_url) 또는 환경변수 `QMS_SMTP_PASSWORD`, `QMS_WEBHOOK_URL`로 설정하세요.")
    with st.form("notify_form"):
        min_sev = st.selectbox("발송 기준 심각도", ["위험", "경고", "주의"], index=["위험", "경고", "주의"].index(cfg.min_severity))
        st.markdown("**이메일(SMTP)**")
        e1, e2, e3, e4 = st.columns([1, 2, 1, 1])
        email_on = e1.toggle("사용", value=cfg.email_enabled, key="em_on")
        host = e2.text_input("SMTP 서버", cfg.smtp_host, placeholder="smtp.company.co.kr")
        port = e3.number_input("포트", 1, 65535, int(cfg.smtp_port))
        tls = e4.toggle("STARTTLS", value=cfg.smtp_tls)
        e5, e6 = st.columns(2)
        user = e5.text_input("계정", cfg.smtp_user)
        sender = e6.text_input("발신 주소", cfg.sender)
        rcpt = st.text_input("수신자(쉼표 구분)", ", ".join(cfg.recipients))
        st.markdown("**메신저 웹훅** (Slack · Microsoft Teams · 사내 메신저 일반 JSON)")
        w1, w2 = st.columns(2)
        wh_on = w1.toggle("사용", value=cfg.webhook_enabled, key="wh_on")
        wh_fmt = w2.selectbox("형식", ["slack", "teams", "generic"], index=["slack", "teams", "generic"].index(cfg.webhook_format))
        dash = st.text_input("대시보드 주소(알림 본문에 링크)", cfg.dashboard_url)
        if st.form_submit_button("저장", type="primary"):
            new = NotifyConfig(min_severity=min_sev, email_enabled=email_on, smtp_host=host, smtp_port=int(port), smtp_tls=tls,
                               smtp_user=user, sender=sender, recipients=[r.strip() for r in rcpt.split(",") if r.strip()],
                               webhook_enabled=wh_on, webhook_format=wh_fmt, dashboard_url=dash)
            save_config(new)
            st.success("저장했습니다.")
            st.rerun()
    st.caption(f"비밀값 상태: SMTP 비밀번호 {'설정됨' if cfg.smtp_password else '없음'} · 웹훅 URL {'설정됨' if cfg.webhook_url else '없음'}")
    t1, t2 = st.columns(2)
    if ctx.events:
        subject, body = format_message(ctx.events[0], "테스트 발송입니다.", [], cfg.dashboard_url)
        if t1.button("테스트 메일 발송"):
            ok, msg = send_email(cfg, "[QMS 테스트] " + subject, body)
            (st.success if ok else st.error)(msg)
        if t2.button("테스트 웹훅 발송"):
            ok, msg = send_webhook(cfg, "[QMS 테스트] " + subject, body)
            (st.success if ok else st.error)(msg)
    st.markdown("**자동 감시(무인 운영)** — 서버에서 아래 명령을 10~30분 주기로 실행(cron·작업 스케줄러)하면 "
                "새 데이터 반영 → 이상 감지 → 알림 발송이 자동으로 이뤄집니다.")
    st.code("python qms_monitor.py --import-dir ./inbox --since-hours 24", language="bash")

with tab4:
    st.markdown(f"""
| 구분 | 내용 | 근거 |
|---|---|---|
| 압축강도 1종 | 3일 12.5 / 7일 22.5 / 28일 42.5 MPa 이상 | {KS_L5201} |
| 압축강도 3종 | 1일 10.0 / 3일 20.0 / 7일 32.5 / 28일 47.5 MPa 이상 | {KS_L5201} |
| 분말도(Blaine) | 1종 2,800 · 3종 3,300 cm²/g 이상 | {KS_L5201} |
| 응결(비카) | 초결 60분 이상, 종결 10시간 이하 | {KS_L5201} |
| 안정도 | 오토클레이브 팽창도 0.8% 이하 | {KS_L5201} |
| 화학성분 | MgO 5.0% 이하 · SO₃ 1종 3.5% / 3종 4.5% 이하 · 강열감량 5.0% 이하(2016 개정 3.0→5.0%) | {KS_L5201} |
| 강도 시험조건 | 시험실 20±2 ℃·RH 50% 이상, 양생수 20±1 ℃ | {KS_ISO679} |

**출처**: [e나라표준인증 KS L 5201](https://standard.go.kr/KSCI/standardIntro/getStandardSearchView.do?ksNo=KSL5201),
[한국시멘트협회 KS 규격](http://www.cement.or.kr/tech_2014/standard.asp?sm=3_6_1) (2026-10 웹 검색으로 확인).
KS L ISO 679 시험조건은 ISO 679 규정값을 적용했으며 원문 대조가 필요합니다. 2·4·5종 기준은 원문 확인 후 추가하십시오.
""")
