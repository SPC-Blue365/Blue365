"""원료 배합·클링커 설계: 배합 계산 → 클링커 예측·검증 → 재령별 강도·응결 예측 → 제어 솔루션(+AI)."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from qms import rawmix as rmx
from qms import strength as stg
from qms.ai_context import rawmix_context, strength_context
from qms.ui import (
    colors,
    get_ctx,
    get_design,
    sidebar,
    signed_bar_figure,
    single_bar_figure,
    strength_curve_figure,
)
from qms.ui_ai import ai_panel

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store
dm = get_design()

st.title("🧪 원료 배합·클링커 설계")
st.caption("① 원료 비율을 목표 LSF·SM·IM·C₃S에 맞게 자동 조정 → ② 소성 후 클링커 계수·광물(XRD) 예측 → "
           "③ 클링커 광물·분쇄 조건으로 1·3·7·28일 강도와 응결 예측 → ④ 목표 강도·응결을 맞추는 조치(규칙 기반 + AI). "
           "모든 예측은 **추정치**이며 공장 데이터가 쌓일수록 자동으로 보정됩니다.")

if "rm_mats" not in st.session_state:
    st.session_state["rm_mats"] = rmx.default_materials()
if "rm_coal_default" not in st.session_state:
    est = rmx.estimate_coal_rate(store)
    st.session_state["rm_coal_default"] = round(est, 1) if est and 60 < est < 200 else 115.0

tab1, tab2, tab3, tab4 = st.tabs(["① 원료·배합 계산", "② 클링커 예측·검증", "③ 재령별 강도·응결 예측", "④ 제어 솔루션·AI"])

# ── ① 원료·배합 계산 ──────────────────────────────────────────────────
with tab1:
    st.markdown("**원료 성분표** (건조 기준 %) — 구분별로 후보 원료를 **여러 개(최대 5종)** 등록할 수 있습니다. "
                "'사용'을 켠 원료만 배합에 들어갑니다. 하한·상한은 배합비(%) 제약, '고정'에 값을 넣으면 그 비율로 고정합니다.")
    cfg_cols = {
        "use": st.column_config.CheckboxColumn("사용", width="small"),
        "name": st.column_config.TextColumn("원료", width="medium", required=True),
        "category": st.column_config.SelectboxColumn("구분", options=rmx.CATEGORIES, width="small"),
        **{o: st.column_config.NumberColumn(rmx.OXIDE_LABELS[o], format="%.2f", min_value=0.0, max_value=100.0)
           for o in rmx.OXIDES},
        "LOI": st.column_config.NumberColumn("강열감량", format="%.2f", min_value=0.0, max_value=60.0),
        "H2O": st.column_config.NumberColumn("수분 %", format="%.1f", min_value=0.0, max_value=60.0),
        "Cr": st.column_config.NumberColumn("총Cr mg/kg", format="%.0f", min_value=0.0, help="6가크롬 물질수지에 사용"),
        "cost": st.column_config.NumberColumn("단가 원/t", format="%.0f", min_value=0.0, help="습윤 입고 기준(예시값)"),
        "min": st.column_config.NumberColumn("하한 %", format="%.1f", min_value=0.0, max_value=100.0),
        "max": st.column_config.NumberColumn("상한 %", format="%.1f", min_value=0.0, max_value=100.0),
        "fixed": st.column_config.NumberColumn("고정 %", format="%.2f", min_value=0.0, max_value=100.0),
    }
    mats = st.data_editor(st.session_state["rm_mats"], key="rm_mats_editor", num_rows="dynamic", hide_index=True,
                          column_config=cfg_cols, width="stretch")

    # 구분별 후보 원료 추가(실리카원·알루미나원·철질·기타 등 각 최대 5종, 수동 입력)
    counts = rmx.category_counts(mats)
    cnt_txt = " · ".join(f"{c} {counts.get(c, 0)}/{rmx.MAX_PER_CATEGORY}" for c in rmx.CATEGORIES)
    a1, a2, a3, a4 = st.columns([1.1, 1.1, 1.3, 1.8])
    add_cat = a1.selectbox("구분", rmx.CATEGORIES, index=1, key="rm_add_cat", label_visibility="collapsed")
    full = int(counts.get(add_cat, 0)) >= rmx.MAX_PER_CATEGORY
    if a2.button(f"➕ {add_cat} 후보 추가", disabled=full,
                 help=f"선택한 구분에 빈 후보 한 줄을 추가합니다(구분별 최대 {rmx.MAX_PER_CATEGORY}종). 성분을 적고 '사용'을 켜세요."):
        st.session_state["rm_mats"] = rmx.add_candidate(mats, add_cat)
        st.session_state.pop("rm_mats_editor", None)
        st.rerun()
    if a3.button("구분별 5칸 채우기", help="각 구분이 5종이 되도록 빈 후보 줄을 한꺼번에 추가합니다(기존 줄은 유지)."):
        st.session_state["rm_mats"] = rmx.fill_candidates(mats)
        st.session_state.pop("rm_mats_editor", None)
        st.rerun()
    a4.caption(f"구분별 등록 수: {cnt_txt}")
    if full:
        st.caption(f"'{add_cat}'은 이미 {rmx.MAX_PER_CATEGORY}종입니다. 더 넣으려면 표에서 직접 행을 추가하세요(권장 상한 초과).")
    for c in rmx.over_cap(mats):
        st.caption(f"⚠️ '{c}'이 권장 상한({rmx.MAX_PER_CATEGORY}종)을 넘었습니다 — 계산은 되지만 후보를 줄이는 것을 권장합니다.")

    u1, u2, u3 = st.columns([1.2, 1.6, 2])
    if u1.button("기본 예시로 초기화", help="예시 원료 5종(구분별 1종)으로 되돌립니다."):
        st.session_state["rm_mats"] = rmx.default_materials()
        st.session_state.pop("rm_mats_editor", None)
        st.rerun()
    up = u2.file_uploader("원료 성분표 불러오기(엑셀·CSV)", type=["xlsx", "csv"], key="rm_upload",
                          label_visibility="collapsed")
    if up is not None and st.session_state.get("rm_upload_id") != up.file_id:
        try:
            st.session_state["rm_mats"] = rmx.parse_materials(up.getvalue(), up.name)
            st.session_state["rm_upload_id"] = up.file_id
            st.session_state.pop("rm_mats_editor", None)
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - 업로드 오류 안내
            st.error(f"불러오기 실패: {exc}")
    u3.caption("성분·단가 기본값은 **예시(추정)** 입니다. 원료 입고 분석값(XRF)으로 바꿔 쓰세요. "
               "엑셀은 아래 '배합 설계서'의 '원료성분' 시트 형식을 그대로 쓰면 됩니다.")

    st.markdown("**목표 계수**")
    b1, b2, b3 = st.columns([1.3, 1.3, 1.4])
    basis = b1.radio("목표 기준", ["클링커 기준(석탄회 흡수 반영)", "생료(킬른 피드) 기준"], key="rm_basis",
                     help="클링커 기준: 석탄회가 흡수된 소성 후 클링커 조성으로 목표를 맞춥니다(권장).")
    mode = b2.radio("계산 방식", ["최소자승(목표 근접)", "원가 최소(허용편차 내)"], key="rm_mode",
                    help="원가 최소: LSF ±0.3, SM·IM ±0.02, C₃S ±0.5 안에서 원료비가 가장 낮은 배합")
    c3s_basis = b3.radio("C₃S 목표 기준", ["Bogue 계산값", "XRD 알라이트(보정식 환산)"], key="rm_c3s_basis",
                         help=f"XRD 보정식: {dm.xrd.source}")
    is_raw = basis.startswith("생료")
    tc = st.columns(4)
    defaults = {"LSF": (99.0 if is_raw else 95.0, True), "SM": (2.55 if is_raw else 2.50, True),
                "IM": (1.58 if is_raw else 1.60, True), "C3S": (64.0 if c3s_basis.startswith("XRD") else 57.0, False)}
    vals, en, wts = {}, {}, {}
    for col, k in zip(tc, rmx.TARGET_KEYS):
        dv, de = defaults[k]
        en[k] = col.checkbox(f"{rmx.TARGET_LABELS[k]} 맞추기", value=de, key=f"rm_en_{k}_{basis[:2]}")
        step = {"LSF": 0.5, "SM": 0.05, "IM": 0.05, "C3S": 0.5}[k]
        vals[k] = col.number_input(f"목표 {rmx.TARGET_LABELS[k]}", value=dv, step=step, format="%.2f",
                                   key=f"rm_t_{k}_{basis[:2]}_{c3s_basis[:2]}", disabled=not en[k])
        wts[k] = col.number_input("가중치", value=1.0, min_value=0.0, step=0.5, key=f"rm_w_{k}",
                                  help="목표끼리 충돌할 때 상대 중요도", disabled=not en[k])
    targets = rmx.MixTargets("raw" if is_raw else "clinker", vals, en, wts, "xrd" if c3s_basis.startswith("XRD") else "bogue")

    with st.expander("소성 조건(석탄회 흡수·휘발 성분) — 클링커 예측에 사용", expanded=False):
        k1, k2, k3, k4 = st.columns(4)
        coal = k1.number_input("석탄 원단위(kg/t-클링커)", value=float(st.session_state["rm_coal_default"]), step=1.0,
                               help="기본값: 최근 14일 DCS 석탄·원료 투입량으로 추정(가능한 경우)")
        ash = k2.number_input("석탄 회분(%)", value=14.0, step=0.5)
        absorb = k3.number_input("회분 흡수율(%)", value=100.0, step=1.0, help="바이패스·더스트 손실이 있으면 100 미만")
        coal_s = k4.number_input("석탄 황분(%)", value=1.0, step=0.1)
        k5, k6, k7, k8 = st.columns(4)
        so3_r = k5.number_input("SO₃ 잔류율(%)", value=60.0, step=5.0)
        k2o_r = k6.number_input("K₂O 잔류율(%)", value=85.0, step=5.0)
        na2o_r = k7.number_input("Na₂O 잔류율(%)", value=95.0, step=5.0)
        fcao_mode = k8.selectbox("f-CaO", ["소성성 모델 예측", "직접 입력"], help=dm.fcao.equation())
        k9, k10, k11, _ = st.columns(4)
        fcao_in = k9.number_input("f-CaO 입력값(%)", value=1.0, step=0.1, disabled=fcao_mode != "직접 입력")
        r90 = k10.number_input("생료 90μm 잔사(%)", value=13.0, step=0.5, help="f-CaO 예측 입력")
        bzt = k11.number_input("소성대 온도(℃)", value=1420.0, step=5.0, help="f-CaO 예측 입력")
        st.caption(f"f-CaO 모델: {dm.fcao.source} · {dm.fcao.equation()}"
                   + (f" · 학습 {dm.fcao.n}점, RMSE {dm.fcao.rmse:.2f}%" if dm.fcao.n else " (공장 데이터 부족 시 경험식)"))
    kp = rmx.KilnParams(coal, ash, absorb, coal_s, so3_r, k2o_r, na2o_r, fcao_in, r90, bzt)
    use_model = fcao_mode.startswith("소성성")

    res = None
    try:
        res = rmx.solve_mix(mats, targets, kp, mode="cost" if mode.startswith("원가") else "lsq",
                            fcao_model=dm.fcao if use_model else None, xrd_map=dm.xrd)
    except ValueError as exc:
        st.error(f"계산할 수 없습니다: {exc}")

    if res is not None:
        st.session_state["rawmix_last"] = {"table": res.table(), "mats": res.mats, "clinker": res.clinker}
        st.subheader("배합 결과")
        mc = st.columns(4)
        for col, k in zip(mc, rmx.TARGET_KEYS):
            v = res.achieved[k]
            lab = ("XRD 알라이트" if (k == "C3S" and targets.c3s_basis == "xrd") else rmx.TARGET_LABELS[k]) + \
                  (" (생료)" if (is_raw and k != "C3S") else " (클링커)")
            if k in res.deviation:
                d = res.deviation[k]
                ok = abs(d) <= rmx.TOL[k] + 1e-9
                col.metric(lab, f"{v:.{rmx.DEC[k]}f}", delta=f"{'✅' if ok else '⚠️'} 목표 {targets.values[k]:g} · 편차 {d:+.{rmx.DEC[k]}f}",
                           delta_color="off", delta_arrow="off", border=True)
            else:
                col.metric(lab, f"{v:.{rmx.DEC[k]}f}", delta="결과값(목표 미지정)", delta_color="off", delta_arrow="off",
                           border=True)
        if res.feasible:
            st.success(f"목표 달성 — {res.mode}. 원료비 약 {res.cost_per_t_clk:,.0f} 원/t-클링커(예시 단가 기준).", icon="✅")
        for msg in res.messages:
            st.warning(msg, icon="⚠️")
        left, right = st.columns([1.5, 1])
        with left:
            tbl = res.table()
            show_t = tbl.drop(columns=["하한(%)", "상한(%)"])
            st.dataframe(show_t, hide_index=True, column_config={
                c: st.column_config.NumberColumn(format="%.2f" if "%" in c else "%.1f") for c in show_t.columns[2:]})
            st.caption("습윤 배합비 = 정량공급기 설정용(수분 보정). 투입량 = 클링커 1 t 생산에 필요한 원료량.")
        with right:
            st.plotly_chart(single_bar_figure(tbl["원료"].tolist(), tbl["건조 배합비(%)"].tolist(), "%", height=260,
                                              title="건조 배합비(%)", fmt_str="{:.2f}"), key="rm_bar")
        with st.expander("생료·클링커 화학 조성 / 원료 민감도"):
            cl = res.clinker
            comp = pd.DataFrame({"성분": [rmx.OXIDE_LABELS[o] for o in rmx.OXIDES] + ["강열감량"],
                                 "생료(건조, %)": [cl["raw"][o] for o in rmx.OXIDES] + [cl["raw"]["LOI"]],
                                 "클링커 예측(%)": [cl["clinker"].get(o) for o in rmx.OXIDES] + [None]})
            e1, e2 = st.columns([1, 1.4])
            e1.dataframe(comp, hide_index=True, column_config={
                "생료(건조, %)": st.column_config.NumberColumn(format="%.2f"),
                "클링커 예측(%)": st.column_config.NumberColumn(format="%.2f")})
            sens = rmx.sensitivity(res.mats, res.x, kp)
            e2.markdown("**원료 1%p 증량 시(나머지 비례 감량) 클링커 계수 변화**")
            e2.dataframe(sens, hide_index=True, column_config={
                c: st.column_config.NumberColumn(format="%+.3f") for c in sens.columns[1:]})
            st.caption(f"생료/클링커 = {cl['kiln_factor']:.3f} t/t · 흡수 석탄회 a = {kp.a:.4f} kg/kg-클링커 · "
                       f"생료 LSF {cl['raw_lsf']:.1f} → 클링커 LSF {cl['LSF']:.1f} (석탄회 흡수로 낮아짐)")
        st.download_button("⬇️ 배합 설계서(엑셀)", rmx.design_workbook(mats, targets, kp, res), file_name="배합설계서.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

# ── ② 클링커 예측·검증 ───────────────────────────────────────────────
with tab2:
    if res is None:
        st.info("① 탭에서 배합 계산을 먼저 완료하세요.")
    else:
        cl = res.clinker
        st.markdown("**배합 → 소성 후 클링커 예측** (석탄회 흡수·휘발 성분 잔류율 반영, 추정)")
        mc = st.columns(6)
        mc[0].metric("LSF", f"{cl['LSF']:.1f}", border=True)
        mc[1].metric("SM", f"{cl['SM']:.2f}", border=True)
        mc[2].metric("IM", f"{cl['IM']:.2f}", border=True)
        mc[3].metric("C₃S(Bogue)", f"{cl['C3S']:.1f} %", border=True)
        mc[4].metric("액상량 1450℃", f"{cl['liquid']:.1f} %", border=True)
        mc[5].metric("f-CaO 예측", f"{cl['fcao']:.2f} %", help=cl["fcao_source"], border=True)
        clk = store.tables.get("clinker", pd.DataFrame())
        xrd = store.tables.get("xrd", pd.DataFrame())
        end = store.period()[1] if store.period() else None

        def recent_mean(df, col):
            if df is None or len(df) == 0 or col not in df or end is None:
                return np.nan
            return float(df.loc[df["timestamp"] >= end - pd.Timedelta(days=7), col].mean())

        rows = []
        for key, val, src in (("clk_lsf", cl["LSF"], clk), ("clk_sm", cl["SM"], clk), ("clk_im", cl["IM"], clk),
                              ("clk_c3s", cl["C3S"], clk), ("clk_c2s", cl["C2S"], clk), ("clk_c3a", cl["C3A"], clk),
                              ("clk_c4af", cl["C4AF"], clk), ("clk_liquid", cl["liquid"], clk),
                              ("clk_na2oeq", cl["na2oeq"], clk), ("clk_fcao", cl["fcao"], clk),
                              ("xrd_alite", cl["xrd"]["alite"], xrd), ("xrd_belite", cl["xrd"]["belite"], xrd),
                              ("xrd_c3a", cl["xrd"]["c3a"], xrd), ("xrd_c4af", cl["xrd"]["c4af"], xrd),
                              ("xrd_periclase", cl["xrd"]["periclase"], xrd)):
            it = reg[key]
            lim = it.limits_for(None)
            judge = "-"
            if lim.lsl is not None or lim.usl is not None:
                judge = "🟢 기준 이내" if ((lim.lsl is None or val >= lim.lsl) and (lim.usl is None or val <= lim.usl)) \
                    else "🟠 사내기준 이탈"
            rng = (f"{lim.lsl:g} ~ {lim.usl:g}" if lim.lsl is not None and lim.usl is not None else
                   f"≥ {lim.lsl:g}" if lim.lsl is not None else f"≤ {lim.usl:g}" if lim.usl is not None else "-")
            rows.append({"항목": it.name, "예측": val, "단위": it.unit, "사내 기준": rng, "최근 7일 실측 평균": recent_mean(src, key),
                         "판정": judge})
        st.dataframe(pd.DataFrame(rows), hide_index=True, height=36 * (len(rows) + 1) + 3, column_config={
            "예측": st.column_config.NumberColumn(format="%.2f"),
            "최근 7일 실측 평균": st.column_config.NumberColumn(format="%.2f")})
        st.caption(f"XRD 광물 예측: {dm.xrd.source}. Bogue 계산값은 평형 가정이라 XRD 실측과 차이가 있으며(통상 알라이트 과소), "
                   "공장 XRD·XRF 짝 데이터로 보정식을 학습합니다.")
        with st.expander("예측식·보정식 상세"):
            st.markdown(f"- **f-CaO(소성성) 모델**: {dm.fcao.equation()} — {dm.fcao.source}"
                        + (f", 학습 {dm.fcao.n}점, R² {dm.fcao.r2:.2f}, LOO RMSE {dm.fcao.rmse:.2f}%" if dm.fcao.n else ""))
            if dm.xrd.rmse:
                xt = pd.DataFrame([{"광물": ph, "절편 b₀": b0, "기울기 b₁": b1, "잔차 RMSE": dm.xrd.rmse.get(ph)}
                                   for ph, (b0, b1) in dm.xrd.coef.items() if ph in dm.xrd.rmse])
                st.markdown("- **XRD 보정식** (XRD 실측 = b₀ + b₁ × Bogue 계산값, 같은 날 짝)")
                st.dataframe(xt, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.3f")
                                                                 for c in ("절편 b₀", "기울기 b₁", "잔차 RMSE")})
        st.subheader("실적 검증: 생료 실측 → 클링커 예측 vs 클링커 실측")
        chk, summ = rmx.conversion_check(store, kp)
        if len(chk) == 0:
            st.info("생료·클링커 실측 데이터가 있어야 검증할 수 있습니다.")
        else:
            recent = chk[chk["timestamp"] >= chk["timestamp"].max() - pd.Timedelta(days=14)]
            c = colors()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=recent["timestamp"], y=recent["LSF 실측"], mode="lines", name="클링커 LSF 실측",
                                     line=dict(color=c["series"], width=2)))
            fig.add_trace(go.Scatter(x=recent["timestamp"], y=recent["LSF 예측"], mode="lines", name="생료 기반 예측",
                                     line=dict(color=c["pred"], width=1.5, dash="dash")))
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                              legend=dict(orientation="h", y=1.1, x=1, xanchor="right"), yaxis_title="LSF")
            st.plotly_chart(fig, key="rm_conv")
            v1, v2, v3, v4 = st.columns(4)
            for col, k in zip((v1, v2, v3), ("LSF", "SM", "IM")):
                col.metric(f"{k} 예측 오차", f"{summ[k]['rmse']:.3f}", delta=f"편향 {summ[k]['bias']:+.3f}", delta_color="off",
                           delta_arrow="off", help=f"RMSE(전체 {summ[k]['n']}점). 편향 = 예측 − 실측 평균", border=True)
            ratio = summ["a_eff"] / summ["a_set"] * 100 if summ["a_set"] else np.nan
            v4.metric("석탄회 흡수(실적 추정)", f"{summ['a_eff']:.4f}", delta=f"설정 {summ['a_set']:.4f} 대비 {ratio:.0f}%",
                      delta_color="off", delta_arrow="off", border=True,
                      help="생료→클링커 산화물 변화로 역산한 클링커 1 kg당 흡수 석탄회(kg)")
            if np.isfinite(ratio) and abs(ratio - 100) > 5:
                st.info(f"실적 기준 석탄회 흡수량이 설정값의 {ratio:.0f}%입니다. 소성 조건의 '회분 흡수율'을 약 {absorb * ratio / 100:.0f}%로 "
                        "보정하면 예측 정확도가 좋아집니다(추정).", icon="💡")
        ai_panel("rawmix", rawmix_context(res, targets, kp), key="ai_rawmix", title="배합·클링커 설계 검토")

# ── ③ 재령별 강도·응결 예측 ──────────────────────────────────────────
with tab3:
    product = st.segmented_control("품종", ["1종", "3종"], default="1종", key="st_prod") or "1종"
    sm = dm.strength[product]
    src_opts = ["최근 생산 실적", "② 배합 설계 클링커(예측)", "평소 조건(학습 평균)"]
    source = st.radio("입력 기준", src_opts, horizontal=True, key="st_src",
                      help="배합 설계 기준: ②의 예측 클링커 광물 + 평소 분쇄 조건")
    latest, latest_ts = sm.latest_inputs()
    typical = sm.typical_inputs()
    if source.startswith("②") and res is not None:
        x = res.clinker["xrd"]
        base = dict(typical)
        base.update({"alite": x["alite"], "belite": x["belite"], "c3a": x["c3a"], "c4af": x["c4af"], "fcao": x["fcao"],
                     "na2oeq": res.clinker["na2oeq"]})
    elif source.startswith("최근"):
        base = latest
    else:
        base = typical
    if source.startswith("최근") and latest_ts is not None:
        st.caption(f"최근 로트 {latest_ts:%Y-%m-%d} 기준(클링커는 생산 1~2일 전 평균, 결측은 평소값).")
    st.markdown("**입력값** (수정하면 즉시 다시 예측)")
    inputs = {}
    rows = [stg.INPUT_KEYS[:6], stg.INPUT_KEYS[6:]]
    steps = {"alite": 0.5, "belite": 0.5, "c3a": 0.2, "c4af": 0.2, "fcao": 0.1, "na2oeq": 0.02, "blaine": 50.0,
             "so3": 0.05, "ls": 0.5, "mill_temp": 2.0}
    for keys in rows:
        cols = st.columns(len(keys))
        for col, k in zip(cols, keys):
            name, unit = stg.FEATURE_INFO[k]
            v0 = float(base.get(k, np.nan))
            inputs[k] = col.number_input(f"{name} ({unit})", value=round(v0, 3) if np.isfinite(v0) else 0.0,
                                         step=steps[k], format="%.2f" if k not in ("blaine", "mill_temp") else "%.0f",
                                         key=f"st_in_{product}_{source[:2]}_{k}_{round(v0, 3)}")
    pred = sm.predict(inputs)
    left, right = st.columns([1, 1.25])
    with left:
        st.plotly_chart(strength_curve_figure(pred, reg, product, height=330), key=f"st_curve_{product}")
    with right:
        show = pred[["항목", "예측", "하한(95%)", "상한(95%)", "KS", "사내", "판정"]].rename(
            columns={"하한(95%)": "하한", "상한(95%)": "상한"})
        st.dataframe(show, hide_index=True, column_config={
            "항목": st.column_config.TextColumn(width="small"),
            **{c: st.column_config.NumberColumn(format="%.1f", width="small") for c in ("예측", "하한", "상한")},
            "KS": st.column_config.TextColumn(width="small"), "사내": st.column_config.TextColumn(width="small")})
        st.caption("강도 MPa · 응결 분. 하한~상한 = 예측 ± 1.96 × LOO RMSE(약 95% 구간). KS = KS L 5201, "
                   "사내 = 사내 관리기준(⚙️에서 수정).")
    m28 = sm.models.get("phy_s28")
    if m28 is not None:
        contrib = m28.contributions(stg.features_from_inputs(inputs, sm.so3_opt))
        labels = [stg.FEATURE_INFO[k][0] for k in contrib]
        st.plotly_chart(signed_bar_figure(labels, list(contrib.values()), "MPa", height=320,
                                          title="28일 강도: 평소 조건(학습 평균) 대비 입력별 기여(MPa)"), key=f"st_contrib_{product}")
        st.caption("파랑 = 강도를 높이는 요인, 주황 = 낮추는 요인. 기여 = 계수 × (현재값 − 평소값).")
    with st.expander("예측 모델 상세(학습 로트·오차·계수)"):
        mt = pd.DataFrame([{"항목": m.label, "모델": m.source, "학습 로트": m.n, "시험조건 이탈 제외": m.n_excluded,
                            "λ": ("∞" if not np.isfinite(m.lam) else f"{m.lam:g}"), "LOO RMSE": m.rmse,
                            "R²": m.r2 if np.isfinite(m.lam) else None, "경험칙 고정 입력": ", ".join(m.fixed) or "-"}
                           for m in sm.models.values()])
        st.dataframe(mt, hide_index=True, column_config={"LOO RMSE": st.column_config.NumberColumn(format="%.2f"),
                                                         "R²": st.column_config.NumberColumn(format="%.2f")})
        tsel = st.selectbox("계수 보기", list(sm.models), format_func=lambda t: stg.TARGETS[t]["label"], key=f"st_coef_{product}")
        st.dataframe(sm.models[tsel].coef_table(), hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="%.4f") for c in ("학습 계수", "경험칙 계수", "변동폭당 영향")})
        st.caption("경험칙 계수에서 출발해 공장 데이터로 보정합니다(사전정보 리지 회귀). 데이터가 적은 품종·재령은 경험칙에 가깝게 유지되며, "
                   "이론과 부호가 반대로 학습된 계수는 경험칙 값으로 고정합니다(과적합·외삽 방지).")
        bt = stg.backtest(sm, "phy_s28")
        if len(bt):
            c = colors()
            fig = go.Figure(go.Scatter(x=bt["예측"], y=bt["실측"], mode="markers", marker=dict(color=c["series"], size=8),
                                       text=bt["timestamp"].dt.strftime("%Y-%m-%d"),
                                       hovertemplate="%{text}<br>예측 %{x:.1f} / 실측 %{y:.1f}<extra></extra>"))
            lo, hi = float(min(bt["예측"].min(), bt["실측"].min())) - 1, float(max(bt["예측"].max(), bt["실측"].max())) + 1
            fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", line=dict(color=c["cl"], dash="dash", width=1)))
            fig.update_layout(height=320, showlegend=False, xaxis_title="예측 28일(MPa)", yaxis_title="실측 28일(MPa)",
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, key=f"st_bt_{product}")

# ── ④ 제어 솔루션·AI ─────────────────────────────────────────────────
with tab4:
    st.markdown(f"**{product} — 목표 강도·응결을 맞추기 위한 조치** (③의 입력값 기준)")
    gbasis = st.radio("강도 목표 기준", ["사내 목표값(권장)", "사내 하한(최소 요구)"], horizontal=True, key=f"gbasis_{product}",
                      help="응결은 항상 사내 하한~상한 범위를 목표로 합니다. 아래 표에서 직접 수정할 수도 있습니다.")
    goals0 = stg.default_goals(reg, product, sm.models, "target" if gbasis.startswith("사내 목표") else "lsl")
    grows = [{"사용": True, "항목": stg.TARGETS[t]["label"], "target": t, "하한": lo, "상한": hi}
             for t, (lo, hi) in goals0.items()]
    gframe = pd.DataFrame(grows)
    gframe[["하한", "상한"]] = gframe[["하한", "상한"]].apply(pd.to_numeric, errors="coerce")
    gdf = st.data_editor(gframe, key=f"goal_edit_{product}_{gbasis[:4]}", hide_index=True, width="stretch",
                         disabled=["항목", "target"], column_config={
                             "target": None, "사용": st.column_config.CheckboxColumn(width="small"),
                             "하한": st.column_config.NumberColumn(format="%.1f"),
                             "상한": st.column_config.NumberColumn(format="%.1f")})
    goals = {r["target"]: (None if pd.isna(r["하한"]) else float(r["하한"]), None if pd.isna(r["상한"]) else float(r["상한"]))
             for _, r in gdf.iterrows() if r["사용"] and not (pd.isna(r["하한"]) and pd.isna(r["상한"]))}
    st.caption("빈 칸(None)은 제한 없음을 뜻합니다.")
    g1, g2, g3 = st.columns([2.2, 1, 1])
    levers = g1.multiselect("조정 가능한 레버", list(stg.LEVERS), default=list(stg.LEVERS),
                            format_func=lambda k: stg.LEVERS[k]["label"], key=f"levers_{product}")
    z = g2.slider("안전 여유(× RMSE)", 0.0, 1.5, 0.0, 0.25, key=f"z_{product}",
                  help="예측 불확실성만큼 목표를 안쪽으로 당겨 계산(0 = 예측값 기준)")
    ls_max = g3.number_input("석회석 상한(%)", value=5.0, step=0.5, key=f"lsmax_{product}",
                             help="KS L 5201 소량 혼합성분 한도 — 원문 확인 필요")
    plan = stg.optimize_controls(sm, inputs, goals, levers, z, ls_max)
    o1, o2 = st.columns([1.1, 1])
    with o1:
        st.markdown("**예측 결과(현재 → 조정 후)**")
        st.dataframe(plan.outcome_table(), hide_index=True, column_config={
            "현재 예측": st.column_config.NumberColumn(format="%.1f"), "조정 후 예측": st.column_config.NumberColumn(format="%.1f")})
    with o2:
        st.markdown("**권장 조정(최소 변경 조합)**")
        lt = plan.lever_table()
        if len(lt):
            st.dataframe(lt, hide_index=True, column_config={
                c: st.column_config.NumberColumn(format="%.2f") for c in ("현재", "권장", "변경")})
        else:
            st.success("현재 조건으로 모든 목표를 충족하는 것으로 예측됩니다(조정 불필요).", icon="✅")
    for msg in plan.messages:
        st.warning(msg, icon="⚠️")
    if len(plan.single_lever):
        with st.expander("레버 하나만 쓴다면? (목표 차이를 단독으로 메우는 데 필요한 변경, 선형 근사)"):
            st.dataframe(plan.single_lever, hide_index=True, column_config={
                "차이": st.column_config.NumberColumn(format="%.2f"), "필요 변경": st.column_config.NumberColumn(format="%+.2f")})
    groups = stg.needed_goals(plan.pred_before, plan.goals)
    with st.expander("📘 규칙 기반 제어 솔루션(지식베이스)", expanded=bool(groups)):
        st.markdown(stg.solution_markdown(sm, plan, product))
        if not groups:
            st.caption("현재 미충족 목표가 없어 조치 그룹을 표시하지 않았습니다. 전체 조치 목록은 아래에서 확인하세요.")
    with st.expander("조치 라이브러리 전체(초기강도·장기강도·응결)"):
        for g in stg.CONTROL_KB.values():
            st.markdown(f"**{g['title']}**")
            st.dataframe(pd.DataFrame([{"조치": a.title, "효과(추정)": a.effect, "부작용": a.side_effects, "실행": a.how,
                                        "확인": a.verify, "근거": a.basis} for a in g["actions"]]), hide_index=True)
    ai_panel("strength", strength_context(product, sm, inputs, source, pred, plan, goals), key=f"ai_strength_{product}")
