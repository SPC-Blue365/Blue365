"""출하시멘트 모니터링(LIMS 일일 로트 표): 한눈에 판정 · 항목 상세 · 혼합재↔강도 · 연도별 관리기준 · 양하지 · 업로드."""

import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from qms import ship_dest as D
from qms import shipment as S
from qms.spc import capability
from qms.ui import colors, fmt, get_ctx, page_header
from qms.ui_ship import dest_panel, parsed_panel

ctx = get_ctx()
page_header(ctx, "🚢 출하시멘트 모니터링")


@st.cache_data(show_spinner=False)
def _load(mtime: float, dest_mtime: float) -> pd.DataFrame:
    """출하 기록 + 양하지 자동 연결(양하지 기록·기본값이 바뀌면 다시 계산)."""
    return D.attach_destinations(S.load_shipment())


def _excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, d in sheets.items():
            d.to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
df_all = _load(S.shipment_mtime(), D.dest_mtime())

if df_all.empty:
    st.info("저장된 출하시멘트 자료가 없습니다. LIMS 출하시멘트 엑셀(채취일·첨가재명칭·석회석비율·강도·비고 등)을 올리면 형식을 자동으로 인식합니다.", icon="📥")
    up = st.file_uploader("출하시멘트 엑셀·CSV", type=["xlsx", "xls", "csv"], key="ship_up_empty")
    if up is not None:
        parsed_panel(up.getvalue(), up.name, key="ship_up_empty_p")
    st.stop()

std = S.load_ship_standards()
c = colors()
first, last = df_all["date"].min(), df_all["date"].max()

# ── 공통 필터 ───────────────────────────────────────────────────────────
prods = [p for p in ["1종", "3종", "2종", "4종", "5종", "고로슬래그"] if p in set(df_all.get("product", []))]
prods += [p for p in sorted(set(df_all.get("product", []))) if p not in prods]
f0, f1, f2, f3, f4, f5 = st.columns([0.9, 1.3, 1, 1.2, 1.2, 1])
product = f0.selectbox("품종", ["전체", *prods], help="1종·3종 등 시멘트 품종. LIMS 품명(예: 1종시멘트 벌크)에서 자동 인식합니다.")
preset = f1.selectbox("기간", ["최근 90일", "최근 180일", "최근 1년", "전체", "직접 지정"], index=1)
if preset == "직접 지정":
    rng = f1.date_input("기간 지정", value=(max(first, last - pd.Timedelta(days=180)).date(), last.date()), min_value=first.date(),
                        max_value=last.date())
    start, end = (pd.Timestamp(rng[0]), pd.Timestamp(rng[1])) if isinstance(rng, (list, tuple)) and len(rng) == 2 else (first, last)
else:
    days = {"최근 90일": 90, "최근 180일": 180, "최근 1년": 365}.get(preset)
    start, end = (last - pd.Timedelta(days=days - 1) if days else first), last
adds = sorted(a for a in df_all["additive"].dropna().unique() if a)
additive = f2.selectbox("첨가재", ["전체", *adds])
mode = f3.selectbox("모선 수", ["전체", "1모선 단독 시험만", "2모선 이상(평균값)만"],
                    help="비고의 선박 수. 1모선 = 그 배만 단독 시험, 2모선 이상 = 그날 출항한 배들의 평균값(선박별로 나눠 추정하지 않습니다).")
kind = f4.selectbox("제품 구분", ["일반 제품만", "저염 포함 전체", "저염 제품만"],
                    help="비고에 ‘저염’이 표기된 날은 저염 제품 출하입니다. 일반 제품과 Cl 수준이 달라 기본은 분리해서 봅니다. "
                         "‘저염·일반 혼재’(저염 배와 일반 배가 같은 날 출항)는 ‘저염 포함 전체’에서만 보입니다.")
dcount = df_all["dest"].value_counts()
dest_opts = [d for d in dcount.index if d not in (D.MIXED, D.UNKNOWN, D.PARTIAL)] + [d for d in (D.MIXED, D.PARTIAL, D.UNKNOWN) if d in dcount]
dest = f5.selectbox("양하지", ["전체", *dest_opts], format_func=lambda d: d if d == "전체" else f"{d} ({dcount.get(d, 0)})",
                    help="선박별 양하지(운항 기록 → 비고 괄호 → 선박 기본값 순)로 자동 연결. 한 날짜에 양하지가 다른 배가 섞이면 ‘복수 양하지’.")
