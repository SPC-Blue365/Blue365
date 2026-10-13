"""그래프 보기: 보고 싶은 항목을 골라 기간·집계를 정해 추이를 본다(출하시멘트·공정 데이터 전 항목). 구성을 이름 붙여 저장."""

import io

import pandas as pd
import streamlit as st

from qms import charts as CH
from qms import ship_dest as D
from qms import shipment as S
from qms.standards import TABLES
from qms.ui import get_ctx, page_header

ctx = get_ctx()
page_header(ctx, "📉 그래프 보기")
reg, store = ctx.registry, ctx.store
ss = st.session_state
st.caption("보고 싶은 항목을 여러 개 고르고 기간·집계를 정하면 항목별 추이 그래프를 그립니다. 자주 보는 구성은 이름을 붙여 저장해 두면 "
           "다음부터 한 번에 불러옵니다. 항목 이름·단위는 ⚙️ 설정 → ✏️ 용어·제목에서 바꿀 수 있습니다.")

STATE_KEYS = ("cv_source", "cv_ship_keys", "cv_proc_keys", "cv_product", "cv_period", "cv_range", "cv_agg", "cv_ma", "cv_mode",
              "cv_cols", "cv_limits", "cv_points", "cv_title", "cv_add", "cv_ship_mode", "cv_kind", "cv_dest")


@st.cache_data(show_spinner=False)
def _ship(m1: float, m2: float) -> pd.DataFrame:
    return D.attach_destinations(S.load_shipment())


# ── 저장된 보기 불러오기 ────────────────────────────────────────────────
views = CH.load_views()
v1, v2, v3 = st.columns([2.2, 1, 1], vertical_alignment="bottom")
names = [v["name"] for v in views]
pick = v1.selectbox("저장된 보기", ["(새로 만들기)", *names], key="cv_pick")
if v2.button("불러오기", disabled=pick == "(새로 만들기)", width="stretch"):
    view = next(v for v in views if v["name"] == pick)
    for k, val in view.get("state", {}).items():
        if k == "cv_range" and val:
            val = tuple(pd.Timestamp(x).date() for x in val)
        ss[k] = val
    st.rerun()
if v3.button("삭제", disabled=pick == "(새로 만들기)", width="stretch"):
    CH.delete_view(pick)
    st.rerun()

source = st.radio("자료", ["출하시멘트", "공정 데이터"], horizontal=True, key="cv_source")
ship_df = _ship(S.shipment_mtime(), D.dest_mtime()) if source == "출하시멘트" else pd.DataFrame()

# ── 항목 고르기 ─────────────────────────────────────────────────────────
if source == "출하시멘트":
    if ship_df.empty:
        st.info("저장된 출하시멘트 자료가 없습니다. 🚢 출하시멘트 또는 📥 데이터 관리에서 LIMS 엑셀을 올리세요.")
        st.stop()
    core = [it.key for it in S.ITEMS if it.key in ship_df and ship_df[it.key].notna().any()]
    extras = [c for c in S.extra_columns(ship_df) if ship_df[c].notna().any()]
    opts = core + extras
    lab = {k: (S.BY_KEY[k].name + (f" ({S.BY_KEY[k].unit})" if S.BY_KEY[k].unit else "")) if k in S.BY_KEY else f"{k[2:]} (기타)" for k in opts}
    presets = {"강도 1·3·7·28일": ["s1", "s3", "s7", "s28"], "화학성분": ["loi", "al2o3", "mgo", "so3", "cl", "ta"],
               "분말도·물성": ["r45", "blaine", "cons", "flow", "fst"], "배합 구성": ["ls", "addr"]}
    pc = st.columns(len(presets) + 1)
    for (pname, keys), col in zip(presets.items(), pc):
        if col.button(pname, width="stretch"):
            ss["cv_ship_keys"] = [k for k in keys if k in opts]
            st.rerun()
    if pc[-1].button("전부", width="stretch"):
        ss["cv_ship_keys"] = core
        st.rerun()
    if "cv_ship_keys" not in ss:
        ss["cv_ship_keys"] = [k for k in ("s1", "s3", "s7", "s28") if k in opts]
    ss["cv_ship_keys"] = [k for k in ss["cv_ship_keys"] if k in opts]
    keys = st.multiselect("항목(여러 개 선택)", opts, key="cv_ship_keys", format_func=lambda k: lab[k])
    with st.expander("출하 조건(첨가재·모선 수·제품 구분·양하지)"):
        f1, f2, f3, f4 = st.columns(4)
        adds = sorted(a for a in ship_df["additive"].dropna().unique() if a)
        add = f1.selectbox("첨가재", ["전체", *adds], key="cv_add")
        smode = f2.selectbox("모선 수", ["전체", "1모선 단독 시험만", "2모선 이상(평균값)만"], key="cv_ship_mode")
        kind = f3.selectbox("제품 구분", ["일반 제품만", "저염 포함 전체", "저염 제품만"], key="cv_kind")
        dests = ["전체", *[d for d in ship_df["dest"].value_counts().index]]
        dest = f4.selectbox("양하지", dests, key="cv_dest")
    first, last = ship_df["date"].min(), ship_df["date"].max()
