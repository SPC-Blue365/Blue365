"""원인 진단 · 솔루션: 5단계 분석 프레임(① 현상 ~ ⑤ KS 평가)."""

import io

import pandas as pd
import streamlit as st

from qms.alerts import SEVERITY_ICON, SEVERITY_ORDER
from qms.diagnosis import VERDICT_ICON, VERDICT_LEGEND, diagnose, diagnosis_markdown
from qms.knowledge import AXIS_ICON
from qms.reports import build_issue_ppt
from qms.store import load_alert_status
from qms.ui import fmt, get_ctx, sidebar, trend_figure

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store
st.title("🧪 원인 진단 · 솔루션")
st.caption("① 현상 정의·정량화 → ② 원인 가설 5축 우선순위 → ③ 확인 방법 → ④ 단기 조치 vs 근본 대책 → ⑤ KS·관리기준 평가")

if not ctx.events:
    st.info("분석할 이상 이벤트가 없습니다.")
    st.stop()

only_major = st.toggle("위험·경고만 보기", value=True)
events = sorted([e for e in ctx.events if not only_major or e.severity != "주의"],
                key=lambda e: (e.end, SEVERITY_ORDER[e.severity]), reverse=True)
sel_id = st.session_state.get("selected_event_id")
if sel_id and all(e.event_id != sel_id for e in events):
    ev = ctx.event(sel_id)
    if ev:
        events = [ev] + events
ids = [e.event_id for e in events]
idx = ids.index(sel_id) if sel_id in ids else 0
labels = {e.event_id: f"{SEVERITY_ICON[e.severity]} {e.end:%m/%d} · " + (f"[{e.product}] " if e.product else "")
          + f"{e.item_name} — {e.rule_desc}" for e in events}
choice = st.selectbox("분석할 이벤트", ids, index=idx, format_func=lambda i: labels[i])
st.session_state["selected_event_id"] = choice
e = ctx.event(choice)
dx = diagnose(e, store, reg, ctx.settings)
q = dx.quant
item = reg[e.item_key]
status = load_alert_status()
srow = status[status["event_id"] == e.event_id]

head = st.container(border=True)
with head:
    st.markdown(f"## {SEVERITY_ICON[e.severity]} {dx.phenomenon.title}" + (f" [{e.product}]" if e.product else ""))
    st.markdown(f"**영향:** {dx.phenomenon.impact}")
    if len(srow):
        st.caption(f"처리 상태: {srow.iloc[0]['status']} · 담당: {srow.iloc[0]['assignee'] or '-'} · 메모: {srow.iloc[0]['note'] or '-'}")

# ① 현상
st.subheader("① 현상 정의와 정량화")
c1, c2 = st.columns([2.2, 1])
with c1:
    fig = trend_figure(ctx, e.item_key, e.product, start=e.start - pd.Timedelta(days=7),
                       end=e.end + pd.Timedelta(days=3), height=340)
    if fig:
        fig.add_vrect(x0=e.start, x1=e.end if e.end > e.start else e.start + pd.Timedelta(hours=2),
                      line=dict(width=1.5, color="#d03b3b"), fillcolor="rgba(0,0,0,0)",
                      annotation_text="분석 대상 구간", annotation_position="top left")
        st.plotly_chart(fig, key="dx_fig")
with c2:
    nd = q["decimals"]
    st.metric("구간 평균", fmt(q["mean"], nd, q["unit"]), delta=f"{q['delta']:+,.{nd}f} ({q['effect']:+.1f}σ) vs 직전 기준기간",
              delta_color="off")
    st.metric(f"{'최대' if e.direction == 'high' else '최소'}값", fmt(e.worst_value, nd, q["unit"]),
              delta=f"{q.get('limit_word', '기준')} {fmt(e.limit_value, nd)}", delta_color="off", delta_arrow="off")
    st.metric("이탈 점수 / 구간 점수", f"{q['n_exceed']} / {q['n']}")
st.info(q["text"], icon="📏")

# 종합 판단
top_sup = [r for r in dx.results if r.supported]
(st.success if top_sup else st.warning)(f"**종합 판단** — {dx.summary}", icon="🧭")

