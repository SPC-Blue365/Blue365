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
from src.models.dataset import build_line_data, filter_period, load_sources, load_yard_change
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
    return mine, osp_exp, yards, yc


st.title("⛏️ 석회석 광산-야드 CaO 운영 모니터")
st.caption(f"목표 CaO {S.TARGET.cao_mean}±{S.TARGET.tol}% · 라인별 예측·경보·추적 · 로컬 전용")

try:
    mine, osp_exp, yards_full, yc_full = _load()
except FileNotFoundError:
    st.error("data/raw/ 에 데이터가 없습니다. 엑셀을 배치한 뒤 새로고침하세요.")
    st.stop()

# ── 사이드바: 기간 설정 (데이터가 늘어도 선택 구간만 표현) ──
st.sidebar.header("📅 기간 설정")
_alldt = pd.concat([yc_full["datetime"]] + [y["datetime"] for y in yards_full.values()])
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
mine_p = filter_period(mine, start, end, "date")          # 광산도 동일 기간
osp_p = filter_period(osp_exp, start, end, "datetime")    # OSP 인출도 동일 기간
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
    st.plotly_chart(V.build_tracking_sankey(mine_p, osp_p, yards), use_container_width=True)

# ── ③ 관리도 (제어차트) ──
with tab3:
    st.markdown("규격밴드 + 통계 관리한계(평균±3σ) + 규격이탈점. **KPI = 규격내 시간 비율**.")
    for ln, stt in statuses.items():
        s = stt.series
        act = s["actual"].values
        fin = act[np.isfinite(act)]
        c1, c2 = st.columns([1, 4])
        if not len(fin):
            c1.metric(f"{ln} 규격내 비율", "-")
            c1.caption(f"{stt.alias}\n데이터 없음")
            c2.info("선택한 기간에 이 라인의 측정 데이터가 없습니다.")
            continue
        in_spec = float(np.mean((fin >= lo) & (fin <= hi)) * 100)
        c1.metric(f"{ln} 규격내 비율", f"{in_spec:.0f}%")
        c1.caption(f"{stt.alias}\n최근 {stt.n_monitored}h")
        c2.plotly_chart(V.control_chart(s["datetime"], act, lo, hi, f"{ln} → {stt.alias} 관리도"),
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
