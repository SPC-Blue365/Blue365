"""출하시멘트 화면 공통: 업로드 패널(🚢 출하시멘트 화면과 📥 데이터 관리 화면이 함께 사용)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from . import shipment as S


def parsed_panel(content: bytes, filename: str, key: str = "ship_up") -> bool:
    """파일을 읽어 인식 결과를 보여 주고 저장 버튼을 제공한다. 저장했으면 True."""
    ov_key = f"{key}_ov"
    overrides = st.session_state.get(ov_key, {})
    p = S.parse_upload(content, filename, overrides)
    for e in p.errors:
        st.error(e)
    if p.errors or p.records.empty:
        return False
    st.success(f"출하시멘트(LIMS 일일 로트) 형식으로 인식했습니다 — 시트 ‘{p.sheet}’")
    for m in p.messages:
        st.write("•", m)
    rep = p.report
    # 열 이름으로 못 찾은 항목은 한 번 지정하면 기억한다
    if rep["missing"]:
        with st.expander(f"찾지 못한 항목 {len(rep['missing'])}개 — 파일의 어느 열인지 지정(선택)", expanded=False):
            used = set(rep["idx"].values())
            options = ["(없음)"] + [h for j, h in enumerate(rep["headers"]) if h and j not in used]
            picks = {}
            for k in rep["missing"]:
                picks[k] = st.selectbox(S.BY_KEY[k].name, options, key=f"{key}_pick_{k}")
            if st.button("선택한 열로 다시 읽기(다음부터 기억)", key=f"{key}_remap"):
                new = {k: v for k, v in picks.items() if v != "(없음)"}
                if new:
                    S.remember_header_map(new)
                    st.session_state[ov_key] = {**overrides, **new}
                    st.rerun()
    if rep["ship_unsure"]:
        with st.expander(f"비고를 확신하지 못한 {len(rep['ship_unsure'])}건(모선 수 분석에서 제외 표시)"):
            st.dataframe(pd.DataFrame(rep["ship_unsure"]).rename(columns={"date": "채취일", "raw": "비고 원문"}), hide_index=True)
    if rep["unknown_ships"]:
        st.caption("드물게 나온 선박명(오타 가능): " + ", ".join(f"{k}({v}건)" for k, v in rep["unknown_ships"].items()))
    with st.expander("미리보기(앞 30행)"):
        show = p.records.drop(columns=["extra"]).head(30)
        st.dataframe(show, hide_index=True)
    old = S.load_shipment_raw()
    if len(old) and "lot" in old:
        keys_old = set(S._key_series(old))
        keys_new = set(S._key_series(p.records))
        st.caption(f"저장된 자료 {len(old)}건과 비교: 새로 추가 {len(keys_new - keys_old)}건 · 갱신 {len(keys_new & keys_old)}건 "
                   "(같은 LOT는 새 값으로 갱신하되, 새 파일에서 비어 있는/0인 항목은 기존 값을 유지합니다)")
    if st.button("저장", type="primary", key=f"{key}_save"):
        r = S.save_shipment(p.records)
        st.session_state.pop(ov_key, None)
        st.success(f"저장 완료 — 새로 추가 {r['added']}건 · 갱신 {r['updated']}건 · 전체 {r['total']}건")
        st.rerun()
    return False
