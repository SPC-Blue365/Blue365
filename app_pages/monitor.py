"""공정 모니터링: 공정 단계별 항목 추세와 기준선."""

import pandas as pd
import streamlit as st

from qms.alerts import SEVERITY_ICON
from qms.spc import capability
from qms.standards import STAGES, TABLES
from qms.ui import fmt, get_ctx, sidebar, trend_figure

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store
period = store.period()
st.title("📈 공정 모니터링")
if period is None:
    st.info("데이터가 없습니다.")
    st.stop()

stage = st.segmented_control("공정 단계", STAGES, default="클링커", key="mon_stage") or "클링커"
f2, f3, f4 = st.columns([1, 1.6, 1.2])
items_in_stage = reg.by_stage(stage)
by_product = any(TABLES[i.table]["by_product"] for i in items_in_stage)
product = f2.selectbox("품종", ["1종", "3종"], key="mon_prod") if by_product else None
if not by_product:
    f2.selectbox("품종", ["구분 없음"], disabled=True, key="mon_prod_na")
default_start = max(period[0].date(), (period[1] - pd.Timedelta(days=14)).date())
rng = f3.date_input("기간", value=(default_start, period[1].date()), min_value=period[0].date(),
                    max_value=period[1].date(), key="mon_range")
resolution = f4.selectbox("집계", ["원 데이터", "8시간 평균", "일 평균"], key="mon_res")
if not isinstance(rng, (list, tuple)) or len(rng) != 2:
    st.stop()
start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(hours=23, minutes=59)
resample = {"원 데이터": None, "8시간 평균": "8h", "일 평균": "1D"}[resolution]

keys = [i.key for i in items_in_stage if product is None or reg.products_for(i.key) == [None]
        or product in reg.products_for(i.key)]
defaults = [k for k in keys if reg[k].key_item] or [k for k in keys if reg[k].limits][:4] or keys[:4]
sel = st.multiselect("표시 항목", keys, default=defaults, format_func=lambda k: reg[k].label(), key=f"mon_items_{stage}")

for key in sel:
    item = reg[key]
    prod = product if TABLES[item.table]["by_product"] else None
    if prod and item.limits and "*" not in item.limits and prod not in item.limits:
        continue
    s = store.series(key, reg, prod, start, end)
    with st.container(border=True):
        lim = item.limits_for(prod)
        evs = [e for e in ctx.events if e.item_key == key and e.product == prod and e.end >= start and e.start <= end]
        worst = max((e.severity for e in evs), key=lambda v: {"위험": 3, "경고": 2, "주의": 1}[v], default="정상")
        st.markdown(f"**{SEVERITY_ICON[worst]} {item.name}**" + (f" [{prod}]" if prod else "")
                    + (f" <span style='color:gray;font-size:0.85em'>{item.description}</span>" if item.description else ""),
                    unsafe_allow_html=True)
        if len(s) == 0:
            st.caption("기간 내 데이터 없음")
            continue
        m = st.columns(5)
        cap = capability(s, lim.lsl, lim.usl)
        m[0].metric("최근값", fmt(float(s.iloc[-1]), item.decimals, item.unit), help=f"{s.index[-1]:%m/%d %H:%M}")
        m[1].metric("평균", fmt(cap["mean"], item.decimals, item.unit),
                    delta=(f"목표 대비 {cap['mean'] - lim.target:+,.{item.decimals}f}" if lim.target is not None else None),
                    delta_color="off")
        m[2].metric("표준편차", fmt(cap["std"], item.decimals + 1))
        n_out = (int((s < lim.lsl).sum()) if lim.lsl is not None else 0) + (int((s > lim.usl).sum()) if lim.usl is not None else 0)
        m[3].metric("사내기준 이탈", f"{n_out}점" if (lim.lsl is not None or lim.usl is not None) else "-")
        m[4].metric("Cpk", fmt(cap["Cpk"], 2), help="군내변동(MR/1.128) 기준. 1.33 이상 충분, 1.0 미만 개선 필요")
        fig = trend_figure(ctx, key, prod, start, end, resample=resample, height=300)
        if fig:
            st.plotly_chart(fig, key=f"mon_fig_{key}")
        if evs:
            st.caption("이벤트: " + " / ".join(f"{SEVERITY_ICON[e.severity]} {e.rule_desc} ({e.start:%m/%d %H:%M}~{e.end:%m/%d %H:%M})"
                                             for e in evs[:4]) + (" …" if len(evs) > 4 else ""))

with st.expander("데이터 표 보기 / 내려받기"):
    tables = {i.table for i in items_in_stage}
    for t in sorted(tables):
        df = store.filtered(start, end).tables.get(t, pd.DataFrame())
        if product and "product" in df:
            df = df[df["product"] == product]
        st.markdown(f"**{TABLES[t]['label']}** ({len(df)}행)")
        st.dataframe(df, hide_index=True, height=260)
        st.download_button(f"{TABLES[t]['label']} CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{t}_{start:%Y%m%d}_{end:%Y%m%d}.csv", mime="text/csv", key=f"dl_{t}")