else:
    period = store.period()
    if period is None:
        st.info("공정 데이터가 없습니다.")
        st.stop()
    first, last = period
    items = [it for it in reg.all() if not it.prediction]
    lab = {it.key: f"[{it.stage}] {it.name}" + (f" ({it.unit})" if it.unit else "") for it in items}
    opts = [it.key for it in items]
    if "cv_proc_keys" not in ss:
        ss["cv_proc_keys"] = [k for k in ("phy_s1", "phy_s3", "phy_s7", "phy_s28") if k in opts]
    ss["cv_proc_keys"] = [k for k in ss["cv_proc_keys"] if k in opts]
    keys = st.multiselect("항목(여러 개 선택)", opts, key="cv_proc_keys", format_func=lambda k: lab[k])
    by_prod = any(TABLES[reg[k].table]["by_product"] for k in keys)
    product = st.selectbox("품종", ["1종", "3종"], key="cv_product") if by_prod else None

# ── 기간·표시 방법 ──────────────────────────────────────────────────────
for k, v in (("cv_period", "최근 180일"), ("cv_ma", 0), ("cv_cols", 2), ("cv_limits", True), ("cv_points", True)):
    ss.setdefault(k, v)
o1, o2, o3, o4 = st.columns([1.3, 1, 1, 1.2])
per = o1.selectbox("기간", [*CH.PERIODS, "직접 지정"], key="cv_period")
if per == "직접 지정":
    if "cv_range" not in ss or not ss["cv_range"]:
        ss["cv_range"] = (max(first, last - pd.Timedelta(days=180)).date(), last.date())
    rng = o1.date_input("기간 지정", key="cv_range", min_value=first.date(), max_value=last.date())
    start, end = (pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(hours=23, minutes=59)) if isinstance(rng, (list, tuple)) and len(rng) == 2 else (first, last)
else:
    d = CH.PERIODS[per]
    start, end = (last - pd.Timedelta(days=d) if d else first), last
agg = o2.selectbox("집계", list(CH.AGGS), key="cv_agg", help="원자료 = 시험값 그대로, 일·주·월 평균 = 그 기간 평균")
ma = o3.number_input("이동평균(점, 0=끔)", 0, 120, key="cv_ma")
mode = o4.selectbox("보기 방식", ["항목별 그래프", "한 그래프(표준화해서 겹치기)", "한 그래프(같은 단위만 겹치기)"], key="cv_mode",
                    help="단위가 다른 항목은 축을 두 개로 겹치지 않습니다. 추세 비교는 '표준화'(평균 0·표준편차 1)로 겹쳐 보세요.")
p1, p2, p3, p4 = st.columns([1, 1, 1, 2.5])
cols = p1.selectbox("한 줄 그래프 수", [1, 2, 3], key="cv_cols")
show_lim = p2.checkbox("기준선 표시", key="cv_limits")
show_pts = p3.checkbox("점 표시", key="cv_points")
title = p4.text_input("그래프 묶음 제목(선택)", key="cv_title", placeholder="예: 2026년 1종 강도 추이")

if not keys:
    st.info("위에서 항목을 하나 이상 고르세요.")
    st.stop()

# ── 자료 만들기 ─────────────────────────────────────────────────────────
series: list[tuple[str, str, pd.Series]] = []
limits: dict[str, dict] = {}
std = S.load_ship_standards()
if source == "출하시멘트":
    dfx = S.apply_filters(ship_df, start, end, None if add == "전체" else add, smode, kind, None if dest == "전체" else dest)
    for k in keys:
        sub = dfx[dfx[k].notna()]
        s = pd.Series(sub[k].astype(float).values, index=pd.DatetimeIndex(sub["date"]))
        s = CH.aggregate(s, CH.AGGS[agg])
        it = S.BY_KEY.get(k)
        name, unit = (it.name, it.unit) if it else (k[2:], "")
        series.append((name, unit, s))
        if show_lim and it and len(s):
            lims = {}
            for f in CH.LIMIT_STYLE:
                vals = [S.effective_limits(std, k, int(ts.year)).get(f) for ts in s.index]
                ser = pd.Series([float(v) if v is not None else float("nan") for v in vals], index=s.index)
                if ser.notna().any():
                    lims[f] = ser
            limits[name] = lims