# ② 우선순위
st.subheader("② 원인 가설 우선순위 (화학 · 원료 · 공정 · 설비 · 시험오차)")
rank = pd.DataFrame([{
    "순위": i + 1, "축": f"{AXIS_ICON.get(r.hyp.axis, '')} {r.hyp.axis}", "원인 가설": r.hyp.title,
    "판정": f"{VERDICT_ICON.get(r.verdict, '')} {r.verdict}",
    "근거 점수": r.evidence_score if r.evidence_score is not None else None,
    "우선순위 점수": round(r.score, 2), "근거 수준": r.hyp.basis, "담당(제안)": r.hyp.owner,
} for i, r in enumerate(dx.results)])
st.dataframe(rank, hide_index=True, column_config={
    "근거 점수": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d",
                                             help="데이터 증거 강도(50=중립, 100=강한 지지, 0=강한 반증). 빈칸=데이터 없음"),
    "우선순위 점수": st.column_config.NumberColumn(help="사전가중치(경험상 빈도) × 데이터 근거로 계산한 순위 점수"),
})
st.caption("※ " + VERDICT_LEGEND)

# ③ 확인 방법
st.subheader("③ 가설별 근거 데이터와 확인 방법")
for i, r in enumerate(dx.results):
    with st.expander(f"{i + 1}. {AXIS_ICON.get(r.hyp.axis, '')} [{r.hyp.axis}] {r.hyp.title} — "
                     f"{VERDICT_ICON.get(r.verdict, '')} {r.verdict}", expanded=i < 2):
        st.markdown(f"**메커니즘** ({r.hyp.basis}): {r.hyp.mechanism}")
        if r.evidences:
            st.markdown("**데이터 근거(자동 평가)**")
            for ev in r.evidences:
                icon = {"지지": "✅", "약한 지지": "☑️", "변화 없음": "▫️", "반대 경향": "✖️", "데이터 없음": "❔"}.get(ev.status, "")
                st.markdown(f"- {icon} {ev.text} → **{ev.status}**")
        else:
            st.markdown("- ❔ 자동 평가할 측정 데이터가 없습니다 — 현장 확인으로 판단(추정 가설)")
        st.markdown("**추가 확인 방법(데이터·시험)**")
        for v in r.hyp.verify:
            st.markdown(f"- {v}")

# ④ 조치
st.subheader("④ 단기 조치 vs 근본 대책")
a, b = st.columns(2)
with a.container(border=True):
    st.markdown("**단기 조치** (확산 방지·수일 이내)")
    for act, tag in dx.short_term:
        st.markdown(f"- {act}  \n  <span style='color:gray;font-size:0.85em'>{tag}</span>", unsafe_allow_html=True)
with b.container(border=True):
    st.markdown("**근본 대책** (재발 방지·시스템 개선)")
    for act, tag in dx.root_cause:
        st.markdown(f"- {act}  \n  <span style='color:gray;font-size:0.85em'>{tag}</span>", unsafe_allow_html=True)

# ⑤ KS 평가
st.subheader("⑤ KS 규격 · 사내 관리기준 대비 평가")
st.dataframe(pd.DataFrame(dx.ks_eval), hide_index=True)
st.caption("KS 값: KS L 5201(한국시멘트협회·e나라표준인증 요약 기준) — 최신 개정 원문 대조 권장. 사내 기준은 ⚙️ 설정값.")

st.subheader("검증 계획표")
plan = dx.verification_plan()
st.dataframe(plan, hide_index=True)

# 내려받기
st.divider()
d1, d2, d3 = st.columns(3)
with d1:
    if st.button("📑 이상 분석 PPT 만들기", type="primary", width="stretch"):
        st.session_state["issue_ppt"] = (e.event_id, build_issue_ppt(dx, store, reg))
    if st.session_state.get("issue_ppt", (None,))[0] == e.event_id:
        st.download_button("⬇️ PPT 내려받기", st.session_state["issue_ppt"][1],
                           file_name=f"이상분석_{e.item_name}_{e.start:%Y%m%d}.pptx",
                           mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                           width="stretch")
with d2:
    st.download_button("📝 분석 내용 텍스트(회의록·메일용)", diagnosis_markdown(dx).encode("utf-8"),
                       file_name=f"이상분석_{e.item_name}_{e.start:%Y%m%d}.md", mime="text/markdown", width="stretch")
with d3:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        rank.to_excel(xw, sheet_name="원인우선순위", index=False)
        plan.to_excel(xw, sheet_name="검증계획", index=False)
        pd.DataFrame(dx.ks_eval).to_excel(xw, sheet_name="KS평가", index=False)
    st.download_button("📊 검증계획 엑셀", buf.getvalue(), file_name=f"검증계획_{e.item_name}_{e.start:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
