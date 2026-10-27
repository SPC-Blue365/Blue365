"""데이터 관리: 템플릿 · 업로드 · 데모 데이터 · 내보내기."""

import io
from datetime import date

import pandas as pd
import streamlit as st

from qms import incoming, ship_dest, shipment, workbook
from qms.demo import SCENARIOS, generate_demo_data, scenario_table
from qms.standards import TABLES
from qms.store import SHEET_NAMES, clear_db, load_raw, parse_upload, save_raw, template_workbook
from qms.upload_template import build_upload_template
from qms.ui import DEMO_FLAG, get_ctx, page_header, refresh
from qms.ui_ship import dest_panel, parsed_panel

ctx = get_ctx()
reg, store = ctx.registry, ctx.store
page_header(ctx, "📥 데이터 관리")

if st.session_state.get("last_apply"):
    st.success("✅ " + st.session_state["last_apply"])

st.subheader("데이터 현황")
st.caption("업로드·자동 반영이 제대로 됐는지 여기서 바로 확인하세요. 행 수와 종료일(가장 최근 데이터)이 바뀌면 반영된 것입니다.")
rows = []
for name, meta in TABLES.items():
    df = store.tables.get(name, pd.DataFrame())
    rows.append({"구분": meta["label"], "측정 주기": meta["freq"], "품종 구분": "예" if meta["by_product"] else "-",
                 "행 수": len(df), "시작": df["timestamp"].min() if len(df) else None,
                 "종료": df["timestamp"].max() if len(df) else None})
_ship = shipment.load_shipment()
rows.append({"구분": "🚢 출하시멘트", "측정 주기": "1일", "품종 구분": "예", "행 수": len(_ship),
             "시작": _ship["date"].min() if len(_ship) else None, "종료": _ship["date"].max() if len(_ship) else None})
_inc = incoming.load_incoming()
rows.append({"구분": "📦 인수검사", "측정 주기": "입고시", "품종 구분": "-", "행 수": len(_inc),
             "시작": pd.to_datetime(_inc["채취일"]).min() if len(_inc) else None,
             "종료": pd.to_datetime(_inc["채취일"]).max() if len(_inc) else None})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
    "시작": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
    "종료": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
if ctx.demo:
    st.info("현재 데모 데이터입니다. 실제 데이터를 업로드하기 전에 아래 '전체 삭제'로 데모 데이터를 지우세요.", icon="🧪")