add_sel = None if additive == "전체" else additive
dest_sel = None if dest == "전체" else dest
df = S.apply_filters(df_all, start, end, add_sel, mode, kind, dest_sel, product=product)
n_prod = df_all["product"].value_counts().to_dict() if "product" in df_all else {}
n_kind = df_all["product_kind"].value_counts().to_dict()
st.caption(f"저장 자료 {len(df_all)}건 ({first:%Y-%m-%d} ~ {last:%Y-%m-%d}) → 현재 조건 **{len(df)}건**. "
           + ("품종: " + " · ".join(f"{k} {v}건" for k, v in n_prod.items()) + " · " if n_prod else "")
           + "제품 구분: " + " · ".join(f"{k} {v}건" for k, v in n_kind.items()))
if df.empty:
    st.warning("조건에 맞는 자료가 없습니다. 기간·제품 구분 조건을 바꿔 보세요.")
    st.stop()

tab1, tab2, tab3, tab4, tab6, tab5 = st.tabs(["📊 한눈에", "📈 항목 상세", "🧱 혼합재·강도", "🎯 관리기준(연도별)", "⚓ 양하지", "📥 업로드·데이터"])

# ── 1) 한눈에 ──────────────────────────────────────────────────────────
with tab1:
    sm = S.summary_table(df, std)
    lab = sm["판정"].str.split().str[-1] if len(sm) else pd.Series(dtype=str)
    cnt = lab.value_counts().to_dict()
    m = st.columns(5)
    m[0].metric("분석 건수", f"{len(df)}건", help=f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}")
    n_single = int(((df["n_ship"] == 1) & df["ship_ok"]).sum())
    m[1].metric("1모선 단독 시험", f"{n_single}건", delta=f"{n_single / len(df) * 100:.0f}%", delta_color="off")
    m[2].metric("🔴 KS 기준 이탈 항목", f"{cnt.get('위험', 0)}개")
    m[3].metric("🟠 사내 기준 이탈 항목", f"{cnt.get('경고', 0)}개")
    m[4].metric("🟡 관리한계(±3σ) 이탈 항목", f"{cnt.get('주의', 0)}개", delta=f"참고 {cnt.get('참고', 0)}개", delta_color="off")
    has_plant = any(e.get(f) is not None for y in std.get("years", {}).values() for e in y.values() for f in ("lsl", "usl"))
    if not has_plant:
        st.warning("사내 관리기준이 아직 입력되지 않아 KS 기준과 통계적 관리한계(±3σ)로만 판정 중입니다. "
                   "‘🎯 관리기준(연도별)’ 탭에서 공장 기준을 입력하세요(연도별로 따로 저장).", icon="🎯")
    st.caption("판정 기준(최근 10건): 🔴 KS 이탈(위험) → 🟠 사내 관리기준 이탈(경고) → 🟡 관리한계(평균±3σ) 이탈(주의) → "
               "🔵 중심선 한쪽 9점 연속(참고) → 🟢 정상. 관리한계는 선택한 조건의 평균±3×표준편차(기존 SPC 화면과 같은 방식)이며, "
               "KS·사내 기준은 **각 시험 채취일의 연도 기준**으로 적용합니다. 값 0(시험 전)은 ‘미시험’으로 제외했습니다.")
    show = sm.drop(columns=["그룹", "key"])
    num_cols = ["최근값", "평균", "표준편차", "최소", "최대", "KS 하한", "KS 상한", "사내 하한", "사내 상한", "목표"]
    disp = show.copy()
    for col in num_cols:                                   # 빈 기준은 ‘None’ 대신 ‘—’로 표시
        disp[col] = show[col].map(lambda v: "—" if pd.isna(v) else f"{v:,.2f}")
    disp["최근 채취일"] = show["최근 채취일"].map(lambda v: "—" if pd.isna(v) else f"{v:%Y-%m-%d}")
    st.dataframe(disp, hide_index=True, height=min(36 * (len(disp) + 1) + 4, 700),
                 column_config={"상태 설명": st.column_config.TextColumn(width="large")})
    st.download_button("⬇️ 판정표·원자료(엑셀)", _excel({"항목별 판정": show, "원자료(필터 적용)": df.drop(columns=["extra"], errors="ignore")}),
                       file_name=f"출하시멘트_판정_{df['date'].max():%Y%m%d}.xlsx", mime=XLSX)

