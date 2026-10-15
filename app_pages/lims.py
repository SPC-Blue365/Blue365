"""LIMS 연동: 연결 설정 · 시험코드 매핑 · 동기화 실행 · 이력."""

import json

import pandas as pd
import streamlit as st

from qms import lims
from qms import ui_lims as U
from qms.standards import TABLES
from qms.store import RAW_COLUMNS
from qms.ui import get_ctx, page_header, refresh

ctx = get_ctx()
page_header(ctx, "🔗 LIMS 연동")
st.caption("실험실정보관리시스템(LIMS)의 **승인된 시험 결과**를 주기적으로 가져와 QMS 모니터링·알림·진단·예측에 바로 사용합니다. "
           "결과가 항목별로 늦게 확정돼도(예: 28일 강도) 같은 시료 행에 열 단위로 채워지고, 먼저 들어온 값은 지워지지 않습니다.")

cfg = lims.load_lims_config()
log = lims.read_sync_log()
last = log[-1] if log else None
s1, s2, s3, s4 = st.columns(4)
s1.metric("연동 상태", "사용" if cfg.enabled else "꺼짐", border=True)
s2.metric("연동 방식", {"db": "DB 연결", "demo": "데모", "sql": "SQL 직접", "rest": "REST API", "file": "파일"}.get(cfg.mode, cfg.mode),
          help=lims.MODES.get(cfg.mode, cfg.mode), border=True)
s3.metric("마지막 동기화", last["ts"] if last else "-", delta=("실패" if last and last.get("errors") else
                                                          (f"반영 {last.get('n_mapped', 0)}건" if last else None)),
          delta_color="off", delta_arrow="off", border=True)
if cfg.mode == "db":
    s4.metric("가져올 곳", f"{sum(1 for x in cfg.sources if x.get('enabled', True))}개", border=True,
              help="② 탭에서 지정한 LIMS 표·뷰(사용 중인 것)")
else:
    s4.metric("워터마크(이후 결과만 조회)", cfg.watermark or f"최근 {cfg.lookback_days}일", border=True)

with st.expander("연동 구조와 보안 원칙", expanded=not cfg.enabled):
    st.markdown("""
| 단계 | 내용 |
|---|---|
| ① 조회 | **DB 연결(IP·포트·계정 입력 → 표 고르기, 권장)** · REST API · 내보내기 파일 중 하나로 **워터마크 이후 확정된 결과만** 조회 |
| ② 표준화 | 열 이름 맞춤(sampled_at·sample_point·test_code·value·product·status·updated_at), 날짜·숫자 변환, `<0.1` 같은 부등호 값 처리 |
| ③ 필터 | 승인 상태(APPROVED 등)만 반영 — 미승인·재시험 대기 결과 제외 |
| ④ 매핑 | (채취 지점, 시험코드) → QMS 항목(자동 추천 후 확인). 단위 환산(계수·오프셋), 품종 코드 변환(OPC→1종, HES→3종) · 출하시멘트 성적은 🚢 출하시멘트로 |
| ⑤ 저장 | 시료 일시(+품종) 기준 **열 단위 병합** — 늦게 나온 결과만 채우고 기존 값 유지 |
| ⑥ 감시 | `python qms_monitor.py --sync-lims` 를 10~30분 주기로 실행 → 동기화 후 이상 감지·알림 자동 발송 |

**처음 연동할 때**: LIMS 담당자에게 받은 **IP·포트·DB 이름·아이디·비밀번호**를 ① 탭(연동 방식 'DB 연결')에 입력 → 🩺 연결 확인 → ② 탭에서 표를 고르고 항목을 매칭하세요.
IT 요청서·결과 뷰(View) SQL 예시가 필요하면 ③ 탭의 **📄 LIMS 연동 준비서(엑셀)** 를 내려받으세요.

**보안**: DB 비밀번호는 ① 탭에서 입력하면 **암호화해 저장**합니다(Windows: 이 PC의 이 Windows 계정에서만 풀리는 DPAPI). 화면·설정 파일(lims.json)·
동기화 기록에는 남지 않고, 저장 후 다시 보여주지 않습니다. 접속 정보는 QMS를 실행 중인 PC에서만 바꿀 수 있습니다(공유 접속은 보기만).
QMS는 **SELECT(읽기)만** 실행하며 PostgreSQL·MySQL은 읽기 전용 세션으로 접속합니다. LIMS 담당자에게 **읽기 전용 계정**을 요청하세요.
(환경변수 `QMS_LIMS_PASSWORD` / `QMS_LIMS_TOKEN` 또는 `.streamlit/secrets.toml [lims]` 에 두면 그 값을 먼저 씁니다.)
""")

