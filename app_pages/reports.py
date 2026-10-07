"""보고서: 경영진 보고 PPT · 데이터 엑셀."""

from datetime import datetime

import pandas as pd
import streamlit as st

from qms.diagnosis import diagnose
from qms.reports import build_excel_report, build_management_ppt, kpi_summary
from qms.ui import get_ctx, sidebar

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store
period = store.period()
st.title("📑 보고서")
if period is None:
    st.info("데이터가 없습니다.")
    st.stop()

st.markdown("""
**경영진 보고 PPT** (16:9, 편집 가능한 PowerPoint 차트)
1. 표지 · 2. 핵심 요약(KPI·주요 사항) · 3. 28일 강도 추이(실측+예측) · 4. 공정 핵심 지표(f-CaO·분말도)
5. 주요 이상 발생·조치 현황 · 6. 상위 이상 원인 분석(5단계 요약) · 7. 공정능력 · 8. 후속 조치 계획

**데이터 엑셀**: 요약 KPI · 공정능력 · 알림 목록 · 원인 진단 · 기간 원 데이터(시트별)
""")
c1, c2 = st.columns([1.5, 1])
rng = c1.date_input("보고 기간", value=(max(period[0].date(), (period[1] - pd.Timedelta(days=30)).date()), period[1].date()),
                    min_value=period[0].date(), max_value=period[1].date())
org = c2.text_input("작성 부서", "품질관리팀")
if not isinstance(rng, (list, tuple)) or len(rng) != 2:
    st.stop()
start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(hours=23, minutes=59)

edf = ctx.events_df()
edf = edf[(edf["end"] >= start) & (edf["start"] <= end)] if len(edf) else edf
ev_ids = set(edf["event_id"]) if len(edf) else set()
events = [e for e in ctx.events if e.event_id in ev_ids]

st.subheader("미리보기 — 요약 KPI")
kpi = kpi_summary(store, reg, edf, start, end)
st.dataframe(pd.DataFrame([{"구분": k, "값": str(v[0]), "설명": v[1]} for k, v in kpi.items()]), hide_index=True)


@st.cache_data(show_spinner="보고서를 만드는 중…", max_entries=4)
def _build(kind: str, start, end, org: str, cache_key: tuple):
    dxs = [diagnose(e, store, reg, ctx.settings) for e in events if e.severity in ("위험", "경고")]
    if kind == "ppt":
        return build_management_ppt(store, reg, edf, dxs, start, end, org=org)
    return build_excel_report(store, reg, edf, dxs, start, end)


key = (len(ctx.events), str(store.period()), len(edf))
b1, b2 = st.columns(2)
stamp = datetime.now().strftime("%Y%m%d")
with b1:
    st.download_button("⬇️ 경영진 보고 PPT", _build("ppt", start, end, org, key),
                       file_name=f"품질관리현황보고_{start:%Y%m%d}_{end:%Y%m%d}.pptx",
                       mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                       type="primary", width="stretch")
with b2:
    st.download_button("⬇️ 데이터 엑셀", _build("xlsx", start, end, org, key),
                       file_name=f"품질데이터_{start:%Y%m%d}_{end:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
st.caption("개별 이상 건의 상세 보고서(5단계 분석 PPT)는 🧪 원인 진단·솔루션 화면에서 만들 수 있습니다. "
           "보고서의 원인 판정은 데이터 기반 1차 판단이며, 회의에서 현장 확인 결과로 확정하십시오.")