# ── 2) 항목 상세 ───────────────────────────────────────────────────────
with tab2:
    core = [it for it in S.ITEMS if it.key in df.columns and df[it.key].notna().any()]
    extras = [e for e in S.extra_columns(df) if df[e].notna().any()]
    opts = [it.key for it in core] + extras
    labels = {it.key: it.name + (f" ({it.unit})" if it.unit else "") for it in core}
    labels.update({e: e[2:] + " (기타 항목)" for e in extras})
    d1, d2 = st.columns([2, 1])
    key = d1.selectbox("항목", opts, index=opts.index("s28") if "s28" in opts else 0, format_func=lambda k: labels[k])
    view = d2.segmented_control("보기", ["추이", "관리도", "분포", "월별"], default="추이") or "추이"
    item = S.BY_KEY.get(key)
    dec = item.dec if item else 2
    unit = item.unit if item else ""
    j = S.judge_item(df, key, std)
    s = j.series
    if len(s) == 0:
        st.info("이 조건에서는 값이 없습니다(시험 전 0은 제외).")
    else:
        sub = df[df[key].notna()].sort_values("date").reset_index(drop=True)
        cur = j.limits.iloc[-1]
        cap = capability(s, cur["lsl"] if pd.notna(cur["lsl"]) else (cur["ks_min"] if pd.notna(cur["ks_min"]) else None),
                         cur["usl"] if pd.notna(cur["usl"]) else (cur["ks_max"] if pd.notna(cur["ks_max"]) else None))
        mm = st.columns(5)
        mm[0].metric("최근값", fmt(float(s.iloc[-1]), dec, unit), help=f"{s.index[-1]:%Y-%m-%d}")
        mm[1].metric("평균", fmt(float(s.mean()), dec, unit))
        mm[2].metric("표준편차", fmt(float(s.std(ddof=1)), dec + 1))
        mm[3].metric("KS·사내 기준 이탈", f"{int(j.ks_out.sum())} · {int(j.plant_out.sum())}건")
        mm[4].metric("Cpk(사내 기준, 없으면 KS)", fmt(cap["Cpk"], 2) if np.isfinite(cap["Cpk"]) else "-",
                     help="기준이 없으면 '-'. 군내변동(MR/1.128) 기준. 1.33 이상 충분")
        st.caption(f"상태: {S.STATUS_ICON[j.status]} {j.label} · 기준선은 각 채취일의 연도 기준(연도가 바뀌면 계단식으로 바뀜)")
        fig = go.Figure()
        x = s.index
        if view in ("추이", "관리도"):
            single = ((sub["n_ship"] == 1) & sub["ship_ok"]).to_numpy()
            pal = [c["series"], "#e08a1e", "#7b5bd6", "#2a9d8f"]
            anames = sorted(sub["additive"].fillna("").unique())
            fig.add_trace(go.Scatter(x=x, y=s.values, mode="lines", line=dict(color=c["zone"], width=1), hoverinfo="skip", showlegend=False))
            for ai, a in enumerate(anames):
                for lab_, mask_sym in (("단독", ("circle", single)), ("복수 평균", ("diamond", ~single))):
                    sym, mk = mask_sym
                    sel = ((sub["additive"].fillna("") == a).to_numpy()) & mk
                    if not sel.any():
                        continue
                    hov = [f"{r.date:%Y-%m-%d} · {getattr(r, key):,.{dec}f}<br>{r.additive} 석회석 {r.ls}% / 첨가재 {r.addr}%<br>"
                           f"{r.ships or '선박 미기재'} ({'단독' if (r.n_ship == 1 and r.ship_ok) else f'{r.n_ship}모선 평균'})"
                           for r in sub[sel].itertuples()]
                    fig.add_trace(go.Scatter(x=x[sel], y=s.values[sel], mode="markers", name=f"{a or '첨가재 미표기'} · {lab_}",
                                             marker=dict(color=pal[ai % len(pal)], size=6, symbol=sym), text=hov, hovertemplate="%{text}<extra></extra>"))
            if view == "추이":
                ma = s.rolling(30, min_periods=5).mean()
                fig.add_trace(go.Scatter(x=x, y=ma.values, mode="lines", name="30건 이동평균", line=dict(color="#0f172a", width=2), hoverinfo="skip"))
                bad = j.ks_out.to_numpy() | j.plant_out.to_numpy()
                if bad.any():
                    fig.add_trace(go.Scatter(x=x[bad], y=s.values[bad], mode="markers", name="기준 이탈", marker=dict(color=c["violation"], size=11, symbol="x"), hoverinfo="skip"))
            else:
                if j.stats:
                    for yv, nm, col, dash in ((j.stats.center, "CL", c["cl"], "solid"), (j.stats.ucl, "UCL(+3σ)", "#e08a1e", "dash"), (j.stats.lcl, "LCL(−3σ)", "#e08a1e", "dash")):
                        fig.add_hline(y=yv, line=dict(color=col, width=1.4, dash=dash), annotation_text=f"{nm} {yv:,.{dec + 1}f}", annotation_position="top left", annotation_font=dict(size=11, color=c["muted"]))
                    r1, r2 = j.r1, j.r2
                    if r1.any():
                        fig.add_trace(go.Scatter(x=x[r1], y=s.values[r1], mode="markers", name="±3σ 이탈", marker=dict(color=c["violation"], size=10, symbol="circle-open", line=dict(width=2)), hoverinfo="skip"))
                    if r2.any():
                        fig.add_trace(go.Scatter(x=x[r2 & ~r1], y=s.values[r2 & ~r1], mode="markers", name="9점 연속 치우침", marker=dict(color="#e08a1e", size=9, symbol="circle-open", line=dict(width=2)), hoverinfo="skip"))
            for f, nm, col, dash in (("ks_max", "KS 상한", c["ks"], "solid"), ("ks_min", "KS 하한", c["ks"], "solid"), ("usl", "사내 상한", c["spec"], "dash"),
                                     ("lsl", "사내 하한", c["spec"], "dash"), ("target", "목표", c["target"], "dot")):
                if j.limits[f].notna().any():
                    fig.add_trace(go.Scatter(x=x, y=j.limits[f].values, mode="lines", name=nm, line=dict(color=col, width=1.6, dash=dash, shape="hv"), hoverinfo="skip"))
            fig.update_layout(xaxis=dict(type="date"))
        elif view == "분포":
            fig.add_trace(go.Histogram(x=s.values, marker_color=c["series"], nbinsx=30, name="건수"))
            for f, nm, col in (("ks_max", "KS 상한", c["ks"]), ("ks_min", "KS 하한", c["ks"]), ("usl", "사내 상한", c["spec"]), ("lsl", "사내 하한", c["spec"]), ("target", "목표", c["target"])):
                if pd.notna(cur[f]):
                    fig.add_vline(x=float(cur[f]), line=dict(color=col, width=1.5, dash="dash"), annotation_text=nm, annotation_position="top")
            fig.add_vline(x=float(s.mean()), line=dict(color=c["cl"], width=1.5), annotation_text="평균", annotation_position="bottom")
            fig.update_layout(bargap=0.05, yaxis_title="건수")
        else:
            g = s.groupby(s.index.to_period("M"))
            mon = pd.DataFrame({"평균": g.mean(), "표준편차": g.std(ddof=1), "건수": g.size()})
            mon.index = mon.index.astype(str)
            fig.add_trace(go.Bar(x=mon.index, y=mon["평균"], error_y=dict(type="data", array=mon["표준편차"].fillna(0).values, color=c["muted"]), marker_color=c["series"],
                                 text=[f"n={n}" for n in mon["건수"]], hovertemplate="%{x} 평균 %{y:,.2f} (%{text})<extra></extra>", name="월 평균"))
            lo, hi = float(mon["평균"].min()), float(mon["평균"].max())
            pad = (hi - lo) * 0.6 or 1
            fig.update_layout(yaxis=dict(range=[lo - pad, hi + pad]), xaxis=dict(type="category"))
            st.caption("막대 = 월 평균, 선 = ±1 표준편차(월 내 변동). 세로축은 평균 근처로 확대했습니다.")
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10), hovermode="closest", yaxis_title=(unit or None) if view != "분포" else "건수",
                          legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0))
        st.plotly_chart(fig, key="ship_detail_fig")
        if view == "추이":
            st.caption("● 단독 시험(1모선) · ◆ 복수 모선 평균 · 색 = 첨가재 · ✕ KS/사내 기준 이탈. 선박별로 값을 나눠 추정하지 않습니다.")
        flagged = (j.ks_out | j.plant_out).to_numpy() | j.r1
        if flagged.any():
            with st.expander(f"기준·관리한계 이탈 {int(flagged.sum())}건 목록"):
                tb = sub[flagged][["date", "additive", "ls", "addr", key, "n_ship", "ships", "product_kind"]].copy()
                tb["사유"] = ["KS 이탈" if a else ("사내 기준 이탈" if b else "관리한계(±3σ) 이탈") for a, b in zip(j.ks_out.to_numpy()[flagged], j.plant_out.to_numpy()[flagged])]
                st.dataframe(tb.rename(columns={"date": "채취일", "additive": "첨가재", "ls": "석회석(%)", "addr": "첨가재(%)", "n_ship": "모선 수", "ships": "선박", "product_kind": "제품 구분", key: labels[key]}),
                             hide_index=True)
        if key == "cl":
            cmp_ = S.apply_filters(df_all, start, end, add_sel, mode, "저염 포함 전체", dest_sel)
            cmp_ = cmp_[cmp_["cl"].notna()].groupby("product_kind")["cl"].agg(["size", "mean", "min", "max"]).rename(
                columns={"size": "건수", "mean": "평균(ppm)", "min": "최소", "max": "최대"})
            st.markdown("**제품 구분별 Cl(XRF)** — 저염 제품은 일반 제품과 분리해서 관리합니다.")
            st.dataframe(cmp_.round(0), column_config={"평균(ppm)": st.column_config.NumberColumn(format="%.0f")})