tab1, tab_src, tab2, tab3, tab4 = st.tabs(["① 연결 설정", "② 가져올 곳·항목 매칭", "③ 시험코드 매핑(파일·REST·SQL)", "④ 동기화 실행",
                                           "⑤ 이력"])

with tab1:
    mode = st.selectbox("연동 방식", list(lims.MODES), index=list(lims.MODES).index(cfg.mode) if cfg.mode in lims.MODES else 0,
                        format_func=lambda m: lims.MODES[m], key="lims_mode_pick",
                        help="LIMS DB의 IP·포트·아이디·비밀번호를 알면 'DB 연결'을 고르세요.")
    if mode == "db":
        U.conn_panel(cfg)
        st.divider()
        with st.form("lims_common"):
            st.markdown("##### ⚙️ 공통 설정")
            g1, g2, g3 = st.columns([1, 1, 1.4])
            enabled_db = g1.toggle("LIMS 연동 사용", value=cfg.enabled, help="켜야 ④ 동기화 실행·자동 감시(5_MONITOR_TASK)가 반영합니다.")
            lookback_db = g2.number_input("최초 조회 기간(일)", 1, 365, int(cfg.lookback_days),
                                          help="확정일시 열이 없으면 매번 최근 N일 채취분을 다시 읽습니다(28일 강도를 위해 35일 이상 권장).")
            status_db = g3.text_input("반영할 결과 상태(쉼표 구분)", ", ".join(cfg.status_ok),
                                      help="결과 상태 열을 지정한 가져올 곳에만 적용")
            prod_db = st.text_input("품종 코드 → QMS 품종(JSON)", json.dumps(cfg.product_map, ensure_ascii=False))
            if st.form_submit_button("공통 설정 저장", type="primary"):
                try:
                    cfg.enabled, cfg.mode, cfg.lookback_days = enabled_db, "db", int(lookback_db)
                    cfg.status_ok = [x.strip() for x in status_db.split(",") if x.strip()]
                    cfg.product_map = json.loads(prod_db or "{}")
                    lims.save_lims_config(cfg)
                    st.success("저장했습니다.")
                    st.rerun()
                except (ValueError, json.JSONDecodeError) as exc:
                    st.error(f"저장 실패: {exc}")
    else:
        with st.form("lims_conn"):
            c1, c3 = st.columns([1, 1])
            enabled = c1.toggle("LIMS 연동 사용", value=cfg.enabled)
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
            st.markdown("**내보내기 파일** — 긴 형식(결과당 1행)과 가로형(시료당 1행, 열 이름 = 시험코드) 모두 가능")
            f1, f2 = st.columns([2, 1])
            file_dir = f1.text_input("폴더 경로(CSV·XLSX)", cfg.file_dir, placeholder=r"\\FILESRV\LIMS_EXPORT 또는 D:/LIMS_EXPORT")
            default_sp = f2.text_input("기본 채취 지점(지점 열이 없을 때)", cfg.default_sample_point, placeholder="CLINKER",
                                       help="파일 이름에 지점 코드(예: CLINKER_1010.xlsx)가 있으면 그것을 먼저 씁니다.")
            st.markdown("**변환 규칙**")
            v1, v2, v3 = st.columns(3)
            status_ok = v1.text_input("반영할 결과 상태(쉼표 구분)", ", ".join(cfg.status_ok))
            prod_map = v2.text_area("품종 코드 → QMS 품종(JSON)", json.dumps(cfg.product_map, ensure_ascii=False), height=90)
            col_map = v3.text_area("LIMS 열 이름 → 표준 열 이름(JSON)", json.dumps(cfg.column_map, ensure_ascii=False), height=90,
                                   help='예: {"채취일시": "sampled_at", "ITEM": "test_code", "RESULT": "value", "시료번호": "-"} '
                                        '— "-" 로 지정한 열은 버립니다(가로형 파일의 시료번호·비고 등).')
            if st.form_submit_button("저장", type="primary"):
                try:
                    cfg.enabled, cfg.mode, cfg.lookback_days = enabled, mode, int(lookback)
                    cfg.sql_url, cfg.sql_query = sql_url.strip(), sql_query
                    cfg.rest_url, cfg.rest_records_path, cfg.rest_since_param = rest_url.strip(), rec_path.strip(), since_param.strip()
                    cfg.file_dir, cfg.default_sample_point = file_dir.strip(), default_sp.strip().upper()
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
        if mode == "rest":
            k1, k2 = st.columns([2, 1], vertical_alignment="bottom")
            tok = k1.text_input("API 토큰 입력(암호화 저장)", type="password", key=f"lims_tok_{st.session_state.get('lims_tok_v', 0)}",
                                disabled=not U.is_local(),
                                placeholder="저장됨 — 바꿀 때만 입력" if lims.secret_source("token") else "")
            if k2.button("토큰 저장", disabled=not tok or not U.is_local()):
                from qms import secret_store
                secret_store.set_secret(lims.STORE_NAMES["token"], tok)
                st.session_state["lims_tok_v"] = st.session_state.get("lims_tok_v", 0) + 1
                st.rerun()

