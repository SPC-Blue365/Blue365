"""시멘트 화학 계산기: 모듈러스 · Bogue 광물 · 액상량 · 3성분 조합 계산."""

import pandas as pd
import streamlit as st

from qms import chemistry as chem
from qms.ui import get_ctx, sidebar

ctx = get_ctx()
sidebar(ctx)
reg = ctx.registry
st.title("🧮 시멘트 화학 계산기")
tab1, tab2, tab3 = st.tabs(["클링커·생료 계산", "3성분 원료 조합 계산", "계산식·출처"])

with tab1:
    st.caption("XRF 분석값(질량 %)을 입력하면 LSF·SM·IM, Bogue 광물 조성, 1450 ℃ 액상량을 계산합니다.")
    c = st.columns(5)
    cao = c[0].number_input("CaO", value=65.8, step=0.1, format="%.2f")
    sio2 = c[1].number_input("SiO₂", value=21.9, step=0.1, format="%.2f")
    al2o3 = c[2].number_input("Al₂O₃", value=5.45, step=0.05, format="%.2f")
    fe2o3 = c[3].number_input("Fe₂O₃", value=3.35, step=0.05, format="%.2f")
    mgo = c[4].number_input("MgO", value=2.6, step=0.1, format="%.2f")
    c = st.columns(5)
    so3 = c[0].number_input("SO₃", value=0.70, step=0.05, format="%.2f")
    k2o = c[1].number_input("K₂O", value=0.80, step=0.05, format="%.2f")
    na2o = c[2].number_input("Na₂O", value=0.18, step=0.02, format="%.2f")
    fcao = c[3].number_input("f-CaO", value=1.0, step=0.1, format="%.2f", help="Bogue 계산 시 CaO에서 차감")
    mode = c[4].selectbox("시료", ["클링커", "생료(킬른 피드)", "시멘트(석고 보정)"])

    l = chem.lsf(cao, sio2, al2o3, fe2o3, so3, gypsum_correction=mode.startswith("시멘트"))
    sm = chem.silica_modulus(sio2, al2o3, fe2o3)
    im = chem.iron_modulus(al2o3, fe2o3)
    st.subheader("결과")
    m = st.columns(3)
    pref = "rm" if mode.startswith("생료") else "clk"
    for col, (name, val, key) in zip(m, (("LSF", l, f"{pref}_lsf"), ("SM", sm, f"{pref}_sm"), ("IM", im, f"{pref}_im"))):
        lim = reg[key].limits_for(None) if key in reg else None
        rng = (f"사내 {lim.lsl:g}~{lim.usl:g}" if lim and lim.lsl is not None and lim.usl is not None else "")
        ok = (lim is None or lim.lsl is None or lim.usl is None or lim.lsl <= val <= lim.usl)
        col.metric(name, f"{val:.2f}", delta=(("✅ " if ok else "⚠️ ") + rng) if rng else None, delta_color="off",
                   delta_arrow="off")
    if not mode.startswith("생료"):
        ph = chem.bogue(cao, sio2, al2o3, fe2o3, so3, fcao)
        liq = chem.liquid_phase_1450(al2o3, fe2o3, mgo, k2o, na2o)
        m = st.columns(6)
        m[0].metric("C₃S", f"{ph['C3S']:.1f} %")
        m[1].metric("C₂S", f"{ph['C2S']:.1f} %")
        m[2].metric("C₃A", f"{ph['C3A']:.1f} %")
        m[3].metric("C₄AF" if al2o3 / fe2o3 >= 0.64 else "ss(C₄AF+C₂F)", f"{ph['C4AF']:.1f} %")
        m[4].metric("액상량(1450℃)", f"{liq:.1f} %")
        m[5].metric("Na₂Oeq", f"{chem.na2o_eq(na2o, k2o):.2f} %")
        st.caption(f"소성성 지수 BI = C₃S/(C₃A+C₄AF) = {chem.burnability_index(ph['C3S'], ph['C3A'], ph['C4AF']):.2f} "
                   "(경험 지표, 값이 클수록 난소성) · A/F = "
                   f"{al2o3 / fe2o3:.2f}" + (" (< 0.64: C₃A=0, 고용체 계산)" if al2o3 / fe2o3 < 0.64 else ""))
        if mgo > 2.0:
            st.caption("MgO가 2%를 넘으면 LSF 식(Lea & Parker)과 액상량 식의 MgO 항 적용 범위를 벗어납니다(액상량은 2.0%로 제한).")
    else:
        st.caption("생료는 소성 전 상태이므로 광물 조성 대신 모듈러스로 관리합니다. 생료 LSF는 석탄회 흡수로 클링커보다 높게 관리합니다.")

