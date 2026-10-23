"""종합 현황: 경영진·관리자가 한눈에 보는 품질 상태판."""

import pandas as pd
import streamlit as st

from qms.alerts import SEVERITY_ICON, SEVERITY_ORDER, latest_status
from qms.standards import STAGES
from qms.ui import fmt, get_ctx, open_diagnosis, page_header, recent_events, trend_figure

ctx = get_ctx()
reg, store = ctx.registry, ctx.store
period = store.period()

page_header(ctx, "🏭 Blue365 통합 품질관리 대시보드")
if period is None:
    st.info("데이터가 없습니다. 📥 데이터 관리에서 데이터를 업로드하거나 데모 데이터를 생성하세요.")
    st.stop()
end = period[1]
st.caption(f"마지막 데이터 {end:%Y-%m-%d %H:%M} · 기준: KS L 5201 포틀랜드 시멘트 + 사내 관리기준 · "
           "심각도 🔴위험(KS 이탈) 🟠경고(사내기준 이탈) 🟡주의(SPC 이상 패턴)")
if ctx.demo:
    st.info("현재 **데모 데이터**(가상의 공장 데이터, 이상 시나리오 6종 포함)로 실행 중입니다. "
            "실제 데이터는 📥 데이터 관리에서 엑셀 템플릿으로 업로드하세요.", icon="🧪")

# ── KPI ────────────────────────────────────────────────────────────────
recent = recent_events(ctx, days=7)
cnt = {k: sum(e.severity == k for e in recent) for k in ("위험", "경고", "주의")}
s28 = store.series("phy_s28", reg, "1종")
s28_recent = s28[s28.index >= s28.index.max() - pd.Timedelta(days=30)] if len(s28) else s28
s28_prev = s28[(s28.index < s28.index.max() - pd.Timedelta(days=30)) &
               (s28.index >= s28.index.max() - pd.Timedelta(days=60))] if len(s28) else s28
pred = store.series("pred_s28", reg, "1종")
lim28 = reg["phy_s28"].limits_for("1종")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔴 위험 (최근 7일)", f"{cnt['위험']}건", help="KS 규격 이탈 이벤트 — 출하 판정 필요", border=True)
c2.metric("🟠 경고 (최근 7일)", f"{cnt['경고']}건", help="사내 관리기준·시험조건 이탈 이벤트", border=True)
c3.metric("🟡 주의 (최근 7일)", f"{cnt['주의']}건", help="규격 이내이나 SPC 판정규칙(추세·평균 이동) 위반", border=True)
if len(s28_recent):
    delta = s28_recent.mean() - s28_prev.mean() if len(s28_prev) else None
    c4.metric("28일 강도(1종)", f"{s28_recent.mean():.1f} MPa",
              delta=f"{delta:+.1f} MPa 전월 대비" if delta is not None else None,
              help=f"최근 30일 평균. KS {lim28.ks_min:g} MPa 이상 · 사내 {lim28.lsl:g} MPa 이상", border=True)
else:
    c4.metric("28일 강도(1종)", "-", border=True)
if len(pred):
    low = int((pred < lim28.lsl).sum())
    c5.metric("28일 예측 최저", f"{pred.min():.1f} MPa",
              delta=f"🟠 미달 예측 {low}로트" if low else "🟢 미달 예측 없음", delta_color="off", delta_arrow="off",
              help=f"28일 결과 미도래 로트의 예측 최저값(조기강도·분말도·C₃S 회귀, 추정치). 사내기준 {lim28.lsl:g} MPa",
              border=True)
else:
    c5.metric("28일 예측", "-", border=True)

