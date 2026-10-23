"""원료·부원료·석고·고령토 인수검사: 합부 현황 · 검사종류별 · 불합격 목록 · 거래처별 · 최근 목록 · 업로드."""

import json

import pandas as pd
import streamlit as st

from qms import incoming as I
from qms.ui import get_ctx, page_header

ctx = get_ctx()
page_header(ctx, "📦 원료 인수검사", "원료·부원료·석고·고령토 인수검사 결과 — LIMS 인수검사 파일을 올리거나 지정 폴더에 넣으면 자동 반영됩니다.")

df = I.load_incoming()

if df.empty:
    st.info("아직 인수검사 데이터가 없습니다. 아래에서 LIMS 인수검사 엑셀(원료·석고·고령토)을 올리거나, "
            "📥 데이터 관리 · 지정 폴더에 넣으면 자동으로 반영됩니다.")
else:
    s = I.summary(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 검사", f"{s['total']:,}건", border=True)
    c2.metric("합격", f"{s['pass']:,}건", border=True)
    c3.metric("불합격", f"{s['fail']:,}건", delta=None if not s["fail"] else "확인 필요",
              delta_color="inverse", border=True)
    c4.metric("불합격률", f"{s['fail_rate']}%", border=True)
    judged = s["pass"] + s["fail"]
    if judged < s["total"]:
        st.caption(f"※ 합부판정이 비어 있는 {s['total'] - judged}건은 집계에서 '판정없음'으로 둡니다(LIMS에 판정 미입력).")

    k = s["by_kind"].copy()
    k["합격"] = k["건수"] - k["불합격"]
    st.markdown("##### 검사종류별 현황")
    st.dataframe(k[["검사종류", "건수", "합격", "불합격"]], hide_index=True, width="stretch")

    if not s["fails"].empty:
        st.markdown("##### ⚠️ 불합격 내역")
        fails = s["fails"].copy()
        fails["채취일"] = pd.to_datetime(fails["채취일"]).dt.strftime("%Y-%m-%d")
        st.dataframe(fails, hide_index=True, width="stretch")

    st.markdown("##### 최근 검사 기록")
    kinds = ["(전체)"] + sorted(df["검사종류"].dropna().unique().tolist())
    pick = st.selectbox("검사종류", kinds, key="inc_kind")
    view = df if pick == "(전체)" else df[df["검사종류"] == pick]
    view = view.sort_values("채취일", ascending=False).head(300).copy()
    view["채취일"] = pd.to_datetime(view["채취일"]).dt.strftime("%Y-%m-%d")
    show = view[["채취일", "검사종류", "거래처", "품명", "합부판정", "비고"]]
    st.dataframe(show, hide_index=True, width="stretch")

    with st.expander("성분값 상세 보기(행 선택)"):
        if len(view):
            opts = {f"{r['채취일']} · {r['검사종류']} · {r['품명'][:24]}": i for i, (_, r) in enumerate(view.iterrows())}
            sel = st.selectbox("기록 선택", list(opts), key="inc_detail")
            rec = view.iloc[opts[sel]]
            try:
                comp = json.loads(rec["성분"]) if rec["성분"] else {}
            except (json.JSONDecodeError, TypeError):
                comp = {}
            if comp:
                st.dataframe(pd.DataFrame([{"항목": k2, "값": v2} for k2, v2 in comp.items()]),
                             hide_index=True, width="stretch")
            else:
                st.caption("성분값이 없습니다.")

    xl = df.sort_values("채취일").drop(columns=["성분"]).copy()
    xl["채취일"] = pd.to_datetime(xl["채취일"]).dt.strftime("%Y-%m-%d")
    st.download_button("⬇️ 인수검사 전체 내려받기(CSV)", xl.to_csv(index=False).encode("utf-8-sig"),
                       file_name="인수검사_전체.csv", mime="text/csv")

st.divider()
with st.expander("📤 인수검사 파일 올리기", expanded=df.empty):
    up = st.file_uploader("LIMS 인수검사 엑셀(원료·석고·고령토)", type=["xlsx", "xls"], key="inc_up")
    if up is not None:
        p = I.parse_incoming(up.getvalue(), up.name)
        for m in p.messages:
            st.write("•", m)
        for e in p.errors:
            st.error(e)
        if not p.rows.empty:
            st.dataframe(p.rows.drop(columns=["성분"]).head(50), hide_index=True, width="stretch")
            if st.button("저장", type="primary", key="inc_save"):
                n = I.save_incoming(p.rows)
                st.success(f"저장 완료 — 누계 {n}행.")
                st.rerun()
    if not df.empty and st.button("🗑 인수검사 데이터 전체 삭제", key="inc_clear"):
        I.clear_incoming()
        st.rerun()