with tab2:
    st.caption("목표 LSF·SM을 동시에 만족하는 3성분(예: 석회석·점토·철광석) 배합비를 계산합니다(건조 기준).")
    base = pd.DataFrame([
        {"원료": "석회석", "CaO": 52.0, "SiO2": 4.0, "Al2O3": 1.0, "Fe2O3": 0.5},
        {"원료": "점토(셰일)", "CaO": 3.0, "SiO2": 60.0, "Al2O3": 15.0, "Fe2O3": 6.0},
        {"원료": "철광석", "CaO": 2.0, "SiO2": 12.0, "Al2O3": 3.0, "Fe2O3": 75.0},
    ])
    mats = st.data_editor(base, hide_index=True, num_rows="fixed", key="mix_edit")
    t1, t2 = st.columns(2)
    lsf_t = t1.number_input("목표 LSF", value=99.0, step=0.5)
    sm_t = t2.number_input("목표 SM", value=2.50, step=0.05)
    res = chem.raw_mix_3([{"CaO": r["CaO"], "SiO2": r["SiO2"], "Al2O3": r["Al2O3"], "Fe2O3": r["Fe2O3"]}
                          for _, r in mats.iterrows()], lsf_t, sm_t)
    if res["feasible"]:
        cols = st.columns(3)
        for col, (_, r), x in zip(cols, mats.iterrows(), res["ratios"]):
            col.metric(r["원료"], f"{x:.2f} %")
        st.success(f"조합 결과: LSF {res['lsf']:.1f} · SM {res['sm']:.2f} · IM {res['im']:.2f} "
                   f"(CaO {res['mix']['CaO']:.2f}, SiO₂ {res['mix']['SiO2']:.2f}, Al₂O₃ {res['mix']['Al2O3']:.2f}, "
                   f"Fe₂O₃ {res['mix']['Fe2O3']:.2f})")
        st.caption("IM은 3성분으로 동시에 맞출 수 없으므로 결과값을 확인하세요(IM까지 맞추려면 4성분 필요).")
    else:
        st.error("이 원료 조합으로는 목표 LSF·SM을 만족할 수 없습니다(음수 배합비). 원료 또는 목표를 조정하세요.")

with tab3:
    st.markdown("""
| 지표 | 계산식 | 출처·비고 |
|---|---|---|
| LSF | 100·CaO / (2.8·SiO₂ + 1.18·Al₂O₃ + 0.65·Fe₂O₃) | Lea & Parker (MgO ≤ 2%). 시멘트는 CaO − 0.7·SO₃ |
| SM | SiO₂ / (Al₂O₃ + Fe₂O₃) | 규산율 |
| IM | Al₂O₃ / Fe₂O₃ | 철률(알루미나율) |
| C₃S | 4.071·CaO′ − 7.600·SiO₂ − 6.718·Al₂O₃ − 1.430·Fe₂O₃ − 2.852·SO₃ | ASTM C150 Bogue (A/F ≥ 0.64), CaO′ = CaO − f-CaO |
| C₂S | 2.867·SiO₂ − 0.7544·C₃S | ASTM C150 |
| C₃A | 2.650·Al₂O₃ − 1.692·Fe₂O₃ | ASTM C150 (A/F < 0.64이면 0) |
| C₄AF | 3.043·Fe₂O₃ | ASTM C150 (A/F < 0.64이면 ss = 2.100·Al₂O₃ + 1.702·Fe₂O₃) |
| 액상량(1450℃) | 3.00·Al₂O₃ + 2.25·Fe₂O₃ + MgO + K₂O + Na₂O | Lea & Parker 경험식 (A/F ≥ 1.38, MgO는 2.0%까지) |
| Na₂Oeq | Na₂O + 0.658·K₂O | ASTM C150 등가 알칼리 |

※ Bogue 계산값은 평형 가정에 따른 계산 광물량으로 XRD 실측과 차이가 있습니다(통상 C₃S 과소·C₂S 과대 경향 — 경험칙).
""")
