"""시멘트 6가크롬: 크롬 투입 → 클링커·시멘트 Cr⁶⁺ 예측 → 환원제 투입량 → 실측 보정 → 저감 솔루션(+AI)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from qms import chromium as crm
from qms.ai_context import chromium_context
from qms.ui import (
    colors,
    get_ctx,
    sidebar,
    single_bar_figure,
    tornado_figure,
    trend_figure,
)
from qms.ui_ai import ai_panel

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store

st.title("☢️ 시멘트 6가크롬(Cr⁶⁺) 관리")
st.caption("원·부원료·연료·내화물의 **총 크롬 물질수지** × **킬른 전환율**로 클링커·시멘트의 수용성 6가크롬을 예측하고, "
           "환원제 필요 투입량과 저감 대책을 제시합니다. 기준: " + crm.LIMIT_KR_TEXT + " · " + crm.LIMIT_EU_TEXT +
           " (두 기준은 시험법이 달라 직접 비교 불가).")

# 현황(모니터링)
period = store.period()
if period:
    s = store.series("phy_crvi", reg, None)
    if len(s):
        recent = s[s.index >= period[1] - pd.Timedelta(days=30)]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("최근 로트 Cr⁶⁺", f"{s.iloc[-1]:.1f} mg/kg", help=f"{s.index[-1]:%Y-%m-%d}", border=True)
        m2.metric("최근 30일 평균", f"{recent.mean():.1f} mg/kg", border=True)
        m3.metric("최근 30일 최대", f"{recent.max():.1f} mg/kg",
                  delta=("🔴 자율기준 20 초과" if recent.max() > crm.LIMIT_KR else "🟢 20 이하"), delta_color="off",
                  delta_arrow="off", border=True)
        m4.metric("18 mg/kg 초과 로트(30일)", f"{int((recent > 18).sum())}건", border=True)
        with st.expander("시멘트·클링커 6가크롬 추이", expanded=bool(recent.max() > 18)):
            f1 = trend_figure(ctx, "phy_crvi", None, start=period[1] - pd.Timedelta(days=60), height=280,
                              title="시멘트 수용성 Cr⁶⁺ — 전 품종 로트 (mg/kg)")
            f2 = trend_figure(ctx, "clk_crvi", None, start=period[1] - pd.Timedelta(days=60), height=280,
                              title="클링커 수용성 Cr⁶⁺ (mg/kg)")
            a, b = st.columns(2)
            if f1:
                a.plotly_chart(f1, key="cr_tr1")
            if f2:
                b.plotly_chart(f2, key="cr_tr2")

DEF = crm.CrParams()
if "cr_conv_pending" in st.session_state:          # ③ 보정값 적용(다음 실행에서 위젯 값 갱신)
    st.session_state["cr_conv"] = st.session_state.pop("cr_conv_pending")
link = st.session_state.get("rawmix_last")
if "cr_kiln" not in st.session_state:
    st.session_state["cr_kiln"] = crm.default_kiln_inputs(link["table"], link["mats"]) if link else crm.default_kiln_inputs()
if "cr_mill" not in st.session_state:
    st.session_state["cr_mill"] = crm.default_mill_inputs()

tab1, tab2, tab3, tab4 = st.tabs(["① 크롬 투입 데이터", "② 6가크롬 예측·환원제", "③ 전환율 보정(실측)", "④ 저감 솔루션·AI"])
P = crm.CrParams()

with tab1:
    st.markdown("**킬른 투입물(클링커 1 t 기준)** — 투입량은 건조 kg/t-클링커, 총Cr는 건조 mg/kg. 잔류율 = 클링커로 이행되는 비율.")
    c1, c2 = st.columns([1, 3])
    if c1.button("🧪 배합 계산 결과 불러오기", disabled=link is None,
                 help="원료 배합 화면의 투입량·원료 Cr를 가져옵니다(연료 행은 기본값으로 다시 채움)."):
        st.session_state["cr_kiln"] = crm.default_kiln_inputs(link["table"], link["mats"])
        st.session_state.pop("cr_kiln_editor", None)
        st.rerun()
    c2.caption("원료 배합 화면을 먼저 계산하면 원료별 투입량이 자동 연동됩니다." if link is None else
               "원료 배합 화면의 최근 계산 결과를 사용할 수 있습니다.")
    kiln_in = st.data_editor(st.session_state["cr_kiln"], key="cr_kiln_editor", num_rows="dynamic", hide_index=True,
                             width="stretch", column_config={
                                 "use": st.column_config.CheckboxColumn("사용", width="small"),
                                 "name": st.column_config.TextColumn("투입원", required=True),
                                 "group": st.column_config.SelectboxColumn("구분", options=crm.GROUPS, width="small"),
                                 "amount": st.column_config.NumberColumn("투입량 kg/t-clk", format="%.1f", min_value=0.0),
                                 "cr": st.column_config.NumberColumn("총Cr mg/kg", format="%.1f", min_value=0.0),
                                 "retention": st.column_config.NumberColumn("잔류율 %", format="%.0f", min_value=0.0,
                                                                            max_value=100.0),
                                 "note": st.column_config.TextColumn("비고·출처", width="large")})
    st.markdown("**내화물·분쇄매체**")
    r1, r2, r3, r4, r5 = st.columns(5)
    P.refr_wear = r1.number_input("내화물 마모(kg/t-clk)", value=DEF.refr_wear, step=0.05, format="%.2f", key="cr_refr_wear",
                                  help="현대식 킬른 0.2 미만(문헌), 정기보수 시 실측 원단위로 교체")
    P.refr_cr2o3 = r2.number_input("벽돌 Cr₂O₃(%)", value=DEF.refr_cr2o3, step=1.0, key="cr_refr_cr2o3",
                                   help="마그네시아-크롬 벽돌 사양서 확인(예시 10%). 크롬프리 벽돌이면 0")
    P.media_wear = r3.number_input("분쇄매체 마모(g/t)", value=DEF.media_wear, step=5.0, key="cr_media_wear")
    P.media_cr = r4.number_input("매체 Cr(%)", value=DEF.media_cr, step=1.0, key="cr_media_cr",
                                 help="고크롬 주철 12~30%, 단조강 약 1%(예시)")
    P.media_conv = r5.number_input("밀 내 산화율(%)", value=DEF.media_conv, step=1.0, key="cr_media_conv", help="추정값")
    st.markdown("**시멘트밀 혼합재** — 비율은 시멘트 중 %, Cr⁶⁺는 혼합재 자체의 수용성 6가크롬(실측 권장)")
    mill_in = st.data_editor(st.session_state["cr_mill"], key="cr_mill_editor", num_rows="dynamic", hide_index=True,
                             width="stretch", column_config={
                                 "use": st.column_config.CheckboxColumn("사용", width="small"),
                                 "name": st.column_config.TextColumn("혼합재", required=True),
                                 "pct": st.column_config.NumberColumn("비율 %", format="%.1f", min_value=0.0, max_value=40.0),
                                 "cr": st.column_config.NumberColumn("총Cr mg/kg", format="%.1f", min_value=0.0),
                                 "crvi": st.column_config.NumberColumn("Cr⁶⁺ mg/kg", format="%.2f", min_value=0.0),
                                 "note": st.column_config.TextColumn("비고·출처", width="large")})
    st.caption("원료·연료 크롬 함량 기본값은 문헌 범위의 **예시(추정)** 입니다(석회석 약 14, 셰일 20~120, 석탄 10~40, "
               "석탄재 약 190 mg/kg). 입고 성적서·자체 XRF/ICP 분석값으로 교체하세요.")

with tab2:
    st.markdown("**킬른 전환율과 환원제 조건**")
    p1, p2, p3, p4 = st.columns(4)
    P.conv_kiln = p1.number_input("킬른 전환율 Cr⁶⁺/총Cr(%)", value=DEF.conv_kiln, step=0.5, format="%.2f", key="cr_conv",
                                  help="문헌 약 8~20%(Costeri 2016). ③ 탭 실측 보정값 사용 권장")
    P.reducer = p2.selectbox("환원제", list(crm.REDUCERS), format_func=lambda k: crm.REDUCERS[k]["label"], key="cr_reducer")
    if st.session_state.get("cr_reducer_prev") != P.reducer:      # 환원제를 바꾸면 해당 제품 기본값으로 채움
        r = crm.REDUCERS[P.reducer]
        st.session_state.update(cr_purity=r["purity"], cr_excess=r["excess"], cr_loss=r["loss_month"], cr_price=r["price"])
        st.session_state["cr_reducer_prev"] = P.reducer
    P.dose = p3.number_input("현재 투입량(kg/t-시멘트)", value=DEF.dose, step=0.05, format="%.3f", key="cr_dose")
    P.target = p4.number_input("사내 목표(mg/kg)", value=DEF.target, step=1.0, key="cr_target",
                               help="자율기준 20 대비 여유를 둔 관리 목표")
    q1, q2, q3, q4, q5 = st.columns(5)
    P.purity = q1.number_input("순도(%)", step=1.0, key="cr_purity")
    P.excess = q2.number_input("현장 과잉계수(배)", step=0.5, key="cr_excess",
                               help="화학양론 대비 실제 필요 배수(경험칙: FeSO₄ 약 10배, SnSO₄ 약 2~4배) — 실측 보정")
    P.loss_month = q3.number_input("월 열화율(%)", step=1.0, key="cr_loss", help="저장 중 환원력 감소(추정)")
    P.months = q4.number_input("저장 기간(개월)", value=DEF.months, step=0.5, key="cr_months")
    P.price = q5.number_input("단가(원/kg)", step=10.0, key="cr_price", help="예시 단가")
    t1, t2 = st.columns([1, 3])
    P.after_mill = t1.toggle("밀 출구 이후 투입", value=DEF.after_mill, key="cr_after", help="저온부 투입 시 FeSO₄ 열화 없음(가정)")
    P.mill_temp = t2.slider("투입 지점 온도(℃)", 40, 130, int(DEF.mill_temp), disabled=P.after_mill, key="cr_mill_temp",
                            help="FeSO₄: 60 ℃ 이하 열화 없음 → 120 ℃에서 효과 60%로 가정(추정)")

    bal = crm.cr_balance(kiln_in, mill_in, P)
    st.subheader("예측 결과")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("클링커 총 Cr", f"{bal.total_clk:.1f} mg/kg", border=True)
    k2.metric("클링커 Cr⁶⁺", f"{bal.crvi_clk:.2f} mg/kg", delta=f"전환율 {P.conv_kiln:.1f}%", delta_color="off",
              delta_arrow="off", border=True)
    k3.metric("시멘트 Cr⁶⁺(환원 전)", f"{bal.crvi_cement0:.2f} mg/kg", delta=f"클링커 비율 {bal.clinker_fraction * 100:.0f}%",
              delta_color="off", delta_arrow="off", border=True)
    judge = ("🔴 자율기준 20 초과" if bal.crvi_cement > crm.LIMIT_KR else "🟠 사내 목표 초과" if bal.crvi_cement > P.target
             else "🟢 사내 목표 이내")
    k4.metric("시멘트 Cr⁶⁺(현재 환원 후)", f"{bal.crvi_cement:.2f} mg/kg", delta=judge, delta_color="off", delta_arrow="off",
              border=True)
    st.markdown("**환원제 필요 투입량** (환원 전 Cr⁶⁺ 기준, 현장 과잉계수·저장 열화 반영 — 추정)")
    rows = []
    for key in crm.REDUCERS:
        pp = P.with_reducer(key) if key != P.reducer else P
        for lab, tgt in ((f"사내 목표 {P.target:g}", P.target), ("국내 자율기준 20", crm.LIMIT_KR), ("EU 2(참고)", crm.LIMIT_EU)):
            d = crm.required_dose(bal.crvi_cement0, tgt, pp)
            rows.append({"환원제": crm.REDUCERS[key]["label"], "목표": lab, "투입량(kg/t)": d, "투입률(%)": d / 10,
                         "원가(원/t-시멘트)": d * pp.price, "잔존율(%)": crm.reducer_retention(pp) * 100,
                         "화학양론(g/g-Cr⁶⁺)": crm.stoich(key)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "투입량(kg/t)": st.column_config.NumberColumn(format="%.3f"), "투입률(%)": st.column_config.NumberColumn(format="%.4f"),
        "원가(원/t-시멘트)": st.column_config.NumberColumn(format="%,.0f"), "잔존율(%)": st.column_config.NumberColumn(format="%.0f"),
        "화학양론(g/g-Cr⁶⁺)": st.column_config.NumberColumn(format="%.2f")})
    st.caption("화학양론: Cr⁶⁺ + 3Fe²⁺ → Cr³⁺ + 3Fe³⁺ (FeSO₄·7H₂O 16.04, FeSO₄·H₂O 9.80 g/g), 2Cr⁶⁺ + 3Sn²⁺ → 2Cr³⁺ + 3Sn⁴⁺ "
               "(SnSO₄ 6.20 g/g). 단가는 예시값, 투입량은 실기 시험으로 확정하세요.")
    a, b = st.columns(2)
    with a:
        top = bal.contrib[bal.contrib["기여(mg/kg)"] > 0].head(8)
        st.plotly_chart(single_bar_figure(top["투입원"].tolist(), top["기여(mg/kg)"].tolist(), "mg/kg", height=330,
                                          title="시멘트 Cr⁶⁺(환원 전) 기여도 — 파레토", fmt_str="{:.2f}"), key="cr_pareto")
        st.caption("누적 비율: " + " → ".join(f"{r['투입원']} {r['누적(%)']:.0f}%" for _, r in top.head(4).iterrows()))
    with b:
        tor = crm.tornado(kiln_in, mill_in, P)
        st.markdown("**민감도(입력 ±30% 시 시멘트 Cr⁶⁺, 현재 환원제 투입 후)**")
        st.plotly_chart(tornado_figure(tor, bal.crvi_cement, "mg/kg", height=330), key="cr_tornado")
    st.download_button("⬇️ 6가크롬 평가표(엑셀)", crm.cr_workbook(bal, tor, kiln_in, mill_in), file_name="6가크롬_평가표.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    with st.expander("투입원별 클링커 총 Cr 기여 상세"):
        kt = bal.kiln[["name", "group", "amount", "cr", "retention", "contribution", "share"]].rename(columns={
            "name": "투입원", "group": "구분", "amount": "투입량(kg/t-clk)", "cr": "총Cr(mg/kg)", "retention": "잔류율(%)",
            "contribution": "클링커 기여(mg/kg)", "share": "비율(%)"}).sort_values("클링커 기여(mg/kg)", ascending=False)
        st.dataframe(kt, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.2f")
                                                         for c in kt.columns[2:]})

with tab3:
    st.markdown("**클링커 총 Cr·수용성 Cr⁶⁺ 실측 짝으로 킬른 전환율을 보정**합니다. 데이터는 '클링커 일일 시료(XRD·크롬)' "
                "테이블(LIMS·업로드)에서 가져오며, 같은 날 킬른 O₂·클링커 Na₂Oeq를 자동으로 붙입니다. 아래 표에 직접 추가할 수도 있습니다.")
    pairs = crm.pairs_from_store(store)
    if len(pairs) == 0:
        pairs = pd.DataFrame([{"date": pd.Timestamp("2026-01-01"), "total_cr": 60.0, "crvi": 7.0, "o2": 3.0,
                               "na2oeq": 0.7, "sd": 90.0}])
        st.info("저장된 실측 짝이 없어 예시 1행을 표시합니다. 실측값으로 바꾸거나 LIMS·업로드로 데이터를 넣으세요.")
    pairs_ed = st.data_editor(pairs, key="cr_pairs_editor", num_rows="dynamic", hide_index=True, height=260, column_config={
        "date": st.column_config.DateColumn("일자"), "total_cr": st.column_config.NumberColumn("총Cr mg/kg", format="%.1f"),
        "crvi": st.column_config.NumberColumn("Cr⁶⁺ mg/kg", format="%.2f"),
        "o2": st.column_config.NumberColumn("킬른 O₂ %", format="%.2f"),
        "na2oeq": st.column_config.NumberColumn("Na₂Oeq %", format="%.2f"),
        "sd": st.column_config.NumberColumn("황산화도 %", format="%.0f", help="100·SO₃/(1.292·Na₂O + 0.850·K₂O)")})
    cal = crm.calibrate_conversion(pairs_ed)
    if cal is None:
        st.warning("유효한 실측 짝이 없습니다.")
    else:
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("전환율 중앙값", f"{cal.median:.2f} %", delta=f"사분위 {cal.q1:.1f}~{cal.q3:.1f}%", delta_color="off",
                  delta_arrow="off", border=True)
        e2.metric("실측 짝", f"{cal.n}건", border=True)
        latest = pairs_ed.dropna(subset=["o2", "na2oeq"]).tail(7)
        pred_now = cal.predict(float(latest["o2"].mean()), float(latest["na2oeq"].mean())) if len(latest) and cal.coef else cal.median
        e3.metric("최근 조건 예측 전환율", f"{pred_now:.2f} %", help="최근 7건 평균 O₂·Na₂Oeq를 회귀식에 대입(회귀 미성립 시 중앙값)",
                  border=True)
        e4.metric("회귀 R²", "-" if cal.r2 is None else f"{cal.r2:.2f}", border=True,
                  help="전환율(%) ~ O₂ + Na₂Oeq. 0.3 미만이면 운전 조건으로 설명되는 부분이 작음")
        if cal.coef:
            st.caption(f"회귀식: 전환율(%) = {cal.coef['intercept']:.2f} {cal.coef['o2']:+.2f}×O₂ {cal.coef['na2oeq']:+.2f}×Na₂Oeq "
                       f"(RMSE {cal.rmse:.2f}%p) — 산소·알칼리↑ 시 전환율↑ 경향(문헌)과 부호가 맞는지 확인하세요.")
            c = colors()
            d = pairs_ed.dropna(subset=["o2", "total_cr", "crvi"])
            d = d[d["total_cr"] > 0]
            fig = go.Figure(go.Scatter(x=d["o2"], y=d["crvi"] / d["total_cr"] * 100, mode="markers",
                                       marker=dict(color=c["series"], size=8), hovertemplate="O₂ %{x:.2f}% · 전환율 %{y:.1f}%<extra></extra>"))
            fig.update_layout(height=280, xaxis_title="킬른 O₂ (%)", yaxis_title="전환율 Cr⁶⁺/총Cr (%)",
                              margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
            st.plotly_chart(fig, key="cr_cal_scatter")
        if st.button(f"보정 전환율 {pred_now:.2f}% 를 ② 계산에 적용", type="primary"):
            st.session_state["cr_conv_pending"] = round(float(pred_now), 2)
            st.rerun()
    st.subheader("환원제 실효 성능(로트별)")
    eff = crm.reducer_effect_series(store)
    if len(eff):
        c = colors()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eff["timestamp"], y=eff["예측 환원 전"], mode="lines+markers", name="예측 환원 전(클링커 실측 기반)",
                                 line=dict(color=c["pred"], dash="dash", width=1.5), marker=dict(size=5)))
        fig.add_trace(go.Scatter(x=eff["timestamp"], y=eff["제품 실측"], mode="lines+markers", name="제품 실측(환원 후)",
                                 line=dict(color=c["series"], width=2), marker=dict(size=6)))
        fig.add_hline(y=crm.LIMIT_KR, line=dict(color=c["ks"], width=1.5), annotation_text="자율기준 20",
                      annotation_position="top left", annotation_font=dict(size=11, color=c["muted"]))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified", yaxis_title="mg/kg",
                          legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        st.plotly_chart(fig, key="cr_eff")
        rem = eff["실효 제거량"]
        st.caption(f"실효 제거량(예측 환원 전 − 제품 실측) 평균 {rem.mean():.2f} mg/kg(표준편차 {rem.std():.2f}). "
                   + (f"현재 투입량 {P.dose:.3f} kg/t 기준 1 kg/t당 실효 제거 {rem.mean() / P.dose:.1f} mg/kg → "
                      f"② 계산의 이론 제거능력 {crm.capacity_per_kg(P):.1f} mg/kg 과 비교해 과잉계수를 보정하세요."
                      if P.dose > 0 else "② 탭에 현재 투입량을 넣으면 1 kg/t당 실효 제거능력을 계산합니다."))
    else:
        st.info("제품 Cr⁶⁺ 실측과 클링커 Cr⁶⁺ 실측이 함께 있어야 계산할 수 있습니다.")

with tab4:
    bal = crm.cr_balance(kiln_in, mill_in, P)
    tor = crm.tornado(kiln_in, mill_in, P)
    st.markdown(crm.cr_solution_markdown(bal))
    with st.expander("저감 조치 라이브러리(표)"):
        st.dataframe(pd.DataFrame([{"구분": a.group, "단기/근본": a.horizon, "조치": a.title, "원리": a.mechanism, "효과(추정)": a.effect,
                                    "부작용": a.side_effects, "실행": a.how, "확인": a.verify, "근거": a.basis}
                                   for a in crm.CR_ACTIONS]), hide_index=True)
    recent_meas = None
    if period is not None:
        s = store.series("phy_crvi", reg, None)
        if len(s):
            r30 = s[s.index >= period[1] - pd.Timedelta(days=30)]
            recent_meas = {"product_crvi_last_mg_kg": round(float(s.iloc[-1]), 2), "product_crvi_30d_mean": round(float(r30.mean()), 2),
                           "product_crvi_30d_max": round(float(r30.max()), 2), "lots_over_18_30d": int((r30 > 18).sum())}
    cal_ctx = crm.calibrate_conversion(crm.pairs_from_store(store))
    ai_panel("chromium", chromium_context(bal, tor, cal_ctx, recent_meas), key="ai_chromium")
    st.caption("근거: Costeri(2016) 클링커 Cr의 약 8~20% 6가 전환 · Hills & Johansen(2007, PCA 문헌 리뷰) 산소·알칼리 영향 · "
               "IJERPH(2022) 알칼리가 수용성 Cr⁶⁺를 높임 · Shimosaka(냉각대 2차 연료로 수용성 Cr⁶⁺ 감소). 상세 출처는 README.")
