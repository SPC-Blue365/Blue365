"""AI(LLM) 솔루션 패널 — 계산 결과 JSON을 근거로 Claude가 보고서를 작성(스트리밍)."""

from __future__ import annotations

import hashlib

import streamlit as st

from .llm import (
    KINDS,
    MODELS,
    ReportStream,
    ai_ready,
    context_json,
    estimate_call_cost,
    load_llm_config,
)
from .ui import md_escape


def ai_panel(kind: str, context: dict, key: str, title: str | None = None) -> None:
    cfg = load_llm_config()
    ok, msg = ai_ready(cfg)
    with st.container(border=True):
        st.markdown(f"#### 🤖 AI 솔루션 보고서 — {title or KINDS.get(kind, kind)}")
        st.caption("숫자는 시스템 계산·지식베이스가 만들고, AI(Claude)는 그 결과만 근거로 해설·조치 계획을 씁니다. "
                   "결과는 [사실]/[추정]/[경험칙]으로 구분 표기되며, 최종 판단은 담당자가 합니다.")
        payload = context_json(context)
        with st.expander("AI에 전달되는 데이터 보기(외부 전송 범위)"):
            st.caption("계산 결과 요약만 전송합니다(원 데이터 DB·개인정보 제외). 사내 보안 승인 후 사용하세요.")
            st.code(payload, language="json")
        if not ok:
            st.info(msg + " 위의 '규칙 기반 솔루션'은 AI 없이도 항상 제공됩니다.", icon="ℹ️")
            return
        q = st.text_area("추가 요청(선택)", key=f"{key}_q", height=70,
                         placeholder="예: 경영진 보고용으로 원가 영향 중심으로 정리해줘 / 단기 조치를 3개 이내로")
        est = estimate_call_cost(cfg.model)
        c1, c2 = st.columns([1, 3])
        run = c1.button("AI 보고서 생성", key=f"{key}_run", type="primary")
        c2.caption(f"모델 {MODELS[cfg.model]['label']} · 노력 {cfg.effort} · 예상 비용 약 ${est:.3f}"
                   f"(≈ {est * cfg.usd_krw:,.0f}원)/회 — 추정")
        sig = hashlib.sha256((payload + q + cfg.model).encode("utf-8")).hexdigest()[:12]
        state_key = f"ai_res_{key}"
        if run:
            rs = ReportStream(kind, context, cfg, question=q)
            st.write_stream(md_escape(chunk) for chunk in rs)
            st.session_state[state_key] = (sig, rs.result)
        saved = st.session_state.get(state_key)
        if not saved:
            return
        s_sig, res = saved
        if not run and res is not None and res.text:
            if s_sig != sig:
                st.caption("⚠️ 아래 보고서는 이전 입력 기준입니다. 입력이 바뀌었으면 다시 생성하세요.")
            st.markdown(md_escape(res.text))
        if res is not None:
            u = res.usage
            st.caption(f"모델 {res.model}{' (대체 모델)' if res.fallback_used else ''} · 입력 {u.get('input_tokens', 0):,} · "
                       f"캐시 읽기 {u.get('cache_read_input_tokens', 0):,} · 출력 {u.get('output_tokens', 0):,} 토큰 · "
                       f"비용 ${res.cost_usd:.4f}(≈ {res.cost_usd * cfg.usd_krw:,.0f}원) · 종료 사유 {res.stop_reason}")
            if res.text:
                st.download_button("⬇️ AI 보고서(마크다운)", res.text.encode("utf-8"), file_name=f"AI_{kind}_보고서.md",
                                   mime="text/markdown", key=f"{key}_dl")
