"""운영 모니터링 대시보드 (Streamlit) [ML-Engineer / Synthesis-Agent].

실행: streamlit run streamlit_app.py

탭: ① 실시간 모니터 ② 추적 흐름(Sankey) ③ 관리도(제어차트) ④ 경보 이력
data/raw/ 최신 데이터를 확정 모델(Ridge)로 예측·경보(로컬 전용).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import streamlit as st

from config import schema as S
from src.matching.segments import LAG_CAUTION, segment_warnings, yard_change_segments
from src.models.dataset import (
    build_line_data, calibrate_flow, filter_period, load_osp_stock, load_sources,
    load_yard_change, stock_vs_flow,
)
from src.monitoring import load_history, log_statuses, monitor_all
from src.monitoring.alerts import AlertConfig, Level
from src.visualization import figures as V

st.set_page_config(page_title="석회석 야드 CaO 모니터", page_icon="⛏️", layout="wide")

BADGE = {Level.GREEN: ("🟢", "정상", "#2ca02c"),
         Level.YELLOW: ("🟡", "주의", "#f0a500"),
         Level.RED: ("🔴", "경고", "#d62728")}


@st.cache_data(show_spinner="데이터 로딩·매칭 중…")
def _load():
    mine, osp_exp, yards = load_sources()
    yc = load_yard_change()
    stock = load_osp_stock()
    return mine, osp_exp, yards, yc, stock


st.title("⛏️ 석회석 광산-야드 CaO 운영 모니터")
st.caption(f"목표 CaO {S.TARGET.cao_mean}±{S.TARGET.tol}% · 라인별 예측·경보·추적 · 로컬 전용")

try:
    mine, osp_exp, yards_full, yc_full, stock_full = _load()
except FileNotFoundError:
    st.error("data/raw/ 에 데이터가 없습니다. 엑셀을 배치한 뒤 새로고침하세요.")
    st.stop()

# ── 사이드바: 기간 설정 (데이터가 늘어도 선택 구간만 표현) ──
st.sidebar.header("📅 기간 설정")
# ⭐️ 기본 기간은 Sankey 가 쓰는 모든 소스를 덮어야 한다. 야드/야드변경만으로 잡으면
#    그보다 먼저 시작하는 OSP(신설 06/01) 물량이 '전체'에서 빠진다(6,000톤 누락 버그).
_alldt = pd.concat(
    [yc_full["datetime"]] + [y["datetime"] for y in yards_full.values()]
    + [pd.to_datetime(osp_exp["datetime"]), pd.to_datetime(mine["datetime"])]
)
dmin, dmax = pd.to_datetime(_alldt.min()).date(), pd.to_datetime(_alldt.max()).date()
rng = st.sidebar.date_input("분석 기간", value=(dmin, dmax), min_value=dmin, max_value=dmax)
start = pd.Timestamp(rng[0]) if isinstance(rng, (list, tuple)) and len(rng) >= 1 else pd.Timestamp(dmin)
end = pd.Timestamp(rng[1]) if isinstance(rng, (list, tuple)) and len(rng) >= 2 else pd.Timestamp(dmax)

st.sidebar.header("⚙️ 경보 설정")
lo = st.sidebar.number_input("규격 하한", value=float(S.TARGET.lower), step=0.1)
hi = st.sidebar.number_input("규격 상한", value=float(S.TARGET.upper), step=0.1)
sustain = st.sidebar.slider("연속 이탈 경고(시간)", 1, 12, 3)
dev = st.sidebar.slider("모델 편차 주의(%p)", 0.3, 3.0, 1.0, 0.1)
if st.sidebar.button("🔄 새 데이터로 새로고침"):
    st.cache_data.clear()
    st.rerun()
cfg = AlertConfig(lo=lo, hi=hi, sustain_hours=sustain, deviation_warn=dev)

# 기간 필터 적용 → 모든 차트가 선택 구간으로 재계산
yc = filter_period(yc_full, start, end, "datetime")
yards = {ln: filter_period(df, start, end, "datetime") for ln, df in yards_full.items()}
mine_p = filter_period(mine, start, end, "datetime")      # 광산도 동일 기간(교대 시각 기준)
osp_p = filter_period(osp_exp, start, end, "datetime")    # OSP 인출도 동일 기간
stock_p = filter_period(stock_full, start, end, "datetime")   # 실사 재고도 동일 기간
lines = {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}
st.caption(f"선택 기간: {start.date()} ~ {end.date()}  ·  야드변경 {len(yc)}건")

statuses = monitor_all(lines, cfg)
added = log_statuses(statuses)  # 경보 이력 누적(중복 제외)

tab1, tab2, tab3, tab4 = st.tabs(["📟 실시간 모니터", "🌊 추적 흐름", "📈 관리도", "📋 경보 이력"])

# ── ① 실시간 모니터 ──
with tab1:
    cols = st.columns(len(statuses))
    for col, (ln, stt) in zip(cols, statuses.items()):
        icon, label = stt.badge
        color = "#8a6d1a" if stt.is_stale else BADGE[stt.level][2]
        # 데이터 부족(가동 중지·짧은 기간)이면 nan 대신 '-' 로 정직하게 표시
        has = np.isfinite(stt.latest_actual)
        col.metric(f"{icon} {ln} → {stt.alias}", f"{stt.latest_actual:.2f}%" if has else "-",
                   f"예측 {stt.latest_pred:.2f} · MAE {stt.recent_mae:.2f}" if has else "데이터 없음")
        col.markdown(f"<span style='color:{color};font-weight:700'>{label}</span> · 경보 {len(stt.alerts)}건",
                     unsafe_allow_html=True)
        col.caption(f"📅 기준 {stt.as_of} ({stt.age_text})" + (f"\n\n⏸️ {stt.note}" if stt.note else ""))
    st.divider()
    for ln, stt in statuses.items():
        icon, label = stt.badge
        st.subheader(f"{icon} {ln} 라인 → {stt.alias} · {label}")
        st.caption(f"📅 데이터 기준 {stt.as_of} ({stt.age_text})" + (f" · ⏸️ {stt.note}" if stt.note else ""))
        if stt.is_stale:
            st.warning("이 라인은 최신 데이터가 없습니다 — 아래 상태·경보는 위 기준 시각의 값입니다.")
        if stt.alerts:
            for a in stt.alerts:
                _, _, c = BADGE[a.level]
                st.markdown(f"- <b style='color:{c}'>[{a.level.label}]</b> {a.message}", unsafe_allow_html=True)
        else:
            st.success("경보 없음 — 정상 범위")
        s = stt.series
        if len(s) == 0:
            st.info("선택한 기간에 이 라인의 측정 데이터가 없어 예측 그래프를 표시할 수 없습니다.")
        else:
            oos = ((s["pred"] < V.TARGET - 0.5) | (s["pred"] > V.TARGET + 0.5)).values
            st.plotly_chart(
                V.prediction_timeseries(s["datetime"], s["actual"].values, s["pred"].values, oos,
                                        f"최근 {stt.n_monitored}시간 · 실측 vs 예측"),
                use_container_width=True)

# ── ② 추적 흐름 (Sankey) ──
with tab2:
    # ⭐️ 야드변경 구간 선택 — 고르면 '그 라인 · 그 구간'만 남긴다.
    #    구간 정의는 src.matching.segments 정본 하나만 쓴다(리포트와 동일 규칙).
    segs = yard_change_segments(yc, mine_p, osp_p, yards)
    seg = None
    if segs:
        opts = {f"{g['label']} ({g['hours']}h)": g for g in segs}
        pick = st.selectbox("🔀 야드변경 구간 (선택하면 그 라인·구간만 표시)",
                            ["전체 기간 (누적)"] + list(opts))
        seg = opts.get(pick)

    if seg:
        # 시간 + 라인 양쪽으로 거른다 (데이터는 라인별로 구분되어 있다)
        ln_sel = seg["line"]
        yc = yc[(yc["line"] == ln_sel) & (yc["datetime"] >= seg["start"]) & (yc["datetime"] < seg["end"])]
        mine_p = filter_period(mine_p[mine_p["line"] == ln_sel], seg["start"], seg["end"], "datetime")
        osp_p = filter_period(osp_p[osp_p["line"] == ln_sel], seg["start"], seg["end"], "datetime")
        yards = {ln: (filter_period(df, seg["start"], seg["end"], "datetime") if ln == ln_sel
                      else df.iloc[0:0])                    # 다른 라인은 비운다
                 for ln, df in yards.items()}
        st.info(
            f"**{seg['label']}** ({seg['hours']}시간) · **{ln_sel} 라인만** 표시 중\n\n"
            f"변경 시점 품위 CaO {seg['cao'] if seg['cao'] is not None else '-'}% · "
            f"MgO {seg['mgo'] if seg['mgo'] is not None else '-'}% · "
            f"이 구간 데이터: 광산 {seg['n_mine']}행 · OSP 인출 {seg['n_osp']}행 · 야드 측정 {seg['n_own']}건"
        )
        st.warning(f"⚠️ {LAG_CAUTION}")
        for w in segment_warnings(seg):
            st.error(f"⚠️ {w}")

    st.markdown("### 야드변경 기반 추적 (CaO/MgO)")
    st.markdown("라인별 **야드변경일자**에 실제 적재한 물량·품위 기준. 링크 두께=야드물량, "
                "**차트 상단 CaO/MgO 버튼**으로 성분 전환. 호버=상세.")
    if len(yc):
        st.plotly_chart(V.build_yardchange_sankey(yc, default="CaO"), use_container_width=True)
        st.plotly_chart(V.yardchange_trend(yc), use_container_width=True)
        st.markdown("#### 표준편차(변동성)")
        std_view = st.radio("기준", ["야드별(변경)", "라인별(변경)", "라인별(연속 CNA/45Q)"],
                            horizontal=True, label_visibility="collapsed")
        if std_view == "야드별(변경)":
            st.plotly_chart(V.yardchange_std_summary(yc, "yard"), use_container_width=True)
        elif std_view == "라인별(변경)":
            st.plotly_chart(V.yardchange_std_summary(yc, "line"), use_container_width=True)
        else:
            st.plotly_chart(V.continuous_std_summary(yards), use_container_width=True)
        with st.expander("변경일자별 상세 데이터"):
            st.dataframe(yc.assign(datetime=yc["datetime"].dt.strftime("%Y/%m/%d %H:%M"))
                         .rename(columns={"datetime": "변경일시", "line": "라인", "yard": "야드",
                                          "cao": "CaO", "mgo": "MgO", "tonnage": "야드물량"}),
                         use_container_width=True)
    else:
        st.info("야드변경 시트가 없습니다. (기존라인/신설라인 야드변경 시트를 추가하세요)")
    st.divider()
    st.markdown("### 물류 개요 (광산→OSP→야드) — 선택 기간 기준")
    st.caption(
        "⚠️ **좌우 물량 합은 일치하지 않는 것이 정상입니다.** 왼쪽은 광산에서 OSP로 **적재한 양**, "
        "오른쪽은 OSP에서 야드로 **인출한 양**으로 공정 단계가 다르며, 그 사이 OSP가 **재고(버퍼)** "
        "역할을 하므로 차이가 곧 재고 증감입니다.  \n"
        "ℹ️ 광산 물량은 **채굴 교대 시각**(1차 08~16 · 2차 16~24 · 3차 00~08의 중점)과 "
        "47Q의 **실측 시작·종료 시각**으로 시간축에 배치됩니다."
    )
    _bal = []
    for _ln in S.YARD_PAIR:
        _m = float(pd.to_numeric(mine_p.loc[mine_p["line"] == _ln, "tonnage"], errors="coerce").sum())
        _o = float(pd.to_numeric(osp_p.loc[osp_p["line"] == _ln, "withdrawn_ton"], errors="coerce").sum())
        if _m or _o:
            _bal.append(f"**{_ln}** 적재 {_m:,.0f}톤 · 인출 {_o:,.0f}톤 → 재고 {_m - _o:+,.0f}톤")
    if _bal:
        st.caption("이 기간 실제: " + "  /  ".join(_bal))
    st.plotly_chart(V.build_tracking_sankey(mine_p, osp_p, yards), use_container_width=True)

    st.markdown("### OSP 재고 증감 추이 (적재 − 인출 누적)")
    st.caption(
        "위 Sankey 의 좌우 차이가 **시간에 따라 어떻게 쌓였는지**. "
        "**선이 내려가면 쓴 양이 들어온 양보다 많아 재고가 줄고 있다는 뜻**이고, "
        "올라가면 재고가 늘고 있다는 뜻입니다. 0선은 선택 기간 시작 수준.  \n"
        "⚠️ **절대 재고량이 아닙니다** — 시작 시점의 재고가 데이터에 없어 **증감분만** 표시합니다. "
        "판단에는 **기울기**를 보십시오."
    )
    st.plotly_chart(V.inventory_trend(mine_p, osp_p), use_container_width=True)

    if len(stock_p):
        st.markdown("### OSP 실사 재고 — 실제 재고량 vs 흐름 계산")
        st.caption(
            "교대마다 직접 파악한 **실사 재고량(실선)**과, 광산 적재−인출만으로 계산한 "
            "**추정 재고(점선)**를 겹쳐 본 것입니다. **두 선이 벌어지면 광산 기록에 잡히지 않은 "
            "유입이 있다는 뜻**입니다.  \n"
            "ℹ️ 실사값은 **1,000톤 단위 개략치**이며 교대 중간(1차 12:30·2차 20:30·3차 04:30)에 파악합니다."
        )
        gaps = []
        for _ln in S.YARD_PAIR:
            r = stock_vs_flow(stock_p, mine_p, osp_p, _ln)
            if r:
                gaps.append(f"**{_ln}** 실사 {r['actual']:+,.0f}톤 vs 흐름 {r['calc']:+,.0f}톤 "
                            f"→ 격차 {r['gap']:+,.0f}톤({r['gap_per_day']:+,.0f}톤/일)")
        if gaps:
            st.warning("⚠️ 이 기간 실측 격차 — " + "  /  ".join(gaps)
                       + "  \n실사 재고가 흐름 계산보다 **덜 줄었습니다**. 원인 확인이 필요합니다.")
        calib = {_ln: calibrate_flow(stock_p, mine_p, osp_p, _ln) for _ln in S.YARD_PAIR}
        cparts = [f"**{_ln}** {c['method']}={c['coef']:.3f} "
                  f"(오차 {c['resid_std_raw']:,.0f}→{c['resid_std']:,.0f}톤, {c['improve']:.0f}% 개선)"
                  for _ln, c in calib.items() if c]
        if cparts:
            st.info("🔧 **실사에 맞춘 보정** — " + "  /  ".join(cparts)
                    + "  \n남은 오차의 하한은 육안 실사 자체의 흔들림입니다"
                      "(교대 간 표준편차 "
                    + "~".join(f"{c['noise_std']:,.0f}" for c in calib.values() if c) + "톤). "
                      "**운영상 '지금 재고'는 가장 최근 실사값을 쓰십시오.**")
        st.plotly_chart(V.stock_trend(stock_p, mine_p, osp_p, calibrations=calib),
                        use_container_width=True)

# ── ③ 관리도 (제어차트) ──
with tab3:
    st.markdown("규격밴드 + 통계 관리한계(평균±3σ) + 규격이탈점. **KPI = 규격내 시간 비율**.")
    st.caption("**선택 기간 전체**의 시간별 야드 실측 기준입니다 "
               "(실시간 모니터 탭의 '최근 감시창'과 달리 기간 전체를 봅니다).")
    for ln, stt in statuses.items():
        # ⭐️ 관리도는 선택 기간 전체의 시간별 야드 실측을 쓴다. 모니터의 series 는
        #    경보용 '최근 20% 감시창'이라 그걸 쓰면 x축이 최근 며칠만 나온다(실제 발생 버그).
        ys = lines[ln].yard_series
        cx, act = ys.index, ys.values
        fin = act[np.isfinite(act)]
        c1, c2 = st.columns([1, 4])
        if not len(fin):
            c1.metric(f"{ln} 규격내 비율", "-")
            c1.caption(f"{stt.alias}\n데이터 없음")
            c2.info("선택한 기간에 이 라인의 측정 데이터가 없습니다.")
            continue
        in_spec = float(np.mean((fin >= lo) & (fin <= hi)) * 100)
        c1.metric(f"{ln} 규격내 비율", f"{in_spec:.0f}%")
        c1.caption(f"{stt.alias}\n집계 {len(fin):,}시간")
        c2.plotly_chart(V.control_chart(cx, act, lo, hi,
                                        f"{ln} → {stt.alias} 관리도 (규격내 {in_spec:.0f}%)"),
                        use_container_width=True)

# ── ④ 경보 이력 ──
with tab4:
    hist = load_history()
    if added:
        st.info(f"이번 조회에서 신규 경보 {added}건을 이력에 기록했습니다.")
    if len(hist):
        st.plotly_chart(V.alert_history_timeline(hist), use_container_width=True)
        st.markdown("**최근 경보 (최신순)**")
        st.dataframe(hist.sort_values("run_time", ascending=False).head(200), use_container_width=True)
        st.download_button("이력 CSV 다운로드", hist.to_csv(index=False).encode("utf-8-sig"),
                           "alert_log.csv", "text/csv")
    else:
        st.success("기록된 경보 이력이 없습니다.")

st.caption("※ 데이터·모델·이력은 로컬 전용입니다. 새 데이터가 들어오면 사이드바 '새로고침'을 누르세요.")
