"""운영 모니터링 대시보드 (Streamlit) [ML-Engineer / Synthesis-Agent].

실행:
    streamlit run streamlit_app.py

라인별 야드 CaO 실시간 상태·경보·예측을 운영자에게 보여준다.
data/raw/ 의 최신 데이터를 읽어 확정 모델(Ridge)로 예측·경보한다(로컬 전용).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from config import schema as S
from src.models.dataset import all_lines, load_sources, build_line_data
from src.monitoring import monitor_line
from src.monitoring.alerts import AlertConfig, Level
from src.visualization import figures as V

st.set_page_config(page_title="석회석 야드 CaO 모니터", page_icon="⛏️", layout="wide")

BADGE = {Level.GREEN: ("🟢", "정상", "#2ca02c"),
         Level.YELLOW: ("🟡", "주의", "#f0a500"),
         Level.RED: ("🔴", "경고", "#d62728")}


@st.cache_data(show_spinner="데이터 로딩·매칭 중…")
def _load():
    _, osp_exp, yards = load_sources()
    return {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}


st.title("⛏️ 석회석 광산-야드 CaO 운영 모니터")
st.caption(f"목표 CaO {S.TARGET.cao_mean}±{S.TARGET.tol}% · 라인별 예측·경보 · 로컬 전용")

# --- 사이드바: 경보 임계 설정 ---
st.sidebar.header("⚙️ 경보 설정")
lo = st.sidebar.number_input("규격 하한", value=float(S.TARGET.lower), step=0.1)
hi = st.sidebar.number_input("규격 상한", value=float(S.TARGET.upper), step=0.1)
sustain = st.sidebar.slider("연속 이탈 경고(시간)", 1, 12, 3)
dev = st.sidebar.slider("모델 편차 주의(%p)", 0.3, 3.0, 1.0, 0.1)
if st.sidebar.button("🔄 새 데이터로 새로고침"):
    st.cache_data.clear()
    st.rerun()
cfg = AlertConfig(lo=lo, hi=hi, sustain_hours=sustain, deviation_warn=dev)

try:
    lines = _load()
except FileNotFoundError:
    st.error("data/raw/ 에 데이터가 없습니다. 엑셀을 배치한 뒤 새로고침하세요.")
    st.stop()

statuses = {ln: monitor_line(ld, cfg) for ln, ld in lines.items()}

# --- 상단 상태 요약 ---
cols = st.columns(len(statuses))
for col, (ln, stt) in zip(cols, statuses.items()):
    icon, label, color = BADGE[stt.level]
    col.metric(f"{icon} {ln} → {stt.alias}", f"{stt.latest_actual:.2f}%",
               f"예측 {stt.latest_pred:.2f} · MAE {stt.recent_mae:.2f}")
    col.markdown(f"<span style='color:{color};font-weight:700'>{label}</span> · 경보 {len(stt.alerts)}건",
                 unsafe_allow_html=True)

st.divider()

# --- 라인별 상세 ---
for ln, stt in statuses.items():
    icon, label, color = BADGE[stt.level]
    st.subheader(f"{icon} {ln} 라인 → {stt.alias}  ·  {label}")
    if stt.alerts:
        for a in stt.alerts:
            _, _, c = BADGE[a.level]
            st.markdown(f"- <b style='color:{c}'>[{a.level.label}]</b> {a.message}", unsafe_allow_html=True)
    else:
        st.success("경보 없음 — 정상 범위")
    s = stt.series
    oos = ((s["pred"] < V.TARGET - 0.5) | (s["pred"] > V.TARGET + 0.5)).values
    fig = V.prediction_timeseries(s["datetime"], s["actual"].values, s["pred"].values, oos,
                                  f"최근 {stt.n_monitored}시간 · 실측 vs 예측")
    st.plotly_chart(fig, use_container_width=True)

st.caption("※ 데이터·모델은 로컬 전용입니다. 새 데이터가 들어오면 사이드바 '새로고침'을 누르세요.")
