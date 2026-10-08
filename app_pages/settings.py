"""기준·알림 설정: 사내 관리기준 · SPC/진단 설정 · 알림 채널 · KS 근거."""

import pandas as pd
import streamlit as st

from qms import llm
from qms.notify import (
    NotifyConfig,
    format_message,
    load_config,
    save_config,
    send_email,
    send_webhook,
)
from qms.spc import RULE_NAMES
from qms.standards import (
    DEFAULT_SETTINGS,
    KS_ISO679,
    KS_L5201,
    USER_STANDARDS_PATH,
    Limits,
    save_registry,
    save_settings,
)
from qms.ui import get_ctx, refresh, sidebar

ctx = get_ctx()
sidebar(ctx)
reg = ctx.registry
st.title("⚙️ 기준·알림 설정")
tab1, tab2, tab3, tab5, tab4 = st.tabs(["사내 관리기준", "SPC·진단 설정", "알림 채널", "AI(LLM)", "KS 규격 근거"])

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

with tab5:
    acfg = llm.load_llm_config()
    st.markdown("**AI 솔루션 보고서(Claude API)** — 강도·응결 제어, 6가크롬 저감, 배합 검토 화면에서 계산 결과를 근거로 "
                "보고서를 작성합니다. 숫자는 시스템이 계산하고 AI는 해설·조치 계획만 씁니다(사실/추정/경험칙 구분 표기).")
    st.warning("**데이터 보안**: AI 보고서를 만들면 계산 결과 요약(JSON)이 외부 API(Anthropic)로 전송됩니다. 원 데이터 DB·개인정보는 "
               "보내지 않지만 공정 정보가 포함되므로 **사내 정보보안 승인 후** 사용하세요. 각 화면의 'AI에 전달되는 데이터 보기'에서 "
               "전송 내용을 확인할 수 있습니다.", icon="🔐")
    with st.form("llm_form"):
        a1, a2, a3 = st.columns([1, 1.6, 1])
        en = a1.toggle("AI 보고서 사용", value=acfg.enabled)
        model = a2.selectbox("모델", list(llm.MODELS), index=list(llm.MODELS).index(acfg.model),
                             format_func=lambda m: f"{llm.MODELS[m]['label']} — 입력 ${llm.MODELS[m]['in']:g}/출력 ${llm.MODELS[m]['out']:g} (100만 토큰)")
        effort = a3.selectbox("추론 깊이(effort)", llm.EFFORTS, index=llm.EFFORTS.index(acfg.effort),
                              help="높을수록 깊이 검토하지만 시간·비용 증가. 보고서 용도는 high 권장")
        b1, b2, b3, b4 = st.columns(4)
        max_tok = b1.number_input("최대 출력 토큰", 2000, 64000, int(acfg.max_tokens), step=1000)
        fb = b2.toggle("응답 거부 시 대체 모델 사용", value=acfg.use_fallbacks,
                       help="안전 정책으로 응답이 거부되면 서버가 권장 대체 모델로 다시 시도(Haiku 제외)")
        krw = b3.number_input("환율(원/$, 비용 표시용)", 500.0, 3000.0, float(acfg.usd_krw), step=10.0)
        base = b4.text_input("API 주소(사내 게이트웨이 시)", acfg.base_url, placeholder="비우면 기본 API")
        if st.form_submit_button("저장", type="primary"):
            llm.save_llm_config(llm.LLMConfig(en, model, effort, int(max_tok), fb, base.strip(), acfg.timeout, float(krw)))
            st.success("저장했습니다.")
            st.rerun()
    ok_key, src = llm.credential_status()
    ready, msg = llm.ai_ready(acfg)
    st.caption(f"API 키: {'설정됨 — ' + src if ok_key else '없음'} · anthropic 패키지: {'설치됨' if llm.sdk_available() else '미설치'} · "
               f"상태: {msg}")
    st.markdown("API 키는 화면에 저장하지 않습니다. 서버 환경변수 `ANTHROPIC_API_KEY` 또는 `.streamlit/secrets.toml`의 "
                "`[anthropic]` 섹션 `api_key`에 넣으세요(저장소에 올라가지 않음).")
    est = pd.DataFrame([{"모델": llm.MODELS[m]["label"], "1회 예상 비용($)": llm.estimate_call_cost(m),
                         "1회 예상 비용(원)": llm.estimate_call_cost(m) * acfg.usd_krw,
                         "월 100회(원)": llm.estimate_call_cost(m) * acfg.usd_krw * 100} for m in llm.MODELS])
    st.markdown("**비용 추정**(입력 약 9천 토큰 중 지식베이스 6천 캐시 + 출력 약 4천 토큰 가정 — 추정)")
    st.dataframe(est, hide_index=True, column_config={"1회 예상 비용($)": st.column_config.NumberColumn(format="%.4f"),
                                                      "1회 예상 비용(원)": st.column_config.NumberColumn(format="%,.0f"),
                                                      "월 100회(원)": st.column_config.NumberColumn(format="%,.0f")})
    logs = llm.read_log()
    if logs:
        lg = pd.DataFrame([{"일시": e.get("ts"), "용도": llm.KINDS.get(e.get("kind"), e.get("kind")), "모델": e.get("served_model"),
                            "입력": (e.get("usage") or {}).get("input_tokens"), "출력": (e.get("usage") or {}).get("output_tokens"),
                            "비용($)": e.get("cost_usd"), "종료": e.get("stop_reason"), "오류": e.get("error") or ""}
                           for e in reversed(logs)])
        st.markdown(f"**사용 기록**(최근 {len(lg)}건, 합계 ${lg['비용($)'].fillna(0).sum():.3f}) — data/ai_log.jsonl")
        st.dataframe(lg, hide_index=True)

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