with tab_src:
    if cfg.mode != "db":
        st.info("이 탭은 **DB 연결** 방식에서 씁니다. ① 연결 설정에서 연동 방식을 'DB 연결'로 고르고 접속 정보를 저장하세요.")
    else:
        U.sources_panel(cfg, ctx.registry)

with tab2:
    if cfg.mode == "db":
        st.info("DB 연결 방식은 **② 가져올 곳·항목 매칭**에서 가져올 곳마다 항목을 매칭합니다. 아래 표는 파일·REST·SQL 직접 입력 방식에서 씁니다.")
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
    m1, m2, m3, m4 = st.columns(4)
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
    m4.download_button("📄 LIMS 연동 준비서(엑셀)", lims.prep_workbook(ctx.registry), file_name="LIMS_연동_준비서.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       help="IT 요청서·표준 뷰 정의(SQL 예시)·시험항목 매핑표·코드 변환·검증 체크리스트")
    st.markdown("**매핑표 올리기** — 준비서 ⑤ 시트에 회사 채취지점·시험코드를 적거나, 위 '매핑표 CSV'를 고쳐서 올리세요.")
    up = st.file_uploader("매핑표(엑셀·CSV)", type=["xlsx", "csv"], key="lims_map_upload")
    if up is not None:
        try:
            up_rows, up_warns = lims.parse_mapping_table(up.getvalue(), up.name)
        except ValueError as exc:
            st.error(str(exc))
            up_rows, up_warns = [], []
        for w in up_warns[:10]:
            st.warning(w)
        if up_rows:
            st.dataframe(pd.DataFrame(up_rows), hide_index=True, height=220)
            if st.button(f"가져오기 — 현재 매핑을 이 표({len(up_rows)}건)로 바꾸기", type="primary"):
                cfg.mapping = up_rows
                lims.save_lims_config(cfg)
                st.session_state.pop("lims_map_editor", None)
                st.success(f"매핑 {len(up_rows)}건을 등록했습니다.")
                st.rerun()
        elif not up_warns:
            st.info("회사 채취지점·시험코드가 적힌 행이 없습니다(준비서 ⑤ 시트의 노란 칸).")
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
        for _s in cfg.sources:
            _s.pop("watermark", None)
        lims.save_lims_config(cfg)
        st.rerun()
    if preview or run:
        with st.spinner("LIMS에서 결과를 읽는 중…"):
            rep = lims.sync(cfg, dry_run=preview and not run)
        U.show_report(rep, preview=preview and not run)
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
    st.markdown("**무인 자동 동기화** — 설치 패키지: `5_MONITOR_TASK.bat` → 1번(30분마다 동기화·이상 감지·알림). "
                "직접 실행하는 경우 작업 스케줄러(cron/Windows)에 등록:")
    st.code("python qms_monitor.py --sync-lims --since-hours 24", language="bash")
