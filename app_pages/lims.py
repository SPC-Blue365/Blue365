"""LIMS 연동: 연결 설정 · 시험코드 매핑 · 동기화 실행 · 이력."""

import json

import pandas as pd
import streamlit as st

from qms import lims
from qms.standards import TABLES
from qms.store import RAW_COLUMNS
from qms.ui import get_ctx, refresh, sidebar

ctx = get_ctx()
sidebar(ctx)
st.title("🔗 LIMS 연동")
st.caption("실험실정보관리시스템(LIMS)의 **승인된 시험 결과**를 주기적으로 가져와 QMS 모니터링·알림·진단·예측에 바로 사용합니다. "
           "결과가 항목별로 늦게 확정돼도(예: 28일 강도) 같은 시료 행에 열 단위로 채워지고, 먼저 들어온 값은 지워지지 않습니다.")

cfg = lims.load_lims_config()
log = lims.read_sync_log()
last = log[-1] if log else None
s1, s2, s3, s4 = st.columns(4)
s1.metric("연동 상태", "사용" if cfg.enabled else "꺼짐", border=True)
s2.metric("연동 방식", {"demo": "데모", "sql": "DB 조회", "rest": "REST API", "file": "파일"}.get(cfg.mode, cfg.mode),
          help=lims.MODES.get(cfg.mode, cfg.mode), border=True)
s3.metric("마지막 동기화", last["ts"] if last else "-", delta=("실패" if last and last.get("errors") else
                                                          (f"반영 {last.get('n_mapped', 0)}건" if last else None)),
          delta_color="off", delta_arrow="off", border=True)
s4.metric("워터마크(이후 결과만 조회)", cfg.watermark or f"최근 {cfg.lookback_days}일", border=True)

with st.expander("연동 구조와 보안 원칙", expanded=not cfg.enabled):
    st.markdown("""
| 단계 | 내용 |
|---|---|
| ① 조회 | LIMS DB(읽기 전용 계정) · REST API · 내보내기 파일 중 하나로 **워터마크 이후 확정된 결과만** 조회 |
| ② 표준화 | 열 이름 맞춤(sampled_at·sample_point·test_code·value·product·status·updated_at), 날짜·숫자 변환, `<0.1` 같은 부등호 값 처리 |
| ③ 필터 | 승인 상태(APPROVED 등)만 반영 — 미승인·재시험 대기 결과 제외 |
| ④ 매핑 | (채취 지점, 시험코드) → QMS 항목. 단위 환산(계수·오프셋), 품종 코드 변환(OPC→1종, HES→3종) |
| ⑤ 저장 | 시료 일시(+품종) 기준 **열 단위 병합** — 늦게 나온 결과만 채우고 기존 값 유지 |
| ⑥ 감시 | `python qms_monitor.py --sync-lims` 를 10~30분 주기로 실행 → 동기화 후 이상 감지·알림 자동 발송 |

**보안**: DB 비밀번호·API 토큰은 화면·설정 파일에 저장하지 않습니다. 환경변수 `QMS_LIMS_PASSWORD` / `QMS_LIMS_TOKEN`
또는 `.streamlit/secrets.toml`의 `[lims]` 섹션(password, token)에 두세요. LIMS DB에는 **읽기 전용 계정**과 결과 뷰(View)만 열어 두는 것을 권장합니다.
""")

tab1, tab2, tab3, tab4 = st.tabs(["① 연결 설정", "② 시험코드 매핑", "③ 동기화 실행", "④ 이력"])