# ── 3) 혼합재·강도 ─────────────────────────────────────────────────────
with tab3:
    st.info(S.MIX_KNOWLEDGE, icon="🧱")
    use_all = st.checkbox("전체 기간 사용(권장: 배합이 여러 번 바뀐 전체 이력으로 비교)", value=True)
    dm = S.apply_filters(df_all, None if use_all else start, None if use_all else end, add_sel, mode, kind, dest_sel)
    dm = dm[dm["mix_total"].notna()]
    if len(dm) < 10:
        st.warning("비교에 필요한 자료가 부족합니다.")
    else:
        age = st.segmented_control("강도 재령", ["s1", "s3", "s7", "s28"], default="s28", format_func=lambda k: S.BY_KEY[k].name) or "s28"
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.32, 0.68], vertical_spacing=0.04)
        fig.add_trace(go.Scatter(x=dm["date"], y=dm["mix_total"], mode="lines", line=dict(color=c["spec"], width=2, shape="hv"), name="혼합재 합계(%)",
                                 hovertemplate="%{x|%Y-%m-%d} 혼합재 %{y}%<extra></extra>"), row=1, col=1)
        ds = dm[dm[age].notna()]
        fig.add_trace(go.Scatter(x=ds["date"], y=ds[age], mode="markers", marker=dict(color=c["series"], size=5), name=S.BY_KEY[age].name,
                                 hovertemplate="%{x|%Y-%m-%d} %{y:.1f} MPa<extra></extra>"), row=2, col=1)
        fig.add_trace(go.Scatter(x=ds["date"], y=ds[age].rolling(20, min_periods=5).mean(), mode="lines", line=dict(color="#0f172a", width=2), name="20건 이동평균", hoverinfo="skip"), row=2, col=1)
        fig.update_yaxes(title_text="혼합재(%)", row=1, col=1)
        fig.update_yaxes(title_text="MPa", row=2, col=1)
        fig.update_layout(height=480, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0))
        st.plotly_chart(fig, key="ship_mix_fig")
        st.caption("혼합재 합계 = 석회석 비율 + 첨가재 비율. 위: 혼합재 투입 설정 이력, 아래: 강도. 혼합재가 줄어든 구간에서 강도가 어떻게 움직였는지 확인하세요.")

        st.markdown("##### 혼합재 변경 시점 전·후 비교 (변경 전 20건 vs 후 20건 평균, 5건 이상 유지된 구간만)")
        ch = S.mix_changes(dm)
        if ch.empty:
            st.caption("배합 변경 이력이 충분하지 않습니다.")
        else:
            st.dataframe(ch, hide_index=True, column_config={"변경일": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                                                           **{col: st.column_config.NumberColumn(format="%+.2f") for col in ch.columns if col.endswith("(MPa)")},
                                                           "변화(%p)": st.column_config.NumberColumn(format="%+.1f")})
            n_ok = int(ch["28일 강도 방향(경험칙 대비)"].str.startswith("✔").sum())
            st.caption(f"28일 강도가 경험칙(혼합재↓ → 강도↑)과 같은 방향으로 움직인 변경 {n_ok}/{len(ch)}회. 전·후 비교는 같은 기간의 클링커 품질·분말도 변화가 섞여 있어 "
                       "단독 원인으로 단정할 수 없습니다(추정).")

        st.markdown("##### 배합(첨가재·석회석·첨가재 비율) 조합별 평균")
        ct = S.composition_table(dm)
        st.dataframe(ct, hide_index=True, column_config={"시작": st.column_config.DatetimeColumn(format="YYYY-MM-DD"), "종료": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                                                         **{col: st.column_config.NumberColumn(format="%.2f") for col in ct.columns if col.startswith(("압축", "Blaine", "SO"))}})

        st.markdown("##### 혼합재 1%p 변화당 강도 변화(통계 추정)")
        rows = []
        for k in S.STRENGTH_KEYS:
            e1 = S.mix_effect(dm, k)
            e2 = S.mix_effect(dm, k, split=True)
            if not e1 or not e2:
                continue
            rows.append({"재령": S.BY_KEY[k].name, "혼합재 합계 +1%p": e1["mix_coef"], "±(95%)": 1.96 * e1["mix_se"],
                         "석회석 +1%p": e2["coef"]["석회석 비율(%p당)"], "±(95%) ": 1.96 * e2["se"]["석회석 비율(%p당)"],
                         "첨가재 +1%p": e2["coef"]["첨가재 비율(%p당)"], "±(95%)  ": 1.96 * e2["se"]["첨가재 비율(%p당)"], "건수": e1["n"], "설명력(R²)": e1["r2"]})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={col: st.column_config.NumberColumn(format="%+.2f") for col in
                                                                          ["혼합재 합계 +1%p", "석회석 +1%p", "첨가재 +1%p"]} | {"설명력(R²)": st.column_config.NumberColumn(format="%.2f"),
                                                                                                                 "±(95%)": st.column_config.NumberColumn(format="%.2f"), "±(95%) ": st.column_config.NumberColumn(format="%.2f"),
                                                                                                                 "±(95%)  ": st.column_config.NumberColumn(format="%.2f")})
            st.caption("단위 MPa. 첨가재 종류(플라이 애시/고로슬래그)·Blaine 분말도·SO₃를 함께 보정한 최소제곱 추정이며 **인과 증명이 아니라 추정**입니다(클링커 품질·시험 오차는 보정 못 함). "
                       "혼합재가 늘면 보통 강도가 내려가고, 석회석은 초기(1일)에 충전재 효과로 오히려 올릴 수 있습니다(경험칙).")