else:
    for k in keys:
        it = reg[k]
        prod = product if TABLES[it.table]["by_product"] else None
        s = CH.aggregate(store.series(k, reg, prod, start, end), CH.AGGS[agg])
        name = it.name + (f" [{prod}]" if prod else "")
        series.append((name, it.unit, s))
        if show_lim:
            lim = it.limits_for(prod)
            limits[name] = {"ks_min": lim.ks_min, "ks_max": lim.ks_max, "lsl": lim.lsl, "usl": lim.usl, "target": lim.target}

empty = [n for n, _, s in series if s.empty]
if empty:
    st.caption("이 조건에 값이 없는 항목: " + ", ".join(empty))
series = [x for x in series if not x[2].empty]
if not series:
    st.warning("선택한 기간·조건에 값이 없습니다.")
    st.stop()

if title:
    st.subheader(title)
st.caption(f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} · {agg}" + (f" · 이동평균 {ma}점" if ma else "")
           + (" · 0(시험 전)은 미시험으로 제외" if source == "출하시멘트" else ""))

if mode == "항목별 그래프":
    grid = st.columns(cols)
    for i, (name, unit, s) in enumerate(series):
        fig = CH.item_figure(s, name, unit, color=CH.SERIES[0], ma=ma, limits=limits.get(name), show_points=show_pts,
                             height=300 if cols > 1 else 360)
        with grid[i % cols].container(border=True):
            st.plotly_chart(fig, key=f"cv_fig_{i}")
            st.caption(f"n={len(s)} · 평균 {s.mean():,.2f} · 표준편차 {s.std(ddof=1):,.2f} · 최소 {s.min():,.2f} · 최대 {s.max():,.2f}")
else:
    standardize = mode.startswith("한 그래프(표준화")
    use = series
    if not standardize:
        unit0 = series[0][1]
        use = [x for x in series if x[1] == unit0]
        skipped = [x[0] for x in series if x[1] != unit0]
        if skipped:
            st.warning(f"단위가 달라 겹치지 않은 항목: {', '.join(skipped)} — ‘표준화해서 겹치기’나 ‘항목별 그래프’로 보세요.")
    if len(use) > len(CH.SERIES):
        st.warning(f"한 그래프에는 {len(CH.SERIES)}개까지 겹칩니다. 나머지는 ‘항목별 그래프’로 보세요.")
    with st.container(border=True):
        st.plotly_chart(CH.overlay_figure(use, standardize, ma=ma, title=title), key="cv_overlay")
    if standardize:
        st.caption("표준화: 항목마다 (값−평균)÷표준편차 로 바꿔 단위가 달라도 오르내림을 한 축에서 비교합니다. 실제 값은 마우스를 올리면 보입니다.")

tbl = CH.wide_table(series)
with st.expander(f"표로 보기 ({len(tbl)}행)"):
    st.dataframe(tbl, hide_index=True, column_config={"일시": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    tbl.to_excel(xw, sheet_name="그래프 자료", index=False)
st.download_button("⬇️ 그래프 자료(엑셀)", buf.getvalue(), file_name=f"그래프자료_{start:%Y%m%d}_{end:%Y%m%d}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ── 지금 구성 저장 ──────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**💾 이 구성 저장** — 항목·기간·집계·보기 방식·제목을 이름 붙여 저장합니다(같은 이름이면 덮어씀).")
    s1, s2 = st.columns([3, 1], vertical_alignment="bottom")
    vname = s1.text_input("보기 이름", value=pick if pick != "(새로 만들기)" else "", placeholder="예: 1종 강도 4재령")
    if s2.button("저장", type="primary", disabled=not vname.strip(), width="stretch"):
        state = {k: ss.get(k) for k in STATE_KEYS if k in ss}
        if state.get("cv_range"):
            state["cv_range"] = [str(x) for x in state["cv_range"]]
        CH.save_view({"name": vname.strip(), "state": state})
        st.success(f"‘{vname.strip()}’ 보기를 저장했습니다. 위 ‘저장된 보기’에서 불러올 수 있습니다.")