with tab1:
    with st.form("lims_conn"):
        c1, c2, c3 = st.columns([1, 1.4, 1])
        enabled = c1.toggle("LIMS 연동 사용", value=cfg.enabled)
        mode = c2.selectbox("연동 방식", list(lims.MODES), index=list(lims.MODES).index(cfg.mode) if cfg.mode in lims.MODES else 0,
                            format_func=lambda m: lims.MODES[m])
        lookback = c3.number_input("최초 조회 기간(일)", 1, 365, int(cfg.lookback_days),
                                   help="워터마크가 없을 때 최근 N일 결과를 가져옵니다.")
        st.markdown("**DB 직접 조회(SQL)** — 데모 방식은 시연용 SQLite(data/lims_demo.db)를 사용합니다.")
        sql_url = st.text_input("SQLAlchemy 연결 주소", cfg.sql_url,
                                placeholder="mssql+pyodbc://qms_reader:{password}@LIMS-DB/LIMS?driver=ODBC+Driver+18+for+SQL+Server",
                                help="비밀번호 자리에는 {password} 를 쓰세요(환경변수 QMS_LIMS_PASSWORD 로 대체).")
        sql_query = st.text_area("조회문(표준 열 이름으로 AS 별칭, :since = 워터마크)", cfg.sql_query, height=210)
        st.markdown("**REST API**")
        r1, r2, r3 = st.columns([2, 1, 1])
        rest_url = r1.text_input("API 주소", cfg.rest_url, placeholder="https://lims.company.local/api/results")
        rec_path = r2.text_input("결과 목록 위치(JSON)", cfg.rest_records_path, help="예: data 또는 result.items")
        since_param = r3.text_input("증분 조회 매개변수", cfg.rest_since_param)
        st.markdown("**내보내기 파일**")
        file_dir = st.text_input("폴더 경로(CSV·XLSX, 긴 형식)", cfg.file_dir, placeholder="D:/LIMS_EXPORT")
        st.markdown("**변환 규칙**")
        v1, v2, v3 = st.columns(3)
        status_ok = v1.text_input("반영할 결과 상태(쉼표 구분)", ", ".join(cfg.status_ok))
        prod_map = v2.text_area("품종 코드 → QMS 품종(JSON)", json.dumps(cfg.product_map, ensure_ascii=False), height=90)
        col_map = v3.text_area("LIMS 열 이름 → 표준 열 이름(JSON)", json.dumps(cfg.column_map, ensure_ascii=False), height=90,
                               help='예: {"SAMPLE_DATE": "sampled_at", "ITEM": "test_code", "RESULT": "value"}')
        if st.form_submit_button("저장", type="primary"):
            try:
                cfg.enabled, cfg.mode, cfg.lookback_days = enabled, mode, int(lookback)
                cfg.sql_url, cfg.sql_query = sql_url.strip(), sql_query
                cfg.rest_url, cfg.rest_records_path, cfg.rest_since_param = rest_url.strip(), rec_path.strip(), since_param.strip()
                cfg.file_dir = file_dir.strip()
                cfg.status_ok = [s.strip() for s in status_ok.split(",") if s.strip()]
                cfg.product_map = json.loads(prod_map or "{}")
                cfg.column_map = json.loads(col_map or "{}")
                lims.save_lims_config(cfg)
                st.success("저장했습니다.")
                st.rerun()
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(f"저장 실패: {exc}")
    sec = lims.secret_status()
    st.caption(f"비밀값 상태: DB 비밀번호 {'설정됨' if sec['password'] else '없음'} · API 토큰 {'설정됨' if sec['token'] else '없음'}")
    t1, t2 = st.columns([1, 3])
    if t1.button("연결 테스트"):
        ok, msg, prev = lims.test_connection(cfg)
        (st.success if ok else st.error)(msg)
        if len(prev):
            st.dataframe(prev, hide_index=True)
    if cfg.mode == "demo" and t2.button("데모 LIMS DB 다시 만들기", help="현재 QMS 데이터 최근 10일을 LIMS 형식으로 만듭니다."):
        from qms.store import load_raw
        info = lims.create_demo_lims(load_raw())
        st.success(f"데모 LIMS DB 생성: 시료 {info['samples']}건, 결과 {info['results']}건")