# ── 4) 관리기준(연도별) ────────────────────────────────────────────────
with tab4:
    st.markdown("공장 **사내 관리기준**을 연도별로 직접 입력하세요. KS 기준은 참고값으로 미리 들어 있으며 이 표에서 고칠 수도 있습니다. "
                "채취일의 연도에 해당하는 기준으로 판정하므로, 연도가 바뀌어도 지난 자료는 그 해 기준으로 평가됩니다.")
    st.caption(f"KS 참고값 출처: {S.KS_REF}. 사내 기준은 비워 두면 ‘기준 없음’입니다.")
    saved_years = sorted(int(y) for y in std.get("years", {}))
    data_years = sorted(int(y) for y in df_all["date"].dt.year.unique())
    y1, y2 = st.columns([1, 3])
    year = int(y1.number_input("적용 연도", min_value=2000, max_value=2100, value=int(last.year), step=1))
    y2.caption("저장된 연도: " + (", ".join(map(str, saved_years)) if saved_years else "없음") + " · 자료가 있는 연도: " + ", ".join(map(str, data_years))
               + " · 저장하지 않은 연도는 직전 연도 기준을 승계합니다.")
    table = S.year_table(std, year)
    ed = st.data_editor(
        table, hide_index=True, key=f"ship_std_{year}_{len(saved_years)}", disabled=["key", "항목", "단위", "출처"], height=min(36 * (len(table) + 1) + 4, 700),
        column_config={"key": None, **{col: st.column_config.NumberColumn(format="%g") for col in ["KS 하한", "KS 상한", "사내 하한", "사내 상한", "목표"]},
                       "비고(변경 사유 등)": st.column_config.TextColumn(width="medium")})
    b1, b2 = st.columns(2)
    if b1.button(f"{year}년 기준 저장", type="primary"):
        S.save_year(std, year, ed)
        st.success(f"{year}년 관리기준을 저장했습니다. 판정이 새 기준으로 다시 계산됩니다.")
        st.rerun()
    if str(year) in std.get("years", {}) and b2.button(f"{year}년 입력 삭제(직전 연도 승계로 복귀)"):
        std["years"].pop(str(year), None)
        S.save_ship_standards(std)
        st.rerun()
    if saved_years:
        st.markdown("##### 연도별 사내 관리기준 변경 이력")
        hist = []
        for it in S.ITEMS:
            row = {"항목": it.name}
            for y in saved_years:
                e = std["years"][str(y)].get(it.key) or {}
                lo, hi, tg = e.get("lsl"), e.get("usl"), e.get("target")
                row[str(y)] = " ~ ".join(x for x in (f"≥{lo:g}" if lo is not None else "", f"≤{hi:g}" if hi is not None else "") if x) + (f" (목표 {tg:g})" if tg is not None else "") or "-"
            hist.append(row)
        hd = pd.DataFrame(hist)
        st.dataframe(hd, hide_index=True)
        st.download_button("⬇️ 연도별 관리기준(엑셀)", _excel({"연도별 사내기준": hd}), file_name="출하시멘트_연도별_관리기준.xlsx", mime=XLSX)