# ── 공정 상태판 ─────────────────────────────────────────────────────────
st.subheader("공정별 상태")
status = latest_status(store, reg, ctx.settings, ctx.events)
stage_order = [s for s in STAGES if s != "시험 조건"]
cols = st.columns(3)
for i, stage in enumerate(stage_order):
    sub = status[status["stage"] == stage] if len(status) else status
    with cols[i % 3].container(border=True):
        worst = "정상"
        if len(sub):
            worst = max(sub["status"], key=lambda s: SEVERITY_ORDER[s])
        st.markdown(f"**{SEVERITY_ICON[worst]} {stage}**")
        if len(sub) == 0:
            st.caption("핵심 항목 데이터 없음")
            continue
        for _key, grp in sub.groupby("item_key", sort=False):
            worst_i = max(grp["status"], key=lambda s: SEVERITY_ORDER[s])
            nd, unit = int(grp["decimals"].iloc[0]), grp["unit"].iloc[0]
            if grp["product"].notna().any():
                vals = " · ".join(f"{r['product']} **{fmt(r['last_value'], nd)}**" for _, r in grp.iterrows())
                vals += f" {unit}"
            else:
                vals = f"**{fmt(grp['last_value'].iloc[0], nd, unit)}**"
            last = grp["last_time"].max()
            st.markdown(f"{SEVERITY_ICON[worst_i]} {grp['item_name'].iloc[0]} — {vals} "
                        f"<span style='color:gray;font-size:0.85em'>({last:%m/%d %H:%M})</span>", unsafe_allow_html=True)

# ── 조치 필요 알림 + 강도 추이 ──────────────────────────────────────────
left, right = st.columns([1, 1.25])
with left:
    st.subheader("조치가 필요한 알림")
    act = sorted([e for e in recent_events(ctx, days=14, min_sev="경고")],
                 key=lambda e: (SEVERITY_ORDER[e.severity], e.end), reverse=True)[:7]
    if not act:
        st.success("최근 14일간 위험·경고 알림이 없습니다.", icon="✅")
    for e in act:
        with st.container(border=True):
            a, b = st.columns([4, 1])
            prod = f"[{e.product}] " if e.product else ""
            a.markdown(f"**{SEVERITY_ICON[e.severity]} {prod}{e.item_name}** — {e.rule_desc}  \n"
                       f"<span style='font-size:0.85em;color:gray'>{e.start:%m/%d %H:%M} ~ {e.end:%m/%d %H:%M} · "
                       f"{'최대' if e.direction == 'high' else '최소'} {fmt(e.worst_value, e.decimals, e.unit)}</span>",
                       unsafe_allow_html=True)
            if b.button("진단", key=f"dx_{e.event_id}", help="원인 진단·솔루션 보기"):
                open_diagnosis(e.event_id)
with right:
    st.subheader("압축강도 추이")
    r1, r2, r3 = st.columns(3)
    ages = {"1일": "phy_s1", "3일": "phy_s3", "7일": "phy_s7", "28일": "phy_s28"}
    age = r1.selectbox("재령", list(ages), index=3, key="ov_age")
    prod = r2.selectbox("품종", ["1종", "3종"], key="ov_prod")
    days = {"30일": 30, "90일": 90, "180일": 180, "1년": 365}[r3.selectbox("기간", ["30일", "90일", "180일", "1년"], index=1, key="ov_days")]
    fig = trend_figure(ctx, ages[age], prod, start=end - pd.Timedelta(days=days), height=340)
    if fig:
        st.plotly_chart(fig, key="ov_strength")
        st.caption("실선 = 실측, 점선 = 예측(재령 미도래 로트, 추정치). 음영 = 경고/위험 이벤트 구간. 여러 항목을 함께 보려면 📉 그래프 보기.")
    else:
        st.caption(f"{prod} {age} 강도 자료가 없습니다.")

# ── 핵심 공정 지표 ─────────────────────────────────────────────────────
st.subheader("핵심 공정 지표 (최근 14일)")
KEY_TRENDS = (("rm_lsf", None), ("clk_fcao", None), ("cem_blaine", "1종"), ("cem_blaine", "3종"))
figs = []
for key, prod in KEY_TRENDS:
    if key not in reg:
        continue
    it = reg[key]
    fig = trend_figure(ctx, key, prod, start=end - pd.Timedelta(days=14), resample="8h",
                       title=f"{it.name}" + (f" [{prod}]" if prod else "") + " · 8h 평균", height=400, show_target=False)
    if fig:
        fig.update_xaxes(range=[end - pd.Timedelta(days=14), end + pd.Timedelta(hours=6)])   # 이벤트 음영이 축을 넓히지 않게
        figs.append((f"ov_{key}_{prod or 'all'}", fig))
if not figs:
    st.caption("최근 14일 공정 데이터가 없습니다.")
for i in range(0, len(figs), 2):                     # 한 줄에 2개씩 크게
    row = st.columns(2)
    for col, (k, fig) in zip(row, figs[i:i + 2]):
        col.plotly_chart(fig, key=k)