with tab2:
    st.markdown("**(채취 지점, 시험코드) → QMS 항목** 매핑표입니다. 공장 LIMS의 시험코드표에 맞게 수정하세요. "
                "계수·오프셋으로 단위를 환산합니다(QMS 값 = LIMS 값 × 계수 + 오프셋).")
    options = sorted({f"{t}.{c}" for t, cols in RAW_COLUMNS.items() for c in cols if c != "product"})
    names = {"sand_lot": "표준사 Lot", "operator": "시험 조"}
    mp = pd.DataFrame(cfg.mapping)
    if len(mp):
        mp["대상"] = mp["table"] + "." + mp["column"]
        mp["항목명"] = mp["column"].map(lambda c: ctx.registry[c].label() if c in ctx.registry else names.get(c, c))
    mp_ed = st.data_editor(mp[["sample_point", "test_code", "대상", "항목명", "factor", "offset"]] if len(mp) else
                           pd.DataFrame(columns=["sample_point", "test_code", "대상", "항목명", "factor", "offset"]),
                           key="lims_map_editor", num_rows="dynamic", hide_index=True, height=420, width="stretch",
                           column_config={"sample_point": st.column_config.TextColumn("채취 지점"),
                                          "test_code": st.column_config.TextColumn("시험코드"),
                                          "대상": st.column_config.SelectboxColumn("QMS 항목(테이블.열)", options=options,
                                                                                width="large"),
                                          "항목명": st.column_config.TextColumn("항목명(저장 후 갱신)", disabled=True),
                                          "factor": st.column_config.NumberColumn("계수", format="%.4g"),
                                          "offset": st.column_config.NumberColumn("오프셋", format="%.4g")})
    m1, m2, m3 = st.columns(3)
    if m1.button("매핑 저장", type="primary"):
        rows = []
        for _, r in mp_ed.dropna(subset=["sample_point", "test_code", "대상"]).iterrows():
            table, column = str(r["대상"]).split(".", 1)
            rows.append({"sample_point": str(r["sample_point"]).strip().upper(), "test_code": str(r["test_code"]).strip().upper(),
                         "table": table, "column": column, "factor": float(r["factor"]) if pd.notna(r["factor"]) else 1.0,
                         "offset": float(r["offset"]) if pd.notna(r["offset"]) else 0.0})
        cfg.mapping = rows
        lims.save_lims_config(cfg)
        st.success(f"매핑 {len(rows)}건 저장")
        st.rerun()
    if m2.button("기본 매핑으로 되돌리기"):
        cfg.mapping = lims.default_mapping()
        lims.save_lims_config(cfg)
        st.session_state.pop("lims_map_editor", None)
        st.rerun()
    m3.download_button("매핑표 CSV", pd.DataFrame(cfg.mapping).to_csv(index=False).encode("utf-8-sig"),
                       file_name="LIMS_매핑표.csv", mime="text/csv")
    st.caption("채취 지점 기본값: " + ", ".join(f"{lims.SAMPLE_POINTS[t]} = {TABLES[t]['label']}" for t in lims.SAMPLE_POINTS)
               + ". DCS 운전값(밀 투입량·온도)은 LIMS 대상이 아니어서 매핑하지 않습니다.")

with tab3:
    st.markdown("**미리보기(저장 안 함)** 로 결과를 확인한 뒤 **동기화 실행**을 누르세요. 실행하면 워터마크가 갱신됩니다.")
    d1, d2, d3 = st.columns(3)
    preview = d1.button("미리보기(저장 안 함)")
    run = d2.button("동기화 실행", type="primary", disabled=not cfg.enabled,
                    help=None if cfg.enabled else "① 연결 설정에서 'LIMS 연동 사용'을 켜세요.")
    if d3.button("워터마크 초기화", help=f"다음 동기화 때 최근 {cfg.lookback_days}일을 다시 조회합니다."):
        cfg.watermark = None
        lims.save_lims_config(cfg)
        st.rerun()
    if preview or run:
        rep = lims.sync(cfg, dry_run=preview and not run)
        (st.error if rep.errors else st.success)(("[미리보기] " if preview and not run else "") + rep.summary_text())
        for m in rep.messages:
            st.info(m)
        if rep.unmapped:
            st.warning("매핑되지 않은 시험코드(② 탭에서 등록하거나 무시): " +
                       ", ".join(f"{sp}/{tc} {n}건" for sp, tc, n in rep.unmapped[:12]))
        if rep.n_censored:
            st.caption(f"부등호 값(<, >) {rep.n_censored}건은 숫자 부분만 사용했습니다(검출한계 표시값).")
        for table, wdf in rep.wide.items():
            with st.expander(f"{TABLES[table]['label']} — {len(wdf)}행"):
                st.dataframe(wdf.tail(50), hide_index=True)
        if run and rep.saved:
            refresh()
            st.success("QMS 데이터에 반영했습니다. 모니터링·알림이 새 데이터로 다시 계산됩니다.")

with tab4:
    if not log:
        st.info("동기화 이력이 없습니다.")
    else:
        rows = [{"일시": e.get("ts"), "방식": e.get("mode"), "미리보기": "예" if e.get("dry_run") else "",
                 "조회": e.get("n_fetched"), "반영": e.get("n_mapped"), "신규 칸": e.get("cells_new"),
                 "변경 칸": e.get("cells_changed"), "미승인 제외": e.get("n_status_skipped"), "미매핑": e.get("n_unmapped"),
                 "워터마크": e.get("watermark_after"), "오류": "; ".join(e.get("errors") or [])} for e in reversed(log)]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.markdown("**무인 자동 동기화** — 서버 작업 스케줄러(cron/Windows)에 등록:")
    st.code("python qms_monitor.py --sync-lims --since-hours 24", language="bash")
