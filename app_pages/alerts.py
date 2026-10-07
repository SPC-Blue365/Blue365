"""알림 센터: 이벤트 목록 · 처리 상태 관리 · 알림 발송."""

import pandas as pd
import streamlit as st

from qms.alerts import SEVERITY_ICON
from qms.diagnosis import diagnose
from qms.notify import dispatch, load_config
from qms.standards import STAGES
from qms.store import load_alert_status, update_alert_status
from qms.ui import get_ctx, open_diagnosis, sidebar

STATUSES = ["신규", "확인", "조치중", "종결"]

ctx = get_ctx()
sidebar(ctx)
period = ctx.store.period()
st.title("🚨 알림 센터")
if period is None:
    st.info("데이터가 없습니다.")
    st.stop()

df = ctx.events_df()
f1, f2, f3, f4, f5 = st.columns([1.6, 1.5, 1.6, 1.4, 1.6])
rng = f1.date_input("기간(이벤트 종료일)", value=(max(period[0].date(), (period[1] - pd.Timedelta(days=30)).date()),
                                             period[1].date()), min_value=period[0].date(), max_value=period[1].date())
sev = f2.multiselect("심각도", ["위험", "경고", "주의"], default=["위험", "경고"], placeholder="전체")
stages = f3.multiselect("공정", STAGES, default=[], placeholder="전체")
stats = f4.multiselect("처리상태", STATUSES, default=[], placeholder="전체")
q = f5.text_input("검색(항목·내용)", "")
if not isinstance(rng, (list, tuple)) or len(rng) != 2:
    st.stop()
start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(hours=23, minutes=59)

view = df.copy()
if len(view):
    view = view[(view["end"] >= start) & (view["start"] <= end)]
    if sev:
        view = view[view["severity"].isin(sev)]
    if stages:
        view = view[view["stage"].isin(stages)]
    if stats:
        view = view[view["status"].isin(stats)]
    if q:
        view = view[view["item_name"].str.contains(q, case=False) | view["message"].str.contains(q, case=False)]

m = st.columns(4)
for col, k in zip(m, ("위험", "경고", "주의")):
    col.metric(f"{SEVERITY_ICON[k]} {k}", int((view["severity"] == k).sum()) if len(view) else 0, border=True)
m[3].metric("미처리(신규)", int((view["status"] == "신규").sum()) if len(view) else 0, border=True)

if len(view) == 0:
    st.success("조건에 맞는 알림이 없습니다.", icon="✅")
    st.stop()

show = view.assign(심각도=view["severity"].map(lambda s: f"{SEVERITY_ICON[s]} {s}"),
                   품종=view["product"].fillna("-"))[
    ["심각도", "stage", "품종", "item_name", "rule_desc", "start", "end", "n_points", "worst_value", "limit_value", "unit",
     "patterns", "status", "assignee"]].rename(columns={
        "stage": "공정", "item_name": "항목", "rule_desc": "판정", "start": "시작", "end": "종료", "n_points": "점수",
        "worst_value": "최악값", "limit_value": "기준값", "unit": "단위", "patterns": "동반 패턴", "status": "상태",
        "assignee": "담당"})
st.caption("행을 선택하면 아래에서 처리 상태를 기록하고 원인 진단을 열 수 있습니다.")
sel = st.dataframe(show, hide_index=True, height=380, on_select="rerun", selection_mode="single-row", key="alert_table",
                   column_config={"시작": st.column_config.DatetimeColumn(format="MM/DD HH:mm"),
                                  "종료": st.column_config.DatetimeColumn(format="MM/DD HH:mm"),
                                  "최악값": st.column_config.NumberColumn(format="%.2f"),
                                  "기준값": st.column_config.NumberColumn(format="%.2f")})
rows = sel.selection.rows if sel and hasattr(sel, "selection") else []
if rows:
    r = view.iloc[rows[0]]
    with st.container(border=True):
        st.markdown(f"### {SEVERITY_ICON[r['severity']]} {r['message']}")
        if r["patterns"]:
            st.caption(f"동반 SPC 패턴: {r['patterns']}")
        a, b = st.columns([3, 1])
        with a.form(f"status_{r['event_id']}"):
            c1, c2 = st.columns(2)
            status = c1.selectbox("처리 상태", STATUSES, index=STATUSES.index(r["status"]) if r["status"] in STATUSES else 0)
            assignee = c2.text_input("담당자", r["assignee"])
            note = st.text_area("조치 내용·메모", r["note"], height=90,
                                placeholder="예) 07/21 석탄 혼탄비 조정, f-CaO 1.2%로 회복 확인")
            if st.form_submit_button("저장", type="primary"):
                update_alert_status(r["event_id"], status=status, assignee=assignee, note=note)
                st.toast("처리 상태를 저장했습니다.", icon="💾")
                st.rerun()
        if b.button("🧪 원인 진단 열기", type="primary", width="stretch"):
            open_diagnosis(r["event_id"])

with st.expander("🔔 알림 발송 (이메일·메신저)"):
    cfg = load_config()
    st.caption(f"발송 기준: {cfg.min_severity} 이상 · 이메일 {'사용' if cfg.email_enabled else '미사용'} · "
               f"웹훅 {'사용' if cfg.webhook_enabled else '미사용'} — 설정은 ⚙️ 기준·알림 설정")
    since_h = st.number_input("최근 N시간 내 종료된 이벤트만", 1, 24 * 90, 48)
    since = period[1] - pd.Timedelta(hours=int(since_h))
    status_df = load_alert_status()
    preview = dispatch(ctx.events, status_df, cfg, diagnose_fn=lambda e: diagnose(e, ctx.store, ctx.registry, ctx.settings),
                       since=since, dry_run=True)
    st.markdown(f"미발송 대상 **{len(preview)}건**")
    for p in preview[:5]:
        st.code(p["body"], language=None)
    if preview and st.button("지금 발송", disabled=not (cfg.email_enabled or cfg.webhook_enabled)):
        results = dispatch(ctx.events, status_df, cfg,
                           diagnose_fn=lambda e: diagnose(e, ctx.store, ctx.registry, ctx.settings), since=since)
        ok = 0
        for res in results:
            if res["sent"]:
                update_alert_status(res["event_id"], notified=1)
                ok += 1
            for ch, success, msg in res["channels"]:
                (st.success if success else st.error)(f"{ch}: {msg}")
        st.info(f"{ok}/{len(results)}건 발송 완료")
