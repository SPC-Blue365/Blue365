"""종합 현황: 경영진·관리자가 한눈에 보는 품질 상태판."""

import pandas as pd
import streamlit as st

from qms import uikit as K
from qms.alerts import SEVERITY_ORDER, latest_status
from qms.standards import STAGES
from qms.ui import fmt, get_ctx, open_diagnosis, page_header, recent_events, trend_figure

ctx = get_ctx()
reg, store = ctx.registry, ctx.store
period = store.period()

act = sorted(recent_events(ctx, days=14, min_sev="경고"), key=lambda e: (SEVERITY_ORDER[e.severity], e.end), reverse=True)
if period is None:
    page_header(ctx, "🏭 Blue365 통합 품질관리 대시보드", headline="자료가\n**아직** 없어요")
    K.empty("📥 데이터 관리에서 자료를 올리거나 데모 데이터를 만들면 여기에 나타나요.")
    st.stop()
status = latest_status(store, reg, ctx.settings, ctx.events)
worst_all = max(status["status"], key=lambda s: SEVERITY_ORDER[s]) if len(status) else "정상"
hl = (f"조치가 필요한 알림이\n**{len(act)}건** 있어요" if act else
      "오늘은 전 공정이\n**정상**이에요" if worst_all == "정상" else f"**{worst_all}** 단계 항목을\n확인해 주세요")
page_header(ctx, "🏭 Blue365 통합 품질관리 대시보드", headline=hl,
            subtitle="기준 KS L 5201 포틀랜드 시멘트 + 사내 관리기준 · 위험 = KS 이탈 · 경고 = 사내기준 이탈 · 주의 = SPC 이상 패턴")
end = period[1]
if ctx.demo:
    K.banner("**데모 데이터**(가상의 공장 데이터, 이상 시나리오 6종 포함)로 실행 중이에요. 실제 자료는 📥 데이터 관리에서 올려 주세요.")

# ── 핵심 지표 카드(보는용 현황판과 같은 모양) ─────────────────────────────
recent = recent_events(ctx, days=7)
s28 = store.series("phy_s28", reg, "1종")
s28_recent = s28[s28.index >= s28.index.max() - pd.Timedelta(days=30)] if len(s28) else s28
s28_prev = s28[(s28.index < s28.index.max() - pd.Timedelta(days=30)) &
               (s28.index >= s28.index.max() - pd.Timedelta(days=60))] if len(s28) else s28
pred = store.series("pred_s28", reg, "1종")
lim28 = reg["phy_s28"].limits_for("1종")
cards = []
if len(s28_recent):
    delta = s28_recent.mean() - s28_prev.mean() if len(s28_prev) else None
    bad = lim28.ks_min is not None and s28_recent.min() < lim28.ks_min
    cards.append(K.kpi_card(len(cards), "28일 강도 평균", f"{s28_recent.mean():.1f}", "MPa",
                            f"28-day strength · KS ≥ {lim28.ks_min:g}" + (f" · 사내 {lim28.lsl:g}" if lim28.lsl is not None else ""),
                            "1종, 최근 30일" + (f" · 전월 대비 {delta:+.1f}" if delta is not None else ""), "bad" if bad else "ok"))
if len(pred):
    low = int((pred < lim28.lsl).sum()) if lim28.lsl is not None else 0
    cards.append(K.kpi_card(len(cards), "28일 강도 예측 최저", f"{pred.min():.1f}", "MPa",
                            "Predicted 28-day · 조기강도·분말도·C₃S 회귀(추정)",
                            f"결과 미도래 {len(pred)}로트" + (f" · 사내기준 미달 예측 {low}로트" if low else ""), "warn" if low else "ok"))
fc = reg.get("clk_fcao")
if fc is not None:
    worst = None
    for ln in store.item_lines("clk_fcao", reg) or [None]:
        sr = store.series("clk_fcao", reg, None, line=ln)
        if len(sr) and (worst is None or sr.iloc[-1] > worst[1]):
            worst = (ln, float(sr.iloc[-1]), sr.index[-1])
    if worst:
        lim = fc.limits_for(None)
        cards.append(K.kpi_card(len(cards), "클링커 f-CaO 최신 최고", f"{worst[1]:.2f}", "%",
                                f"Free lime · {worst[2]:%m/%d %H:%M}" + (f" · 사내 상한 {lim.usl:g}" if lim.usl is not None else ""),
                                worst[0] or "전체", "warn" if lim.usl is not None and worst[1] > lim.usl else "ok"))
cnt7 = {k: sum(e.severity == k for e in recent) for k in ("위험", "경고", "주의")}
cards.append(K.kpi_card(len(cards), "최근 7일 알림", f"{sum(cnt7.values())}", "건", "Alerts · 🚨 알림 센터에서 전체 보기",
                        f"위험 {cnt7['위험']} · 경고 {cnt7['경고']} · 주의 {cnt7['주의']}",
                        "bad" if cnt7["위험"] else "warn" if cnt7["경고"] else "ok"))
K.grid(cards)