# ── 6) 양하지 ──────────────────────────────────────────────────────────
with tab6:
    st.markdown("각 출하 기록의 **선박마다 양하지를 자동으로 연결**합니다. 우선순위: ① 운항(양하지) 기록 파일(같은 날짜, 없으면 앞뒤 1일) "
                "→ ② LIMS 비고의 괄호 주석(예: 리나호(부산)) → ③ 선박 기본 양하지. 기록·기본값을 바꾸면 **저장된 모든 출하 기록에 바로 다시 연결**되고, "
                "새로 올리는 LIMS 파일도 자동으로 연결됩니다. 값을 추정하지 않으며, 한 날짜에 양하지가 다른 배가 섞이면 ‘복수 양하지’로 둡니다.")
    cv = D.coverage(S.apply_filters(df_all, start, end, add_sel, mode, kind))
    m = st.columns(4)
    m[0].metric("양하지 확정 건수", f"{cv['single']}건", delta=f"{cv['single'] / max(cv['n'], 1) * 100:.0f}%", delta_color="off",
                help="그날 출항한 배들의 양하지가 하나로 정해진 날(1모선 포함)")
    m[1].metric("복수 양하지", f"{cv['mixed']}건", help="양하지가 다른 배가 같은 날 출항 — 평균값이라 양하지별로 나누지 않음")
    m[2].metric("미상·일부 미상", f"{cv['unknown'] + cv['partial']}건", help="운항 기록·비고·기본값 어디에도 양하지가 없는 선박이 있는 날")
    m[3].metric("운항 기록으로 연결", f"{cv['by_src']['운항기록']}건", help="운항(양하지) 기록 파일에서 찾은 날")
    st.caption("연결 출처: " + " · ".join(f"{k} {v}건" for k, v in cv["by_src"].items()) + " (한 날짜에 출처가 여러 개일 수 있음)")

    st.markdown("##### 양하지별 품질(양하지가 하나로 정해진 날만)")
    qkeys = [k for k in ("s1", "s3", "s7", "s28", "blaine", "r45", "so3", "cl", "loi", "mgo") if k in df_all]
    dq = D.dest_quality(S.apply_filters(df_all, start, end, add_sel, mode, kind), qkeys)
    if dq.empty:
        st.info("아직 양하지가 확정된 출하 기록이 없습니다. 아래에서 운항(양하지) 기록을 올리거나 선박 기본 양하지를 입력하세요.")
    else:
        st.dataframe(dq.round(2), hide_index=True)
        st.caption("단순 평균(추정·분해 없음). 양하지별 차이는 같은 시기의 배합·클링커 품질 차이와 섞여 있을 수 있으니 원인으로 단정하지 마세요.")

    st.markdown("##### ① 운항(양하지) 기록 올리기")
    st.caption("열 이름을 자동 인식합니다: 일자(출항일·선적일·일자) · 선박(선박명·모선·본선) · 양하지(양하지·양하항·도착항·하역지). "
               "일자 열이 없는 표는 ‘선박 기본 양하지’로 저장합니다. 같은 날짜·선박은 새 값으로 갱신합니다.")
    upd = st.file_uploader("운항(양하지) 기록 엑셀·CSV", type=["xlsx", "xls", "csv"], key="dest_up")
    if upd is not None:
        dest_panel(upd.getvalue(), upd.name, key="dest_up_p", known=set(D.ship_table(df_all)["ship"]))
    voy = D.load_voyages()
    if len(voy):
        with st.expander(f"저장된 운항 기록 {len(voy)}건 ({voy['date'].min():%Y-%m-%d} ~ {voy['date'].max():%Y-%m-%d})"):
            st.dataframe(voy.rename(columns={"date": "일자", "ship": "선박", "dest": "양하지", "source": "파일", "updated_at": "저장"}), hide_index=True,
                         column_config={"일자": st.column_config.DatetimeColumn(format="YYYY-MM-DD")})
            if st.checkbox("운항 기록을 모두 지웁니다", key="voy_clear_ok") and st.button("운항 기록 삭제"):
                D.clear_voyages()
                st.cache_data.clear()
                st.rerun()

    st.markdown("##### ② 선박 기본 양하지(늘 같은 곳으로 가는 배)")
    st.caption("운항 기록이 없는 날에 쓰입니다. ‘비고에 적힌 양하지’는 LIMS 비고 괄호에서 찾은 횟수이며, 버튼으로 빈 칸에 추천값을 채울 수 있습니다(저장 전 확인).")
    stb = D.ship_table(df_all)
    stb = stb[(stb["출하 건수"] >= 3) | (stb["dest"] != "")].reset_index(drop=True)
    if st.session_state.pop("_dest_fill", False):
        stb["dest"] = [d or r for d, r in zip(stb["dest"], stb["추천"])]
    ed = st.data_editor(stb, hide_index=True, key=f"dest_master_{D.dest_mtime()}", disabled=["ship", "출하 건수", "비고에 적힌 양하지", "추천"],
                        column_config={"ship": st.column_config.TextColumn("선박"), "dest": st.column_config.TextColumn("기본 양하지", help="예: 부산, 평택"),
                                       "note": st.column_config.TextColumn("메모")}, height=min(36 * (len(stb) + 1) + 4, 560))
    b1, b2 = st.columns(2)
    if b1.button("기본 양하지 저장", type="primary"):
        n = D.save_master(ed[["ship", "dest", "note"]])
        st.cache_data.clear()
        st.success(f"{n}척의 기본 양하지를 저장했습니다. 모든 출하 기록에 다시 연결됩니다.")
        st.rerun()
    if b2.button("빈 칸에 비고 추천값 채우기(저장 전 확인)"):
        st.session_state["_dest_fill"] = True
        st.rerun()
    left = S.apply_filters(df_all, start, end, add_sel, mode, kind)
    left = left[left["dest"].isin([D.UNKNOWN, D.PARTIAL])]
    if len(left):
        with st.expander(f"양하지를 못 정한 출하 기록 {len(left)}건(현재 기간)"):
            st.dataframe(left[["date", "ships", "dest_detail", "ship_raw"]].rename(columns={"date": "채취일", "ships": "선박", "dest_detail": "선박별 양하지", "ship_raw": "비고 원문"}),
                         hide_index=True, column_config={"채취일": st.column_config.DatetimeColumn(format="YYYY-MM-DD")})

