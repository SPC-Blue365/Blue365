"""SPC 관리도 · 공정능력."""

import pandas as pd
import streamlit as st

from qms.reports import capability_table
from qms.spc import capability, capability_grade, rule_name
from qms.standards import STAGES, TABLES
from qms.ui import fmt, get_ctx, histogram_figure, sidebar, spc_figure

ctx = get_ctx()
sidebar(ctx)
reg, store, settings = ctx.registry, ctx.store, ctx.settings
period = store.period()
st.title("📊 SPC 관리도 · 공정능력")
if period is None:
    st.info("데이터가 없습니다.")
    st.stop()

tab1, tab2 = st.tabs(["관리도·공정능력 (항목별)", "공정능력 현황 (전체 항목)"])
with tab1:
    keys = [i.key for s in STAGES for i in reg.by_stage(s) if (i.limits or i.rules) and not i.ks_is_method]
    c1, c2, c3, c4 = st.columns([2.2, 1, 1.6, 1.2])
    key = c1.selectbox("항목", keys, index=keys.index("clk_fcao") if "clk_fcao" in keys else 0,
                       format_func=lambda k: f"[{reg[k].stage}] {reg[k].label()}", key="spc_item")
    item = reg[key]
    prods = reg.products_for(key)
    product = c2.selectbox("품종", prods, format_func=lambda p: p or "구분 없음", key="spc_prod")
    rng = c3.date_input("기간", value=(period[0].date(), period[1].date()), min_value=period[0].date(),
                        max_value=period[1].date(), key="spc_range")
    rs = TABLES[item.table].get("spc_resample")
    basis_opts = ([f"{rs} 평균(판정 기준)", "원 데이터"] if rs else ["원 데이터(판정 기준)"])
    basis = c4.selectbox("데이터 기준", basis_opts, key="spc_basis")
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        st.stop()
    start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(hours=23, minutes=59)
    raw = store.series(key, reg, product, start, end)
    s = raw.resample(rs).mean().dropna() if (rs and basis.startswith(rs)) else raw
    if len(s) < 10:
        st.warning("관리도를 그리기에 데이터가 부족합니다(10점 미만).")
        st.stop()
    show_spec = st.toggle("규격·관리기준선 함께 표시", value=True, key="spc_spec")
    fig_i, fig_mr, info = spc_figure(s, item, product, settings, show_spec=show_spec)
    st.plotly_chart(fig_i, key="spc_i")
    st.plotly_chart(fig_mr, key="spc_mr")
    stats = info["stats"]
    if stats:
        st.caption(f"기준기간 {stats.base_start:%Y-%m-%d} ~ {stats.base_end:%Y-%m-%d} (n={stats.n}) · "
                   f"CL {stats.center:,.{item.decimals + 1}f} · σ {stats.sigma:,.{item.decimals + 2}f} · "
                   f"적용 규칙: {', '.join(rule_name(r, settings.get('run_length', 9), settings.get('trend_length', 6)) for r in info['rules'])}"
                   " · 기준기간·규칙은 ⚙️ 기준·알림 설정에서 변경")
    viol = {r: int(f.sum()) for r, f in info["flags"].items()}
    if any(viol.values()):
        st.markdown("**판정규칙 위반 점 수**: " + " · ".join(
            f"{rule_name(r, settings.get('run_length', 9), settings.get('trend_length', 6))} **{n}점**"
            for r, n in viol.items() if n))

    st.subheader("공정능력")
    lim = item.limits_for(product)
    cap = capability(raw, lim.lsl, lim.usl)
    m = st.columns(6)
    m[0].metric("n", f"{cap['n']:,}")
    m[1].metric("평균", fmt(cap["mean"], item.decimals + 1, item.unit))
    m[2].metric("Cp", fmt(cap["Cp"], 2))
    m[3].metric("Cpk", fmt(cap["Cpk"], 2), help="군내변동 σ=MR̄/1.128")
    m[4].metric("Ppk", fmt(cap["Ppk"], 2), help="전체 표준편차 기준")
    m[5].metric("사내기준 이탈", fmt(cap["out_pct"], 1, "%"))
    st.markdown(f"등급: **{capability_grade(cap['Cpk'])}** — 관용 기준: Cpk ≥ 1.33 충분, 1.0~1.33 보통, 1.0 미만 개선 필요")
    if lim.lsl is None and lim.usl is None:
        st.caption("사내 관리기준이 설정되지 않아 공정능력지수를 계산할 수 없습니다.")
    st.plotly_chart(histogram_figure(raw, item, product), key="spc_hist")

with tab2:
    rng2 = st.date_input("기간", value=(max(period[0].date(), (period[1] - pd.Timedelta(days=30)).date()), period[1].date()),
                         min_value=period[0].date(), max_value=period[1].date(), key="cap_range")
    if isinstance(rng2, (list, tuple)) and len(rng2) == 2:
        t = capability_table(store, reg, pd.Timestamp(rng2[0]), pd.Timestamp(rng2[1]) + pd.Timedelta(hours=23, minutes=59))
        if len(t):
            t = t.drop(columns=["item_key"]).sort_values("Cpk")
            st.dataframe(t, hide_index=True, height=520, column_config={
                "Cpk": st.column_config.NumberColumn(format="%.2f", help="1.33 이상 충분, 1.0 미만 개선 필요"),
                "Ppk": st.column_config.NumberColumn(format="%.2f"),
                "기준이탈(%)": st.column_config.NumberColumn(format="%.1f"),
            })
            weak = t[t["Cpk"] < 1.0]
            if len(weak):
                st.warning(f"공정능력 부족(Cpk<1.0) {len(weak)}개 항목: " + ", ".join(f"{r['항목']}({r['품종']})" for _, r in weak.iterrows()))
            st.download_button("공정능력 표 CSV", t.to_csv(index=False).encode("utf-8-sig"), "capability.csv", "text/csv")
