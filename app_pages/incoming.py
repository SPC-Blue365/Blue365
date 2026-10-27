"""원료·부원료·석고·고령토 인수검사: 합부 현황 · 사내 기준 설정·자동판정 · 불합격 목록 · 최근 목록 · 업로드."""

import json

import pandas as pd
import streamlit as st

from qms import incoming as I
from qms.ui import get_ctx, page_header

ctx = get_ctx()
page_header(ctx, "📦 원료 인수검사", "원료·부원료·석고·고령토 인수검사 결과 — LIMS 인수검사 파일을 올리거나 지정 폴더에 넣으면 자동 반영됩니다.")

raw = I.load_incoming()

if raw.empty:
    st.info("아직 인수검사 데이터가 없습니다. 아래에서 LIMS 인수검사 엑셀(원료·석고·고령토)을 올리거나, "
            "📥 데이터 관리 · 지정 폴더에 넣으면 자동으로 반영됩니다.")
else:
    df = I.judge_frame(raw)
    final = df["최종판정"]
    total = len(df)
    npass = int((final == I.PASS).sum())
    nfail = int((final == I.FAIL).sum())
    nhold = total - npass - nfail
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 검사", f"{total:,}건", border=True)
    c2.metric("합격", f"{npass:,}건", border=True)
    c3.metric("불합격", f"{nfail:,}건", delta=None if not nfail else "확인 필요", delta_color="inverse", border=True)
    c4.metric("불합격률", f"{round(100 * nfail / total, 1) if total else 0.0}%", border=True)
    cap = "판정 기준: LIMS 합부판정 우선, 비어 있으면 아래 '사내 기준'으로 자동판정."
    if nhold:
        cap += f" · 아직 판정없음 {nhold}건(해당 품목 기준 미설정)."
    st.caption(cap)

    with st.expander("⚙️ 사내 인수검사 기준 설정 (원료·부원료 자동 합부판정)", expanded=(npass + nfail == 0)):
        st.markdown("품목별로 항목과 **최소/최대 허용값**을 넣으면, LIMS 합부판정이 비어 있는 건을 자동으로 합/불 판정합니다.  \n"
                    "· **대상**: 품명에 이 글자가 들어간 검사에만 적용(예: `규석`, `슬래그`). 비워 두면 모든 품목에 적용.  \n"
                    f"· **항목**: {', '.join(I.JUDGE_ITEMS)} 중 선택.  · **최소/최대**: 한쪽만 넣어도 됩니다(예: SiO2 최소 88).")
        cur = I.load_standards()
        base = pd.DataFrame(cur) if cur else pd.DataFrame(columns=["대상", "항목", "min", "max"])
        for col in ("대상", "항목", "min", "max"):
            if col not in base.columns:
                base[col] = None
        edited = st.data_editor(
            base[["대상", "항목", "min", "max"]], num_rows="dynamic", hide_index=True, width="stretch",
            column_config={
                "대상": st.column_config.TextColumn("대상(품명 포함어)", help="예: 규석 / 슬래그 / 플라이애시. 비우면 전체"),
                "항목": st.column_config.SelectboxColumn("항목", options=I.JUDGE_ITEMS, required=True),
                "min": st.column_config.NumberColumn("최소 허용", help="이 값보다 낮으면 불합격"),
                "max": st.column_config.NumberColumn("최대 허용", help="이 값보다 높으면 불합격")},
            key="inc_std_editor")
        if st.button("💾 기준 저장·적용", type="primary", key="inc_std_save"):
            I.save_standards(edited.to_dict("records"))
            st.success("기준을 저장했습니다. 자동 합부판정에 바로 반영됩니다.")
            st.rerun()
        if cur:
            st.caption("현재 기준: " + " · ".join(
                f"[{r.get('대상') or '전체'}] {r['항목']} "
                + (f"{r.get('min')}~" if r.get('min') is not None else "~")
                + (f"{r.get('max')}" if r.get('max') is not None else "") for r in cur))

    kk = (df.assign(불합격=(final == I.FAIL).astype(int), 합격=(final == I.PASS).astype(int))
          .groupby("검사종류").agg(건수=("최종판정", "size"), 합격=("합격", "sum"), 불합격=("불합격", "sum")).reset_index())
    st.markdown("##### 검사종류별 현황")
    st.dataframe(kk, hide_index=True, width="stretch")

    fails = df[final == I.FAIL][["채취일", "검사종류", "거래처", "품명", "판정사유", "비고"]].sort_values("채취일", ascending=False)
    if not fails.empty:
        st.markdown("##### ⚠️ 불합격 내역")
        fv = fails.copy()
        fv["채취일"] = pd.to_datetime(fv["채취일"]).dt.strftime("%Y-%m-%d")
        st.dataframe(fv, hide_index=True, width="stretch")

    st.markdown("##### 최근 검사 기록")
    kinds = ["(전체)"] + sorted(df["검사종류"].dropna().unique().tolist())
    pick = st.selectbox("검사종류", kinds, key="inc_kind")
    view = (df if pick == "(전체)" else df[df["검사종류"] == pick]).sort_values("채취일", ascending=False).head(300).copy()
    view["채취일"] = pd.to_datetime(view["채취일"]).dt.strftime("%Y-%m-%d")
    st.dataframe(view[["채취일", "검사종류", "거래처", "품명", "최종판정", "판정사유", "비고"]], hide_index=True, width="stretch")

    with st.expander("성분값 상세 보기(행 선택)"):
        if len(view):
            opts = {f"{r['채취일']} · {r['검사종류']} · {str(r['품명'])[:24]}": i for i, (_, r) in enumerate(view.iterrows())}
            sel = st.selectbox("기록 선택", list(opts), key="inc_detail")
            rec = view.iloc[opts[sel]]
            try:
                comp = json.loads(rec["성분"]) if rec["성분"] else {}
            except (json.JSONDecodeError, TypeError):
                comp = {}
            if comp:
                st.dataframe(pd.DataFrame([{"항목": k2, "값": "" if v2 is None else str(v2)} for k2, v2 in comp.items()]), hide_index=True, width="stretch")
            else:
                st.caption("성분값이 없습니다.")

    xl = df.sort_values("채취일")[["채취일", "검사종류", "거래처", "품명", "합부판정", "자동판정", "최종판정", "판정사유", "비고"]].copy()
    xl["채취일"] = pd.to_datetime(xl["채취일"]).dt.strftime("%Y-%m-%d")
    st.download_button("⬇️ 인수검사 전체 내려받기(CSV)", xl.to_csv(index=False).encode("utf-8-sig"),
                       file_name="인수검사_전체.csv", mime="text/csv")

st.divider()
with st.expander("📤 인수검사 파일 올리기", expanded=raw.empty):
    up = st.file_uploader("LIMS 인수검사 엑셀(원료·석고·고령토)", type=["xlsx", "xls"], key="inc_up")
    if up is not None:
        p = I.parse_incoming(up.getvalue(), up.name)
        for m in p.messages:
            st.write("•", m)
        for e in p.errors:
            st.error(e)
        if not p.rows.empty:
            st.dataframe(p.rows.drop(columns=["성분"]).head(50), hide_index=True, width="stretch")
            if st.button("✅ 인수검사 적용(저장)", type="primary", key="inc_save"):
                n = I.save_incoming(p.rows)
                st.success(f"저장 완료 — 누계 {n}행.")
                st.rerun()
    if not raw.empty and st.button("🗑 인수검사 데이터 전체 삭제", key="inc_clear"):
        I.clear_incoming()
        st.rerun()
