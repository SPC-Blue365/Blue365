"""보고서: 경영진 보고 PPT · 데이터 엑셀."""

from datetime import datetime

import pandas as pd
import streamlit as st

from qms.alerts import SEVERITY_ORDER
from qms.diagnosis import diagnose
from qms.reports import build_excel_report, build_management_ppt, kpi_summary
from qms.ui import get_ctx, page_header

ctx = get_ctx()
reg, store = ctx.registry, ctx.store
period = store.period()
page_header(ctx, "📑 보고서")
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


def _top_events(evs, n: int = 20):
    """보고서에 넣을 원인 분석 대상: 위험 → 경고 순·최근 순, 같은 항목(품종·호기)은 1건만 — 자료가 많아도 빠르게."""
    seen, out = set(), []
    for e in sorted((e for e in evs if e.severity in ("위험", "경고")),
                    key=lambda e: (SEVERITY_ORDER[e.severity], e.rule == "KS", e.end), reverse=True):
        k = (e.item_key, e.product, e.line)
        if k not in seen:
            seen.add(k)
            out.append(e)
        if len(out) >= n:
            break
    return out


@st.cache_data(show_spinner="보고서를 만드는 중…", max_entries=4)
def _build(kind: str, start, end, org: str, cache_key: tuple):
    dxs = [diagnose(e, store, reg, ctx.settings) for e in _top_events(events)]
    if kind == "ppt":
        return build_management_ppt(store, reg, edf, dxs, start, end, org=org)
    return build_excel_report(store, reg, edf, dxs, start, end)


key = (len(ctx.events), str(store.period()), len(edf))
b1, b2 = st.columns(2)
stamp = datetime.now().strftime("%Y%m%d")


def _safe(kind: str):
    """보고서 생성이 실패해도 화면 전체가 멈추지 않게 — 원인을 보여 주고 나머지 기능은 계속 쓸 수 있게 한다."""
    try:
        return _build(kind, start, end, org, key), None
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인 표시
        import traceback
        return None, (f"{type(exc).__name__}: {exc}", traceback.format_exc())


for col, kind, label, fname, mime, primary in (
        (b1, "ppt", "⬇️ 경영진 보고 PPT", f"품질관리현황보고_{start:%Y%m%d}_{end:%Y%m%d}.pptx",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation", True),
        (b2, "xlsx", "⬇️ 데이터 엑셀", f"품질데이터_{start:%Y%m%d}_{end:%Y%m%d}.xlsx",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False)):
    with col:
        data, err = _safe(kind)
        if data is not None:
            st.download_button(label, data, file_name=fname, mime=mime, type="primary" if primary else "secondary",
                               width="stretch")
        else:
            st.error(f"{label.split()[-1]} 생성 실패 — {err[0][:300]}  \n보고 기간을 바꿔 보거나, 아래 원문을 캡처해 보내 주세요.")
            with st.expander("오류 원문(개발 확인용)"):
                st.code(err[1][-3000:])
st.divider()
st.subheader("👀 보는용 현황판 (공유용 · 조회 전용)")
st.markdown("경영진·다른 부서·현장이 **설치 없이 더블클릭으로 보는** 한 파일짜리 현황판입니다(인터넷 불필요). "
            "**종합 현황 · 공정 모니터링(호기·밀별) · 강도 예측(재령·품종) · 원인 진단 · 출하시멘트 · 데이터 현황** 6개 탭.  \n"
            "매일 자동반영을 등록해 두면 06:00에 앱 폴더의 `현황판\\Blue365_현황_최신.html` 이 새로 만들어지고, "
            "`현황판\\기록` 에 날짜별로 30일치가 보관됩니다. 공유 드라이브 접근 권한이 있는 사람은 이 파일을 열면 됩니다.  \n"
            "이 앱(관리용)은 자료 올리기·관리기준 입력·보고서 만들기 등 **관리 업무**에 씁니다.")
h1, h2 = st.columns(2)
if h1.button("👀 지금 보는용 현황판 만들기", width="stretch"):
    from qms.viewer import build_viewer
    with st.spinner("현황판을 만드는 중…(10~30초)"):
        try:
            st.session_state["snap_html"] = build_viewer(ctx).encode("utf-8")
            st.session_state["snap_err"] = None
        except Exception as exc:  # noqa: BLE001
            st.session_state["snap_html"], st.session_state["snap_err"] = None, f"{type(exc).__name__}: {exc}"
if st.session_state.get("snap_err"):
    h2.error("현황판 생성 실패 — " + st.session_state["snap_err"][:300])
if st.session_state.get("snap_html"):
    h2.download_button("⬇️ 보는용 현황판 내려받기(.html)", st.session_state["snap_html"], type="primary", width="stretch",
                       file_name=f"Blue365_현황_{datetime.now():%Y%m%d_%H%M}.html", mime="text/html")

st.caption("개별 이상 건의 상세 보고서(5단계 분석 PPT)는 🧪 원인 진단·솔루션 화면에서 만들 수 있습니다. "
           "보고서의 원인 판정은 데이터 기반 1차 판단이며, 회의에서 현장 확인 결과로 확정하십시오.")