# ── 5) 업로드·데이터 ───────────────────────────────────────────────────
with tab5:
    st.markdown("LIMS에서 내보낸 **출하시멘트 엑셀을 그대로** 올리세요. 열 이름으로 형식을 자동 인식합니다. 같은 LOT는 갱신하고 새 날짜는 추가합니다.")
    up = st.file_uploader("출하시멘트 엑셀·CSV", type=["xlsx", "xls", "csv"], key="ship_up_main")
    if up is not None:
        parsed_panel(up.getvalue(), up.name, key="ship_up_main_p")
    st.divider()
    st.markdown(f"**저장 현황**: {len(df_all)}건, {first:%Y-%m-%d} ~ {last:%Y-%m-%d}")
    st.caption("양하지는 ‘⚓ 양하지’ 탭에서 운항 기록·기본값으로 자동 연결됩니다. 선박별 값 추정은 하지 않습니다.")
    raw = df_all.drop(columns=["extra", "ship_hints"], errors="ignore")
    st.download_button("⬇️ 저장된 전체 자료(엑셀)", _excel({"출하시멘트": raw}), file_name="출하시멘트_저장자료.xlsx", mime=XLSX)
    ok = st.checkbox("저장된 출하시멘트 자료를 모두 삭제합니다(되돌릴 수 없음). 연도별 관리기준은 유지됩니다.")
    if st.button("출하시멘트 자료 삭제", disabled=not ok):
        S.clear_shipment()
        st.cache_data.clear()
        st.rerun()