# ── 공정별 상태(카드) ───────────────────────────────────────────────────
K.section("공정별 상태", "원료 → 소성 → 클링커 → 분쇄 → 제품")
STAGE_EN = {"원료": "Raw meal", "소성(킬른)": "Kiln", "클링커": "Clinker", "시멘트(분쇄)": "Cement mill", "제품 물성": "Product"}
DOT = {"정상": "var(--q-ok)", "주의": "var(--q-warn)", "경고": "var(--q-warn)", "위험": "var(--q-bad)"}
stage_cards = []
for i, stage in enumerate([s for s in STAGES if s != "시험 조건"]):
    sub = status[status["stage"] == stage] if len(status) else status
    worst = max(sub["status"], key=lambda s: SEVERITY_ORDER[s]) if len(sub) else "정상"
    rows = []
    for _key, grp in sub.groupby("item_key", sort=False):
        w = max(grp["status"], key=lambda s: SEVERITY_ORDER[s])
        nd, unit = int(grp["decimals"].iloc[0]), grp["unit"].iloc[0]
        has_tag = len(grp) > 1 or grp["product"].notna().any() or ("line" in grp and grp["line"].notna().any())
        if has_tag:
            def _tag(r):
                return " ".join(str(x) for x in (r.get("product"), r.get("line")) if isinstance(x, str) and x) or "구분 없음"
            val = " · ".join(f"{K.esc(_tag(r))} <b>{K.esc(fmt(r['last_value'], nd))}</b>" for _, r in grp.iterrows()) + f" {K.esc(unit)}"
        else:
            val = f"<b>{K.esc(fmt(grp['last_value'].iloc[0], nd, unit))}</b>"
        name = reg[_key].name if _key in reg else grp["item_name"].iloc[0]
        rows.append(f'<div><i style="background:{DOT[w]}"></i><span>{K.esc(name)} {val}</span></div>')
    well = (f'<div style="display:flex;gap:10px;align-items:center;margin-bottom:6px">{K.status_icon(worst)}<b style="font-size:17px">{worst}</b></div>'
            f'<div class="items">{"".join(rows) or "<div>핵심 항목 데이터 없음</div>"}</div>')
    last = sub["last_time"].max() if len(sub) else None
    stage_cards.append(K.card(f"{i + 1:02d}", K.esc(stage), f"{STAGE_EN.get(stage, '')}" + (f" · 최근 {last:%m/%d %H:%M}" if last is not None else ""), well, i))
K.grid(stage_cards, "stage")

# ── 알림 요약 + 조치 필요 알림 ────────────────────────────────────────────
left, right = st.columns([1, 2])
with left.container(border=True):
    cnt14 = {k: sum(e.severity == k for e in recent_events(ctx, days=14)) for k in ("위험", "경고", "주의")}
    st.html(K.sev_summary(cnt14))
with right.container(border=True):
    st.html(f'<div class="qk"><h3 class="qk-h3">조치가 필요한 알림 <span class="note">최근 14일 위험·경고 {len(act)}건 중 최근 7건</span></h3></div>')
    if not act:
        K.empty("최근 14일 위험·경고 알림이 없어요.")
    for n, e in enumerate(act[:7]):
        with st.container(key=f"qms_li_{n}"):
            a, b = st.columns([6, 1], vertical_alignment="center")
            prod = f"[{e.product}] " if e.product else ""
            a.html(f'<div class="qk li-t">{K.sev_pill(e.severity)} <b>{K.esc(prod + e.item_name)}</b>'
                   f'<small>{K.esc(e.rule_desc)} · {e.start:%m/%d %H:%M} ~ {e.end:%m/%d %H:%M} · '
                   f'{"최대" if e.direction == "high" else "최소"} {K.esc(fmt(e.worst_value, e.decimals, e.unit))}</small></div>')
            if b.button("진단 ›", key=f"dx_{e.event_id}", help="원인 진단·솔루션 보기", width="stretch"):
                open_diagnosis(e.event_id)

# ── 압축강도 추이 ──────────────────────────────────────────────────────
K.section("압축강도 추이", "실선 = 실측 · 점선 = 예측(재령 미도래, 추정) · 음영 = 경고/위험 구간")
with st.container(border=True):
    r1, r2, r3 = st.columns(3)
    ages = {"1일": "phy_s1", "3일": "phy_s3", "7일": "phy_s7", "28일": "phy_s28"}
    age = r1.segmented_control("재령", list(ages), default="28일", key="ov_age") or "28일"
    prod = r2.segmented_control("품종", ["1종", "3종"], default="1종", key="ov_prod") or "1종"
    dsel = r3.segmented_control("기간", ["30일", "90일", "180일", "1년"], default="90일", key="ov_days") or "90일"
    days = {"30일": 30, "90일": 90, "180일": 180, "1년": 365}[dsel]
    fig = trend_figure(ctx, ages[age], prod, start=end - pd.Timedelta(days=days), height=340)
    if fig:
        st.plotly_chart(fig, key="ov_strength")
    else:
        K.empty(f"{prod} {age} 강도 자료가 없어요.")

# ── 핵심 공정 지표 ─────────────────────────────────────────────────────
K.section("핵심 공정 지표", "최근 14일 · 8시간 평균")
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
    K.empty("최근 14일 공정 데이터가 없어요.")
for i in range(0, len(figs), 2):                     # 한 줄에 2개씩 크게
    row = st.columns(2)
    for col, (k, fig) in zip(row, figs[i:i + 2]):
        with col.container(border=True):
            st.plotly_chart(fig, key=k)
