"""데이터 관리: 템플릿 · 업로드 · 데모 데이터 · 내보내기."""

import io
from datetime import date

import pandas as pd
import streamlit as st

from qms.demo import SCENARIOS, generate_demo_data, scenario_table
from qms.standards import TABLES
from qms.store import SHEET_NAMES, clear_db, load_raw, parse_upload, save_raw, template_workbook
from qms.ui import DEMO_FLAG, get_ctx, refresh, sidebar

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store
st.title("📥 데이터 관리")

st.subheader("데이터 현황")
rows = []
for name, meta in TABLES.items():
    df = store.tables.get(name, pd.DataFrame())
    rows.append({"구분": meta["label"], "측정 주기": meta["freq"], "품종 구분": "예" if meta["by_product"] else "-",
                 "행 수": len(df), "시작": df["timestamp"].min() if len(df) else None,
                 "종료": df["timestamp"].max() if len(df) else None})
st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
    "시작": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
    "종료": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
if ctx.demo:
    st.info("현재 데모 데이터입니다. 실제 데이터를 업로드하기 전에 아래 '전체 삭제'로 데모 데이터를 지우세요.", icon="🧪")

tab1, tab2, tab3, tab4 = st.tabs(["⬆️ 업로드", "📄 입력 템플릿", "🧪 데모 데이터", "⬇️ 내보내기·삭제"])
with tab1:
    st.markdown("엑셀(시트: 생료·킬른·클링커·시멘트·물성) 또는 CSV(파일명에 테이블명 포함, 예: `clinker_2026-10.csv`)를 올리세요. "
                "같은 측정일시(+품종)는 업로드 값으로 덮어씁니다.")
    up = st.file_uploader("파일 선택", type=["xlsx", "xls", "csv"])
    if up is not None:
        res = parse_upload(up.getvalue(), up.name)
        for m in res.messages:
            st.write("•", m)
        for e in res.errors:
            st.error(e)
        if res.tables:
            for name, df in res.tables.items():
                with st.expander(f"미리보기: {SHEET_NAMES[name]} ({len(df)}행)"):
                    st.dataframe(df.head(50), hide_index=True)
            replace_demo = st.checkbox("데모 데이터를 지우고 업로드 데이터만 사용", value=ctx.demo)
            if st.button("저장", type="primary"):
                if replace_demo:
                    clear_db()
                    DEMO_FLAG.unlink(missing_ok=True)
                counts = save_raw(res.tables, replace=False)
                refresh()
                st.success("저장 완료: " + ", ".join(f"{SHEET_NAMES[k]} {v}행" for k, v in counts.items()))
                st.rerun()

with tab2:
    st.markdown("항목 코드(열 이름)와 설명(2행)이 들어 있는 입력 양식입니다. 예시 5행이 포함되어 있습니다.")
    sample = {k: v.head(5) for k, v in load_raw().items()}
    st.download_button("⬇️ 데이터 입력 템플릿(엑셀)", template_workbook(reg, sample), file_name="QMS_데이터입력템플릿.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.markdown("**연계 방식(단계별 권장)**: ① 엑셀 업로드(현재) → ② LIMS·DCS 내보내기 파일을 폴더에 저장하면 "
                "`qms_monitor.py --import-dir` 가 주기적으로 자동 반영 → ③ DB/OPC-UA 직접 연계(차기 단계)")

with tab3:
    st.markdown("가상의 공장 데이터(생료→소성→클링커→분쇄→강도 인과관계 반영)와 이상 시나리오 6종을 생성합니다.")
    c1, c2, c3 = st.columns(3)
    days = c1.number_input("기간(일)", 30, 365, 120)
    end_d = c2.date_input("종료일", value=date.today())
    seed = c3.number_input("난수 시드", 0, 9999, 7)
    st.dataframe(scenario_table(pd.Timestamp(end_d) - pd.Timedelta(days=int(days) - 1)), hide_index=True)
    if int(days) < max(v["days"][1] for v in SCENARIOS.values()) + 1:
        st.caption("※ 기간이 짧으면 일부 시나리오가 포함되지 않습니다.")
    if st.button("데모 데이터 다시 생성(기존 데이터 교체)"):
        clear_db()
        save_raw(generate_demo_data(end=end_d, days=int(days), seed=int(seed)), replace=True)
        DEMO_FLAG.write_text("demo", encoding="utf-8")
        refresh()
        st.success("데모 데이터를 생성했습니다.")
        st.rerun()

with tab4:
    raw = load_raw()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in raw.items():
            df.to_excel(xw, sheet_name=SHEET_NAMES[name], index=False)
    st.download_button("⬇️ 전체 원 데이터(엑셀)", buf.getvalue(), file_name="QMS_원데이터.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.divider()
    confirm = st.checkbox("모든 데이터와 알림 처리 기록을 삭제합니다(되돌릴 수 없음).")
    if st.button("전체 삭제", disabled=not confirm, type="primary"):
        clear_db()
        DEMO_FLAG.unlink(missing_ok=True)
        save_raw({k: pd.DataFrame(columns=["timestamp"]) for k in TABLES}, replace=True)
        refresh()
        st.success("삭제했습니다. 업로드 탭에서 실제 데이터를 올리세요.")
        st.rerun()