tab1, tab2, tab3, tab4 = st.tabs(["⬆️ 업로드", "📄 입력 템플릿", "🧪 데모 데이터", "⬇️ 내보내기·삭제"])
with tab1:
    st.markdown("엑셀(시트: 원료·킬른·클링커·시멘트·물성) 또는 CSV(파일명에 테이블명 포함, 예: `clinker_2026-10.csv`)를 올리세요. "
                "같은 측정일시(+품종)는 업로드 값으로 덮어씁니다.")
    up = st.file_uploader("파일 선택", type=["xlsx", "xls", "csv"])
    parts = workbook.analyze(up.getvalue(), up.name) if up is not None and not up.name.lower().endswith(".csv") else None
    if parts is not None and (parts.is_template or len(parts.kinds) >= 2):      # 통합 업로드 양식(공정+출하+인수검사)
        st.info("**통합 업로드 양식**입니다. 시트별로 읽은 내용을 확인하고 한 번에 적용하세요: "
                + (" · ".join(parts.kinds) or "읽은 데이터 없음"), icon="🗂️")
        for m in parts.summary():
            st.write("•", m)
        for e in parts.errors:
            st.error(e)
        for name, df in parts.process.tables.items():
            with st.expander(f"미리보기: {SHEET_NAMES[name]} ({len(df)}행)"):
                st.dataframe(df.head(50), hide_index=True)
        for sn, p in parts.ships:
            with st.expander(f"미리보기: 출하시멘트·{sn} ({len(p.records)}건)"):
                st.dataframe(p.records.head(50), hide_index=True)
        for sn, p in parts.incomings:
            with st.expander(f"미리보기: 인수검사·{sn} ({len(p.rows)}행)"):
                st.dataframe(p.rows.drop(columns=["성분"]).head(50), hide_index=True)
        if parts.kinds:
            replace_demo = st.checkbox("데모 데이터를 지우고 업로드 데이터만 사용", value=ctx.demo, key="wb_replace_demo")
            if st.button("✅ 통합 양식 전체 적용(저장)", type="primary", key="wb_apply"):
                if replace_demo:
                    clear_db()
                    DEMO_FLAG.unlink(missing_ok=True)
                logs = workbook.apply(parts)
                refresh()
                st.session_state["last_apply"] = f"{pd.Timestamp.now():%Y-%m-%d %H:%M} · " + " / ".join(logs)
                st.rerun()
    elif up is not None and shipment.looks_like_shipment(up.getvalue(), up.name):
        st.info("LIMS **출하시멘트 일일 로트** 형식입니다. 전용 화면(🚢 출하시멘트)에서 관리하며, 아래에서 바로 저장할 수 있습니다.", icon="🚢")
        parsed_panel(up.getvalue(), up.name, key="data_ship")
    elif up is not None and ship_dest.looks_like_dest(up.getvalue(), up.name):
        st.info("**선박 양하지** 자료입니다(선박·양하지[·일자] 열). 출하시멘트 기록에 자동으로 연결됩니다.", icon="⚓")
        dest_panel(up.getvalue(), up.name, key="data_dest")
    elif up is not None and incoming.looks_like_incoming(up.getvalue(), up.name):
        p = incoming.parse_incoming(up.getvalue(), up.name)
        for m in p.messages:
            st.write("•", m)
        for e in p.errors:
            st.error(e)
        if not p.rows.empty:
            st.info(f"**{p.kind} 인수검사** 자료입니다. 전용 화면(📦 인수검사)에서 관리합니다.", icon="📦")
            with st.expander(f"미리보기 ({len(p.rows)}행)"):
                st.dataframe(p.rows.drop(columns=["성분"]).head(50), hide_index=True)
            if st.button("✅ 인수검사 적용(저장)", type="primary", key="save_incoming"):
                n = incoming.save_incoming(p.rows)
                st.session_state["last_apply"] = (f"{pd.Timestamp.now():%Y-%m-%d %H:%M} · {p.kind} 인수검사 "
                                                  f"{len(p.rows)}행 반영 → 누계 {n}행. 📦 인수검사 화면에서 확인하세요.")
                st.rerun()
    elif up is not None:
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
            if st.button("✅ 공정 데이터 적용(저장)", type="primary"):
                if replace_demo:
                    clear_db()
                    DEMO_FLAG.unlink(missing_ok=True)
                counts = save_raw(res.tables, replace=False)
                refresh()
                st.session_state["last_apply"] = (f"{pd.Timestamp.now():%Y-%m-%d %H:%M} · 공정 데이터 반영 → "
                                                  + ", ".join(f"{SHEET_NAMES[k]} {v}행" for k, v in counts.items())
                                                  + ". 공정 모니터링·그래프 보기 화면에서 확인하세요.")
                st.rerun()

with tab2:
    st.markdown("**통합 업로드 양식** — 한 파일에 공정별 시트(원료·킬른·클링커·클링커일일·시멘트·물성)와 출하시멘트·인수검사가 들어 있습니다. "
                "각 시트의 **공정구분**(킬른 4K~7K · 원료밀 R/M · 시멘트밀 C/M)과 **품명**은 목록에서 고르고, 5행부터 LIMS 값을 붙여넣으세요.")
    st.download_button("⬇️ 통합 업로드 양식(엑셀)", build_upload_template(), file_name="Blue365_QMS_업데이트_양식.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.caption("채운 파일은 위 ‘⬆️ 업로드’에 올리거나, 매일 자동 반영 파일(data\\Blue365_QMS.xlsx)로 저장하면 06:00에 자동 반영됩니다. "
               "LIMS에서 받은 원본 파일을 그대로 올려도 인식합니다.")
    with st.expander("내부 항목 코드 양식(고급 — 열 이름이 QMS 내부 코드)"):
        sample = {k: v.head(5) for k, v in load_raw().items()}
        st.download_button("⬇️ 내부 코드 템플릿(엑셀)", template_workbook(reg, sample), file_name="QMS_데이터입력템플릿.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab3:
    st.markdown("가상의 공장 데이터(원료→소성→클링커→분쇄→강도 인과관계 반영)와 이상 시나리오 6종을 생성합니다.")
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
