"""공정 모니터링: 공정 단계별 항목 추세와 기준선."""

import pandas as pd
import streamlit as st

from qms.alerts import SEVERITY_ICON
from qms.spc import capability
from qms.standards import STAGES, TABLES
from qms.store import line_label, line_sort_key
from qms.ui import fmt, get_ctx, page_header, trend_figure

ctx = get_ctx()
reg, store = ctx.registry, ctx.store
period = store.period()
page_header(ctx, "📈 공정 모니터링")
if period is None:
    st.info("데이터가 없습니다.")
    st.stop()

stage = st.segmented_control("공정 단계", STAGES, default="클링커", key="mon_stage") or "클링커"
f1, f2, f3, f4 = st.columns([1.3, 1, 1.6, 1.2])
items_in_stage = reg.by_stage(stage)
stage_lines = sorted({ln for t in {i.table for i in items_in_stage} for ln in store.lines(t)}, key=line_sort_key)
ALL = "전체(호기별 겹쳐 보기)"
if stage_lines:
    line_pick = f1.selectbox("공정구분(호기·밀)", [ALL, *stage_lines], key=f"mon_line_{stage}",
                             format_func=lambda v: v if v == ALL else line_label(v),
                             help="같은 시각이라도 4K·5K·6K·7K, 원료밀(R/M)·시멘트밀(C/M)은 따로 저장·판정합니다.")
else:
    line_pick = f1.selectbox("공정구분(호기·밀)", ["구분 없음"], disabled=True, key=f"mon_line_na_{stage}",
                             help="이 공정 자료에 공정구분(호기) 열이 없습니다. 새 업로드 양식의 '공정구분' 열을 채우면 호기별로 나뉩니다.")
line_sel = None if line_pick in (ALL, "구분 없음") else line_pick
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
    item_lines = store.item_lines(key, reg, prod)
    line = line_sel if line_sel in item_lines else None
    multi = line is None and len(item_lines) >= 2
    s = store.series(key, reg, prod, start, end, line=line)
    with st.container(border=True):
        lim = item.limits_for(prod)
        evs = [e for e in ctx.events if e.item_key == key and e.product == prod and e.end >= start and e.start <= end
               and (line is None or e.line == line)]
        worst = max((e.severity for e in evs), key=lambda v: {"위험": 3, "경고": 2, "주의": 1}[v], default="정상")
        st.markdown(f"**{SEVERITY_ICON[worst]} {item.name}**" + (f" [{prod}]" if prod else "") + (f" [{line}]" if line else "")
                    + (f" <span style='color:gray;font-size:0.85em'>{item.description}</span>" if item.description else ""),
                    unsafe_allow_html=True)
        if len(s) == 0:
            st.caption("기간 내 데이터 없음")
            continue
        if multi:                                            # 호기를 섞어 통계를 내지 않는다 — 호기별 요약 표
            rows = []
            for ln in item_lines:
                sl = store.series(key, reg, prod, start, end, line=ln)
                if len(sl) == 0:
                    continue
                cp = capability(sl, lim.lsl, lim.usl)
                n_o = (int((sl < lim.lsl).sum()) if lim.lsl is not None else 0) + (int((sl > lim.usl).sum()) if lim.usl is not None else 0)
                ev_l = [e for e in evs if e.line == ln]
                w = max((e.severity for e in ev_l), key=lambda v: {"위험": 3, "경고": 2, "주의": 1}[v], default="정상")
                rows.append({"상태": f"{SEVERITY_ICON[w]} {w}", "공정구분": line_label(ln), "n": len(sl),
                             "최근값": fmt(float(sl.iloc[-1]), item.decimals), "평균": fmt(cp["mean"], item.decimals),
                             "표준편차": fmt(cp["std"], item.decimals + 1),
                             "사내기준 이탈": f"{n_o}점" if (lim.lsl is not None or lim.usl is not None) else "-",
                             "Cpk": fmt(cp["Cpk"], 2)})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            fig = trend_figure(ctx, key, prod, start, end, resample=resample, height=300)
            if fig:
                st.plotly_chart(fig, key=f"mon_fig_{key}")
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
        fig = trend_figure(ctx, key, prod, start, end, resample=resample, height=300, line=line)
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
        if line_sel and "line" in df:
            df = df[df["line"] == line_sel]
        st.markdown(f"**{TABLES[t]['label']}** ({len(df)}행)")
        st.dataframe(df, hide_index=True, height=260)
        st.download_button(f"{TABLES[t]['label']} CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{t}_{start:%Y%m%d}_{end:%Y%m%d}.csv", mime="text/csv", key=f"dl_{t}")
