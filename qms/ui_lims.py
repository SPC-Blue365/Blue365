"""LIMS 연동 화면 — DB 연결 방식(주소·계정 입력 → 연결 진단 → 표 고르기 → 열 역할 → 항목 매칭)."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from . import lims, lims_db as L, secret_store as SS
from . import shipment as S
from .standards import TABLES
from .store import RAW_COLUMNS

NONE = "(없음)"
SKIP = "(가져오지 않음)"
QMS_TABLES = [t for t in ("raw_meal", "clinker", "xrd", "cement", "physical")]
SP_GUESS = {   # 채취 지점 값 → QMS 시료 종류(추천용)
    "raw_meal": ("kf", "kilnfeed", "rawmeal", "생료", "원료", "킬른피드", "raw", "rm", "feed"),
    "clinker": ("clk", "clinker", "클링커", "ck", "cl"),
    "xrd": ("xrd", "clinkerdaily", "클링커일일", "일일시료", "크롬"),
    "cement": ("cm", "cement", "cementmill", "시멘트", "밀출구", "cem", "mill"),
    "physical": ("phy", "physical", "물성", "강도", "lot", "cementlot", "출하", "제품"),
}
DATE_FORMATS = {"datetime": "날짜형(DATE·DATETIME)", "%Y%m%d": "문자 20261015", "%Y%m%d%H%M%S": "문자 20261015083000",
                "%Y%m%d%H%M": "문자 202610150830", "%Y-%m-%d %H:%M:%S": "문자 2026-10-15 08:30:00", "%Y.%m.%d": "문자 2026.10.15",
                "%Y/%m/%d": "문자 2026/10/15", "int:%Y%m%d": "숫자 20261015", "int:%Y%m%d%H%M%S": "숫자 20261015083000"}


def is_local() -> bool:
    """QMS를 실행 중인 PC에서 접속했는가(공유 실행 때 다른 PC는 접속 정보·비밀번호를 바꾸지 못함)."""
    try:
        ip = st.context.ip_address
    except Exception:  # noqa: BLE001
        return True
    return ip in (None, "", "127.0.0.1", "::1", "localhost")


def _pw() -> str:
    return lims._secret("password")


def guess_table(sp: str) -> str | None:
    """채취 지점 값 → QMS 시료 종류. 정확히 같은 이름 우선, 그다음 가장 길게 겹치는 이름(CLINKER_DAILY → XRD)."""
    n = L.norm(sp)
    for t, al in SP_GUESS.items():
        if n in al:
            return t
    best = max(((len(a), t) for t, al in SP_GUESS.items() for a in al if len(a) >= 3 and a in n), default=None)
    return best[1] if best else None


def item_options(registry, tables=None) -> dict[str, str]:
    names = {"sand_lot": "표준사 Lot", "operator": "시험 조"}
    out = {}
    for t in tables or QMS_TABLES:
        for c in RAW_COLUMNS[t]:
            if c == "product" or c in lims.DCS_ONLY:
                continue
            nm = registry[c].label() if c in registry else names.get(c, c)
            out[f"{t}.{c}"] = f"{TABLES[t]['label']} · {nm}"
    return out


def _steps_table(steps: list[dict]) -> None:
    for x in steps:
        (st.success if x["ok"] else st.error)(f"{'✅' if x['ok'] else '❌'} **{x['step']}** — {x['msg']}")


def _clear_browse_cache() -> None:
    ss = st.session_state
    for k in [k for k in ss if str(k).startswith(("ldb_objects_", "ldb_schemas", "ldb_cols_", "ldb_prev_", "ldb_codes_", "ldb_dbs",
                                                   "ldb_explore", "ldb_find", "ldb_struct"))]:
        ss.pop(k, None)


# ── ① 접속 정보 ─────────────────────────────────────────────────────────
def conn_panel(cfg: lims.LimsConfig) -> None:
    ss = st.session_state
    local = is_local()
    c0 = {**L.empty_conn(), **(cfg.db or {})}
    st.markdown("##### 🔌 LIMS DB 접속 정보")
    st.caption("LIMS 담당자에게 받은 **IP 주소·호스트 이름·포트·DB 이름·아이디·비밀번호**를 입력하세요. IP와 호스트 이름은 하나만 있어도 됩니다"
               "(둘 다 있으면 IP로 접속). 비밀번호는 암호화해 저장하며 화면에 다시 보여주지 않습니다.")
    if not local:
        st.info("🔒 접속 정보·비밀번호는 **QMS를 실행 중인 PC**에서만 바꿀 수 있습니다(사내망 공유 접속은 보기만 가능).")
    types = list(L.DB_TYPES)
    if "ldb_type_next" in ss:                          # 🔎 DB 종류 자동 확인 결과 반영(위젯을 만들기 전에만 바꿀 수 있음)
        ss["ldb_type"] = ss.pop("ldb_type_next")
        if "ldb_port_next" in ss:
            ss[f"ldb_port_{ss['ldb_type']}"] = ss.pop("ldb_port_next")
    a1, a2 = st.columns([1.3, 1])
    tkw = {} if "ldb_type" in ss else {"index": types.index(c0["type"]) if c0["type"] in types else 0}
    t = a1.selectbox("DB 종류", types, **tkw,
                     format_func=lambda k: L.DB_TYPES[k]["label"], key="ldb_type", disabled=not local,
                     help="모르면 IP·포트를 넣고 아래 '🔎 DB 종류 자동 확인'을 누르세요(포트로도 짐작: 1433 = MS SQL Server, 1521 = Oracle, 5432 = PostgreSQL, 3306 = MySQL·MariaDB).")
    drivers = L.DB_TYPES[t]["drivers"]
    drv = a2.selectbox("접속 드라이버", list(drivers), format_func=lambda k: drivers[k], disabled=not local or len(drivers) < 2,
                       index=list(drivers).index(c0["driver"]) if c0.get("driver") in drivers else 0, key=f"ldb_drv_{t}")
    if t == "sqlite":
        db_name = st.text_input("DB 파일 경로", c0["database"] if c0["type"] == "sqlite" else str(lims.LIMS_DEMO_DB),
                                key="ldb_sqlite", disabled=not local, help="연습용: 데모 LIMS DB(data/lims_demo.db)로 표 고르기·매칭을 미리 해 볼 수 있습니다.")
        ip = host = user = ""
        port, omode = 0, "service"
        from pathlib import Path
        if Path(db_name) == lims.LIMS_DEMO_DB and not lims.LIMS_DEMO_DB.exists() and st.button("연습용 데모 LIMS DB 만들기"):
            from .store import load_raw
            info = lims.create_demo_lims(load_raw())
            st.success(f"만들었습니다: 시료 {info['samples']}건 · 결과 {info['results']}건 — 표 'V_QC_RESULT'(결과 뷰)로 연습하세요.")
    else:
        b1, b2, b3 = st.columns([1.2, 1.4, 0.7])
        ip = b1.text_input("IP 주소", c0["ip"], placeholder="예: 10.20.30.40", key="ldb_ip", disabled=not local)
        host = b2.text_input("호스트 이름(host)", c0["host"], placeholder="예: LIMS-DB01 또는 lims.company.local", key="ldb_host",
                             disabled=not local, help="MS SQL Server 이름 있는 인스턴스는 '서버\\인스턴스' 대신 포트 번호를 쓰세요.")
        default_port = c0["port"] if c0["type"] == t and c0.get("port") else L.DB_TYPES[t]["port"]
        pkw = {} if f"ldb_port_{t}" in ss else {"value": int(default_port)}
        port = b3.number_input("포트", 1, 65535, **pkw, key=f"ldb_port_{t}", disabled=not local)
        k1, k2 = st.columns([1, 2.2], vertical_alignment="center")
        if k1.button("🔎 DB 종류 자동 확인", width="stretch", disabled=not (ip.strip() or host.strip()),
                     help="아이디·비밀번호 없이 IP(또는 호스트)·포트만으로 서버에 물어 DB 종류와 버전을 알아냅니다."):
            with st.spinner("서버에 확인 중…"):
                det = L.detect_type(ip.strip() or host.strip(), int(port))
            if det["type"] and det["type"] != t:
                ss["ldb_type_next"], ss["ldb_port_next"] = det["type"], int(port)
                ss["ldb_detect"] = (ip.strip() or host.strip(), int(port), det["msg"] + " — DB 종류를 자동으로 바꿨습니다.", True)
                st.rerun()
            ss["ldb_detect"] = (ip.strip() or host.strip(), int(port), det["msg"], bool(det["type"]))
        shown = ss.get("ldb_detect")
        shown = shown if shown and shown[:2] == (ip.strip() or host.strip(), int(port)) else None   # 주소·포트를 바꾸면 지움
        if shown:
            (k2.success if shown[3] else k2.warning)(shown[2])
        g = L.guess_type(port)
        if g and g != t and not shown:
            st.warning(f"포트 {port} 는 보통 **{L.DB_TYPES[g]['label']}** 입니다 — DB 종류를 확인하세요(🔎 자동 확인).")
        d1, d2 = st.columns([1.6, 1])
        lab = {"mssql": "데이터베이스 이름(모르면 비우고 아래 'DB 목록 불러오기')", "oracle": "서비스 이름(또는 SID)",
               "postgresql": "데이터베이스 이름(모르면 비우고 'DB 목록 불러오기')", "mysql": "데이터베이스 이름(모르면 비우고 'DB 목록 불러오기')"}[t]
        db_name = d1.text_input(lab, c0["database"] if c0["type"] == t else "", key=f"ldb_db_{t}_{ss.get('ldb_db_v', 0)}", disabled=not local,
                                placeholder={"oracle": "예: ORCL, LIMSPDB"}.get(t, "예: LIMS"))
        if t == "oracle":
            omode = d2.radio("Oracle 접속 방식", ["service", "sid"], horizontal=True, key="ldb_omode", disabled=not local,
                             index=0 if c0.get("oracle_mode", "service") == "service" else 1,
                             format_func=lambda m: {"service": "서비스 이름", "sid": "SID"}[m])
        else:
            omode = "service"
        e1, e2 = st.columns(2)
        user = e1.text_input("아이디", c0["user"] if c0["type"] == t else c0["user"], key="ldb_user", disabled=not local,
                             help="LIMS 담당자에게 **읽기 전용 계정**을 요청하는 것을 권장합니다.")
    src_label = lims.secret_source("password")
    if t != "sqlite":
        pw_new = e2.text_input("비밀번호", type="password", key=f"ldb_pw_{ss.get('ldb_pw_v', 0)}", disabled=not local,
                               placeholder="저장됨 — 바꿀 때만 입력" if src_label else "비밀번호 입력",
                               help="암호화해 저장합니다: " + SS.method_label())
    else:
        pw_new = ""
    odbc = c0.get("odbc_driver") or L.ODBC_DEFAULT
    if t == "mssql" and drv == "pyodbc":
        odbc = st.text_input("ODBC 드라이버 이름", odbc, key="ldb_odbc", disabled=not local,
                             help="Windows 'ODBC 데이터 원본 관리자 → 드라이버' 탭의 이름(예: ODBC Driver 17 for SQL Server, SQL Server)")
    conn = {"type": t, "ip": ip.strip(), "host": host.strip(), "port": int(port), "database": db_name.strip(), "user": user.strip(),
            "driver": drv, "odbc_driver": odbc, "oracle_mode": omode}
    ss["ldb_form_conn"] = conn
    st.caption(f"🔐 비밀번호: {src_label or '없음'}" + (f" · 저장 방식 {SS.method_label()}" if src_label.startswith("화면") else ""))

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("💾 접속 정보 저장", type="primary", disabled=not local, width="stretch"):
        if t != "sqlite" and not (conn["ip"] or conn["host"]):
            st.error("IP 주소 또는 호스트 이름을 입력하세요.")
        else:
            if pw_new:
                SS.set_secret(lims.STORE_NAMES["password"], pw_new)
            cfg.db, cfg.mode = conn, "db"
            lims.save_lims_config(cfg)
            ss["ldb_pw_v"] = ss.get("ldb_pw_v", 0) + 1          # 입력칸 비우기(위젯 키를 바꿔 새로 만듦)
            _clear_browse_cache()
            st.success("저장했습니다." + (" 비밀번호는 암호화해 저장했습니다." if pw_new else ""))
            st.rerun()
    if c2.button("🩺 연결 확인", width="stretch", help="주소 → 포트 → 드라이버 → 로그인 → 읽기 권한 순서로 확인합니다(저장 전 입력값으로)."):
        with st.spinner("연결 확인 중…(최대 10~20초)"):
            ss["ldb_diag"] = L.diagnose(conn, pw_new or _pw())
        if ss["ldb_diag"] and all(x["ok"] for x in ss["ldb_diag"]) and local:      # 연결에 성공하면 그 정보를 바로 저장
            if pw_new:
                SS.set_secret(lims.STORE_NAMES["password"], pw_new)
                ss["ldb_pw_v"] = ss.get("ldb_pw_v", 0) + 1
            changed = cfg.db != conn or bool(pw_new)
            cfg.db, cfg.mode = conn, "db"
            lims.save_lims_config(cfg)
            if changed:
                _clear_browse_cache()
            ss["ldb_diag_saved"] = True
            st.rerun()
    if c3.button("📚 DB 목록 불러오기", width="stretch", disabled=t in ("oracle", "sqlite")):
        try:
            with st.spinner("DB 목록을 읽는 중…"):
                ss["ldb_dblist"] = L.list_databases(conn, pw_new or _pw())
            if not ss["ldb_dblist"]:
                st.info("보이는 DB가 없습니다(권한 확인).")
        except Exception as exc:  # noqa: BLE001
            m = L.sanitize(f"{type(exc).__name__}: {exc}", pw_new or _pw())
            st.error((L.explain(m) + " · " if L.explain(m) else "") + m)
    if c4.button("🗑 저장된 비밀번호 지우기", width="stretch", disabled=not local or not src_label.startswith(("화면", "저장"))):
        SS.delete_secret(lims.STORE_NAMES["password"])
        st.rerun()
    if ss.get("ldb_diag"):
        _steps_table(ss["ldb_diag"])
        if all(x["ok"] for x in ss["ldb_diag"]):
            if ss.pop("ldb_diag_saved", False):
                st.success("연결에 성공해 접속 정보를 저장했습니다" + (" (비밀번호는 암호화 저장)" if lims.secret_source("password") else "") + ".")
            st.info("다음: **② 가져올 곳·항목 매칭** 탭 → **🧭 자동으로 찾기**를 누르세요. 결과가 들어 있을 표를 자동으로 찾아 줍니다.")
    if ss.get("ldb_dblist"):
        p1, p2 = st.columns([2, 1], vertical_alignment="bottom")
        pick = p1.selectbox("DB 고르기", ss["ldb_dblist"], key="ldb_dbpick")
        if p2.button("이 DB 사용", disabled=not local, width="stretch"):
            conn["database"] = pick
            if pw_new:
                SS.set_secret(lims.STORE_NAMES["password"], pw_new)
                ss["ldb_pw_v"] = ss.get("ldb_pw_v", 0) + 1
            cfg.db, cfg.mode = conn, "db"
            lims.save_lims_config(cfg)
            ss["ldb_db_v"] = ss.get("ldb_db_v", 0) + 1
            ss.pop("ldb_dblist", None)
            st.rerun()


# ── ② 가져올 곳(소스) ────────────────────────────────────────────────────
def _new_draft() -> dict:
    return {"orig": None, "name": "", "database": None, "schema": None, "table": None, "layout": None, "cols": {}, "fixed_table": None,
            "item_cols": [], "filter_col": "", "filter_values": "", "date_format": None, "updated_format": None,
            "mapping": [], "ship_map": {}, "enabled": True}


def _draft_from(src: dict) -> dict:
    d = {**_new_draft(), **{k: v for k, v in src.items() if k != "watermark"}}
    d["orig"] = src.get("name")
    fsp = src.get("fixed_sample_point")
    d["fixed_table"] = next((t for t, code in lims.SAMPLE_POINTS.items() if code == fsp), None) if fsp else None
    return d


def _cached(key: str, fn):
    ss = st.session_state
    if key not in ss:
        ss[key] = fn()
    return ss[key]


LAYOUT_SHORT = {"long": "긴 형식", "wide": "가로형", "ship": "출하시멘트"}


def _loc(r) -> str:
    return ".".join(x for x in (r.get("database"), r.get("schema"), r.get("table")) if x)


def _explorer(cfg: lims.LimsConfig, pw: str) -> None:
    """🧭 결과 표 자동으로 찾기 — DB 구조를 몰라도 후보 표를 순위로 보여 주고 바로 시작."""
    ss = st.session_state
    t = cfg.db.get("type")
    with st.container(border=True):
        st.markdown("**🧭 결과 표 자동으로 찾기** — LIMS DB 구조를 몰라도 됩니다. 볼 수 있는 표·뷰를 모두 훑어 "
                    "**시험 결과가 들어 있을 가능성이 높은 표**를 순서대로 보여 줍니다(표·열 이름만 읽음, 데이터는 바꾸지 않음).")
        e1, e2, e3 = st.columns([1.1, 1.2, 2.2], vertical_alignment="center")
        multi = t in ("mssql", "postgresql")
        all_dbs = e2.checkbox("모든 DB에서 찾기", value=multi and not cfg.db.get("database"), disabled=not multi, key="ldb_all_dbs",
                              help="접속 계정이 들어갈 수 있는 DB를 모두 찾습니다(MS SQL Server·PostgreSQL).")
        if e1.button("🧭 자동으로 찾기", type="primary", width="stretch"):
            bar = st.progress(0.0, text="DB 구조를 읽는 중…")
            res = L.explore(cfg.db, pw, all_dbs=all_dbs,
                            progress=lambda i, n, db: bar.progress(min(1.0, i / max(n, 1)), text=f"{db or '접속한 DB'} 읽는 중… ({i}/{n})"))
            bar.empty()
            ss["ldb_explore"] = res
            ss.pop("ldb_find", None)
            ss.pop("ldb_struct_xlsx", None)
        res = ss.get("ldb_explore")
        if not res:
            e3.caption("처음이면 이 버튼부터 누르세요. 결과에서 표를 골라 '▶ 이 표로 시작'을 누르면 아래 단계가 자동으로 채워집니다.")
            return
        for e in res["errors"][:5]:
            st.warning(e)
        cand = res["candidates"]
        if cand.empty:
            st.error("읽을 수 있는 표·뷰가 없습니다 — 접속 계정의 읽기(SELECT) 권한을 LIMS 담당자에게 확인하세요.")
            return
        top = cand[cand["score"] > 0].head(15)
        if top.empty:
            st.warning("시험 결과처럼 보이는 표를 찾지 못했습니다 — 아래 '이름·값으로 찾기'나 직접 고르기를 쓰세요.")
            top = cand.head(15)
        e3.caption(f"표·뷰 {len(cand)}개를 확인했습니다" + (f"(DB {len(res['databases'])}개: {', '.join(res['databases'][:5])})"
                                                      if res["databases"] else "") + ". 점수가 높을수록 결과 표일 가능성이 큽니다.")
        recs = top.to_dict("records")
        st.dataframe(pd.DataFrame([{"순위": i, "위치(DB.스키마.표)": _loc(r), "종류": r["kind"], "추정 형식": LAYOUT_SHORT.get(r["layout"], r["layout"]),
                                    "점수": r["score"], "근거": r["reasons"]} for i, r in enumerate(recs, 1)]),
                     hide_index=True, width="stretch", height=min(38 * len(recs) + 40, 420),
                     column_config={"점수": st.column_config.ProgressColumn(min_value=0, max_value=max(30, int(top["score"].max())),
                                                                          format="%d")})
        p1, p2 = st.columns([3, 1], vertical_alignment="bottom")
        pick = p1.selectbox("시작할 표", list(range(len(recs))), key="ldb_exp_pick",
                            format_func=lambda i: f"{i + 1}. {_loc(recs[i])} — {LAYOUT_SHORT.get(recs[i]['layout'], '')}")
        if p2.button("▶ 이 표로 시작", type="primary", width="stretch"):
            r = recs[pick]
            ss["ldb_start"] = {"database": r["database"] or None, "schema": r["schema"] or None, "table": r["table"], "layout": r["layout"]}
            ss["ldb_src_pick_next"] = "➕ 새로 추가"
            st.rerun()
        with st.expander("🔤 이름·값으로 찾기 — 예: Blaine, 28일, CaO, 클링커, 선박 이름"):
            q1, q2 = st.columns([3, 1], vertical_alignment="bottom")
            term = q1.text_input("찾을 말", key="ldb_find_term", placeholder="예: Blaine")
            if q2.button("찾기", width="stretch", disabled=not term.strip()):
                with st.spinner("열 이름과 값을 찾는 중…(상위 후보 표만)"):
                    ss["ldb_find"] = L.find_term(cfg.db, pw, res["catalog"], cand, term)
            fd = ss.get("ldb_find")
            if fd is not None:
                if fd.empty:
                    st.info("찾지 못했습니다 — 다른 말(영문 코드·한글 이름)로 찾아보세요.")
                else:
                    st.dataframe(fd, hide_index=True, width="stretch")
                    st.caption("'값'에서 찾은 표는 시험항목 이름이 행에 들어 있는 **긴 형식**, '열 이름'에서 찾은 표는 **가로형**일 가능성이 큽니다.")
        with st.expander("📄 LIMS DB 구조를 엑셀로 받기 — LIMS 담당자와 함께 보거나 지원 요청할 때"):
            inc = st.checkbox("추천 상위 5개 표의 예시 데이터 5행 포함(실제 데이터가 들어갑니다)", value=False, key="ldb_struct_inc")
            if st.button("엑셀 만들기", key="ldb_struct_btn"):
                samples = {}
                if inc:
                    for r in recs[:5]:
                        try:
                            samples[_loc(r)] = L.preview(cfg.db, pw, r["schema"] or None, r["table"], 5, r["database"] or None)
                        except Exception:  # noqa: BLE001
                            continue
                ss["ldb_struct_xlsx"] = L.structure_workbook(res, samples)
            if ss.get("ldb_struct_xlsx"):
                st.download_button("⬇️ LIMS_DB_구조.xlsx 내려받기", ss["ldb_struct_xlsx"], file_name="LIMS_DB_구조.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.caption("표 목록·열 목록·역할/시험항목 추정이 들어 있습니다. 비밀번호·접속 정보는 들어가지 않습니다.")


def sources_panel(cfg: lims.LimsConfig, registry) -> None:
    ss = st.session_state
    pw = _pw()
    if not (cfg.db or {}).get("type") or (cfg.db.get("type") != "sqlite" and not L.server_of(cfg.db)):
        st.info("먼저 **① 연결 설정**에서 LIMS DB 접속 정보를 저장하세요.")
        return
    st.markdown("##### 📋 가져올 곳(표·뷰)과 항목 매칭")
    st.caption("LIMS DB에서 **어느 표(뷰)의 어떤 열을 어떤 QMS 항목으로** 가져올지 지정합니다. 표가 여러 개면 가져올 곳을 여러 개 만드세요"
               "(예: 원료·클링커 결과 뷰, 물성 시험 표, 출하시멘트 성적 표). 저장한 뒤 **④ 동기화 실행**에서 반영합니다.")
    if cfg.sources:
        rows = [{"사용": "✅" if s.get("enabled", True) else "—", "이름": s.get("name"),
                 "표": f"{s.get('schema') + '.' if s.get('schema') else ''}{s.get('table')}",
                 "형식": {"long": "긴 형식", "wide": "가로형", "ship": "출하시멘트"}.get(s.get("layout"), s.get("layout")),
                 "매칭 항목": len(s.get("ship_map") or {}) if s.get("layout") == "ship" else len(s.get("mapping") or []),
                 "증분 기준": "확정일시" if (s.get("cols") or {}).get("updated_at") else "최근 N일 채취분",
                 "워터마크": s.get("watermark") or "—"} for s in cfg.sources]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    names = [s.get("name") for s in cfg.sources]
    form = ss.get("ldb_form_conn")
    keys = ("type", "ip", "host", "port", "database", "user", "driver", "oracle_mode")
    if form and any(str(form.get(k) or "") != str((cfg.db or {}).get(k) or "") for k in keys if k in form):
        st.warning("① 연결 설정에서 바꾼 접속 정보가 **아직 저장되지 않았습니다**. 여기서는 저장된 정보로 접속합니다 — "
                   "① 탭에서 **🩺 연결 확인**(성공하면 자동 저장) 또는 **💾 접속 정보 저장**을 먼저 하세요.")
    c = cfg.db
    st.caption(f"사용 중인 접속: {L.DB_TYPES.get(c.get('type'), {}).get('label', c.get('type'))} · "
               + (f"{L.server_of(c)}:{c.get('port')} · DB {c.get('database') or '(지정 안 함 — 아래에서 고르거나 자동으로 찾기)'} · 아이디 {c.get('user')}"
                  if c.get("type") != "sqlite" else str(c.get("database"))))
    _explorer(cfg, pw)

    if "ldb_src_pick_next" in ss:                       # 저장·삭제·자동 찾기 직후 선택 바꾸기(위젯 생성 전에만 바꿀 수 있음)
        ss["ldb_src_pick"] = ss.pop("ldb_src_pick_next")
    choice = st.selectbox("편집할 가져올 곳", ["➕ 새로 추가", *names], key="ldb_src_pick",
                          help="저장해 둔 가져올 곳을 고르면 그 설정을 불러와 고칠 수 있습니다.")
    start = ss.pop("ldb_start", None)
    if start or ss.get("ldb_draft") is None or ss.get("ldb_draft_for") != choice:
        src = next((s for s in cfg.sources if s.get("name") == choice), None)
        ss["ldb_draft"] = _draft_from(src) if src and not start else _new_draft()
        if start:
            ss["ldb_draft"].update(start, name=start["table"], auto_codes=True)
        ss["ldb_draft_for"] = choice
        ss["ldb_draft_rev"] = ss.get("ldb_draft_rev", 0) + 1
        for k in [k for k in ss if str(k).startswith(("ldb_cols_", "ldb_prev_", "ldb_codes_"))]:
            ss.pop(k, None)
    d = ss["ldb_draft"]
    rev = ss["ldb_draft_rev"]

    # 1) 표 고르기
    st.markdown("**1. 표(뷰) 고르기** — 위 🧭 자동 찾기에서 '이 표로 시작'을 누르면 채워집니다. 직접 골라도 됩니다.")
    dbs: list[str] = []
    if c.get("type") in ("mssql", "postgresql"):
        try:
            dbs = _cached("ldb_dbs", lambda: L.list_databases(c, pw))
        except Exception:  # noqa: BLE001 - DB 목록 권한이 없으면 접속 DB만
            dbs = []
    cur_db = d.get("database") or c.get("database") or ""
    if dbs:
        db_opts = dbs if (not cur_db or cur_db in dbs) else [cur_db, *dbs]
        s0, s1, s2, s3 = st.columns([1, 1, 1, 2])
        db = s0.selectbox("데이터베이스", db_opts, index=db_opts.index(cur_db) if cur_db in db_opts else 0, key=f"ldb_dbsel_{rev}")
    else:
        db = cur_db
        s1, s2, s3 = st.columns([1, 1, 2])
    try:
        schemas, default = _cached(f"ldb_schemas_{db}", lambda: L.list_schemas(c, pw, db or None))
    except Exception as exc:  # noqa: BLE001
        m = L.sanitize(f"{type(exc).__name__}: {exc}", pw)
        st.error("DB에 접속하지 못했습니다 — " + (L.explain(m) + " · " if L.explain(m) else "") + m)
        if st.button("다시 시도"):
            for k in [k for k in ss if str(k).startswith(("ldb_schemas", "ldb_dbs"))]:
                ss.pop(k, None)
            st.rerun()
        return
    sch_opts = schemas or [None]
    sch = s1.selectbox("스키마(소유자)", sch_opts, key=f"ldb_sch_{rev}_{db}",
                       index=sch_opts.index(d["schema"]) if d.get("schema") in sch_opts else
                       (sch_opts.index(default) if default in sch_opts else 0),
                       format_func=lambda x: f"{x}{' (기본)' if x == default else ''}" if x else "(기본)")
    flt = s2.text_input("이름 검색", key=f"ldb_flt_{rev}", placeholder="예: RESULT, 성적")
    try:
        objs = _cached(f"ldb_objects_{db}_{sch}", lambda: L.list_objects(c, pw, sch, db or None))
    except Exception as exc:  # noqa: BLE001
        st.error(L.sanitize(f"표 목록을 읽지 못했습니다 — {exc}", pw))
        return
    view = objs[objs["이름"].str.contains(flt, case=False, regex=False)] if flt else objs
    if view.empty:
        st.info("이 스키마에 보이는 표·뷰가 없습니다. 위 **🧭 자동으로 찾기**를 누르거나, 데이터베이스·스키마를 바꾸거나, 검색어를 지우세요.")
        return
    opts = list(view["이름"])
    kinds = dict(zip(objs["이름"], objs["종류"]))
    if st.button("목록 새로 고침", key=f"ldb_reload_{rev}"):
        for k in [k for k in ss if str(k).startswith(("ldb_schemas", "ldb_objects_", "ldb_dbs"))]:
            ss.pop(k, None)
        st.rerun()
    tbl = s3.selectbox(f"표·뷰 ({len(view)}개)", opts, index=opts.index(d["table"]) if d.get("table") in opts else 0,
                       format_func=lambda n: f"{n}  ·  {kinds.get(n, '')}", key=f"ldb_tbl_{rev}_{db}_{sch}")
    if (d.get("database") or "", d.get("schema"), d.get("table")) != (db or "", sch, tbl):
        if d.get("name") in (None, "", d.get("table")):          # 이름을 직접 바꾸지 않았으면 표 이름을 따라감
            d["name"] = tbl
        keep_layout = d.get("table") == tbl and d.get("layout")
        d.update(database=db or None, schema=sch, table=tbl, cols={} if not keep_layout else d.get("cols", {}),
                 layout=d.get("layout") if keep_layout else None, item_cols=[],
                 mapping=[] if d.get("orig") is None else d["mapping"], ship_map={}, date_format=None, updated_format=None)
        if not d.get("name"):
            d["name"] = tbl
    try:
        cols_df = _cached(f"ldb_cols_{db}_{sch}_{tbl}", lambda: L.get_columns(c, pw, sch, tbl, db or None))
        prev = _cached(f"ldb_prev_{db}_{sch}_{tbl}", lambda: L.preview(c, pw, sch, tbl, 20, db or None))
    except Exception as exc:  # noqa: BLE001
        m = L.sanitize(f"{type(exc).__name__}: {exc}", pw)
        st.error("표를 읽지 못했습니다 — " + (L.explain(m) + " · " if L.explain(m) else "") + m)
        return
    cols = list(cols_df["열"])
    with st.expander(f"미리보기 — {tbl} 처음 {len(prev)}행 · 열 {len(cols)}개", expanded=True):
        st.dataframe(prev.map(lambda v: "" if v is None or (isinstance(v, float) and v != v) or v is pd.NaT else str(v)),
                     hide_index=True, height=260)
        st.caption("열 자료형: " + ", ".join(f"{r.열}({str(r.자료형).split(' COLLATE')[0]})" for r in cols_df.itertuples()))

    # 2) 형식
    st.markdown("**2. 표 형식**")
    lay_opts = list(L.LAYOUTS)
    if d.get("layout") not in lay_opts:
        d["layout"] = L.guess_layout(cols)
    layout = st.radio("한 행에 무엇이 들어 있나요?", lay_opts, index=lay_opts.index(d["layout"]), format_func=lambda k: L.LAYOUTS[k],
                      key=f"ldb_layout_{rev}_{tbl}")
    if layout != d["layout"]:
        d.update(layout=layout, cols={}, mapping=[], ship_map={})
    if not d.get("cols"):
        d["cols"] = L.suggest_roles(cols, layout)

    # 3) 열 역할
    if layout == "ship":
        _ship_roles(d, cols, prev, rev)
    else:
        _roles(d, cols, prev, rev, layout)
    # 4) 항목 매칭
    if layout == "long":
        _match_long(d, cfg, pw, registry, rev)
    elif layout == "wide":
        _match_wide(d, cols, prev, registry, rev)

    # 5) 저장
    st.markdown("**5. 저장**")
    n1, n2 = st.columns([2, 1], vertical_alignment="bottom")
    d["name"] = n1.text_input("가져올 곳 이름", d.get("name") or tbl, key=f"ldb_name_{rev}_{tbl}")
    d["enabled"] = n2.toggle("동기화에 사용", d.get("enabled", True), key=f"ldb_en_{rev}")
    src = _draft_to_src(d)
    problems = _validate(src)
    if src["name"] and src["name"] != d.get("orig") and src["name"] in names:
        problems.insert(0, f"같은 이름의 가져올 곳('{src['name']}')이 이미 있습니다 — 이름을 바꾸세요(그대로 저장하면 덮어씁니다).")
    for p in problems:
        st.warning(p)
    b1, b2, b3 = st.columns(3)
    if b1.button("💾 가져올 곳 저장", type="primary", disabled=bool(problems), width="stretch"):
        others = [s for s in cfg.sources if s.get("name") not in (d.get("orig"), src["name"])]
        old = next((s for s in cfg.sources if s.get("name") == d.get("orig")), None)
        if old and old.get("watermark") and old.get("table") == src["table"]:
            src["watermark"] = old["watermark"]
        cfg.sources = others + [src]
        if cfg.mode != "db":
            cfg.mode = "db"
        lims.save_lims_config(cfg)
        ss["ldb_draft_for"] = None
        ss["ldb_src_pick_next"] = src["name"]
        st.success(f"'{src['name']}' 저장 — ④ 동기화 실행에서 반영하세요.")
        st.rerun()
    if b2.button("🔍 이 가져올 곳 미리보기(저장 안 함)", disabled=bool(problems), width="stretch"):
        tmp = replace(cfg, sources=[{**src, "enabled": True}])
        with st.spinner("LIMS에서 읽는 중…"):
            rep = lims._sync_db(tmp, lims.DB_PATH, True, None, lims.LIMS_LOG_PATH, False, only=src["name"])
        show_report(rep, preview=True)
    if d.get("orig") and b3.button("🗑 이 가져올 곳 삭제", width="stretch"):
        cfg.sources = [s for s in cfg.sources if s.get("name") != d["orig"]]
        lims.save_lims_config(cfg)
        ss["ldb_draft_for"] = None
        ss["ldb_src_pick_next"] = "➕ 새로 추가"
        st.rerun()


def _sel(label, options, current, key, help=None, container=st):
    opts = [NONE, *options]
    return container.selectbox(label, opts, index=opts.index(current) if current in opts else 0, key=key, help=help)


def _date_fmt(d, prev, col, key, label, container=st):
    cur = d.get(key) or (L.guess_date_format(prev[col]) if col in prev else "datetime")
    opts = list(DATE_FORMATS)
    v = container.selectbox(label, opts, index=opts.index(cur) if cur in opts else 0, format_func=lambda k: DATE_FORMATS[k],
                            key=f"ldb_{key}_{st.session_state['ldb_draft_rev']}_{col}",
                            help="자동으로 알아낸 저장 형식입니다. 증분 조회(이후 결과만)에 씁니다.")
    d[key] = v


def _roles(d: dict, cols: list[str], prev: pd.DataFrame, rev: int, layout: str) -> None:
    st.markdown("**3. 열 역할 지정** — 자동으로 추천한 값을 확인하고 틀리면 고치세요.")
    c = d["cols"]
    kp = f"{rev}_{d.get('schema')}_{d.get('table')}_{layout}"
    roles = L.LAYOUT_ROLES[layout]
    grid = st.columns(3)
    for i, r in enumerate(roles):
        nm, req, hlp = L.ROLES[r]
        v = _sel(nm + (" *" if req and not (r == "test_code" and layout != "long") else ""), cols, c.get(r),
                 f"ldb_role_{kp}_{r}", help=hlp or None, container=grid[i % 3])
        c[r] = None if v == NONE else v
    d["cols"] = {k: v for k, v in c.items() if v}
    if d["cols"].get("sampled_at"):
        f1, f2 = st.columns(2)
        _date_fmt(d, prev, d["cols"]["sampled_at"], "date_format", "채취 일시 저장 형식", f1)
        if d["cols"].get("updated_at"):
            _date_fmt(d, prev, d["cols"]["updated_at"], "updated_format", "확정·수정 일시 저장 형식", f2)
    need_fixed = layout == "wide" or not d["cols"].get("sample_point")
    if need_fixed:
        g1, _ = st.columns(2)
        opts = [None, *QMS_TABLES]
        ft = g1.selectbox("이 표의 시료 종류(QMS) *" if layout == "wide" else "시료 종류(채취 지점 열이 없을 때) *", opts,
                          index=opts.index(d.get("fixed_table")) if d.get("fixed_table") in opts else 0,
                          format_func=lambda t: TABLES[t]["label"] if t else "— 고르세요 —", key=f"ldb_ft_{kp}")
        d["fixed_table"] = ft
    else:
        d["fixed_table"] = None
    with st.expander("조건(선택) — 한 표에 여러 공장·시료가 섞여 있을 때 특정 값만 가져오기"):
        h1, h2 = st.columns(2)
        fc = _sel("조건 열", cols, d.get("filter_col"), f"ldb_fc_{kp}", container=h1)
        d["filter_col"] = "" if fc == NONE else fc
        d["filter_values"] = h2.text_input("값(쉼표로 여러 개)", d.get("filter_values", ""), key=f"ldb_fv_{kp}",
                                           placeholder="예: P1 또는 CLK,CLINKER")


def _ship_roles(d: dict, cols: list[str], prev: pd.DataFrame, rev: int) -> None:
    st.markdown("**3·4. 출하시멘트 항목 ↔ DB 열 매칭** — 엑셀 업로드와 같은 규칙(0 = 미시험, 비고 = 선박명, '저염' 표시)으로 해석합니다.")
    if not d.get("ship_map"):
        idx = S.match_headers(cols)
        d["ship_map"] = {k: cols[j] for k, j in idx.items()}
    fields = [("date", "채취일 *"), ("lot", "LOT 번호"), ("additive", "첨가재명칭"), ("ships", "비고(선박명)")] + \
             [(it.key, f"{it.name}{' (' + it.unit + ')' if it.unit else ''}") for it in S.ITEMS]
    ed = pd.DataFrame([{"key": k, "출하시멘트 항목": nm, "DB 열": d["ship_map"].get(k) or NONE} for k, nm in fields])
    out = st.data_editor(ed, hide_index=True, key=f"ldb_shipmap_{rev}_{d.get('table')}", width="stretch", height=min(36 * len(ed) + 40, 520),
                         column_config={"key": None, "출하시멘트 항목": st.column_config.TextColumn(disabled=True),
                                        "DB 열": st.column_config.SelectboxColumn(options=[NONE, *cols], required=True)})
    d["ship_map"] = {r["key"]: r["DB 열"] for _, r in out.iterrows() if r["DB 열"] and r["DB 열"] != NONE}
    dcol = d["ship_map"].get("date")
    d["cols"] = {k: v for k, v in (d.get("cols") or {}).items() if k == "updated_at"}
    f1, f2 = st.columns(2)
    if dcol:
        _date_fmt(d, prev, dcol, "date_format", "채취일 저장 형식", f1)
    up = _sel("결과 확정·수정 일시(선택, 증분 조회)", cols, d["cols"].get("updated_at"), f"ldb_shipupd_{rev}_{d.get('table')}", container=f2)
    d["cols"] = {"updated_at": up} if up != NONE else {}


def _match_long(d: dict, cfg: lims.LimsConfig, pw: str, registry, rev: int) -> None:
    ss = st.session_state
    st.markdown("**4. 시험항목 ↔ QMS 항목 매칭**")
    if not (d["cols"].get("test_code") and d["cols"].get("value") and d["cols"].get("sampled_at")):
        st.info("3에서 채취 일시·시험항목 코드·결과값 열을 먼저 고르세요.")
        return
    if not d["cols"].get("sample_point") and not d.get("fixed_table"):
        st.info("3에서 채취 지점 열 또는 시료 종류를 고르세요.")
        return
    src = _draft_to_src(d)
    key = f"ldb_codes_{rev}"
    days = st.number_input("시험항목 목록을 볼 기간(최근 일)", 1, 365, int(cfg.lookback_days), key=f"ldb_days_{rev}")
    if st.button("📥 시험항목 목록 불러오기", key=f"ldb_loadcodes_{rev}") or (key not in ss and (d.get("mapping") or d.pop("auto_codes", False))):
        ss[f"{key}_v"] = ss.get(f"{key}_v", 0) + 1
        try:
            with st.spinner("LIMS에서 시험항목을 모으는 중…"):
                ss[key] = L.distinct_codes(cfg.db, pw, src, pd.Timestamp.now() - pd.Timedelta(days=int(days)))
        except Exception as exc:  # noqa: BLE001
            m = L.sanitize(f"{type(exc).__name__}: {exc}", pw)
            st.error((L.explain(m) + " · " if L.explain(m) else "") + m)
            return
    codes = ss.get(key)
    opts = item_options(registry)
    cur = {(str(m["sample_point"]).upper(), str(m["test_code"]).upper()): m for m in d.get("mapping") or []}
    if codes is None:
        if cur:
            codes = pd.DataFrame([{"sample_point": k[0], "test_code": k[1], "n": None} for k in cur])
        else:
            st.caption("버튼을 누르면 이 표에 실제로 있는 (채취 지점, 시험항목) 목록과 추천 매칭을 보여 줍니다.")
            return
    rows = []
    for r in codes.itertuples():
        k = (str(r.sample_point).upper(), str(r.test_code).upper())
        m = cur.get(k)
        if m:
            tgt, fac, off = f"{m['table']}.{m['column']}", m.get("factor", 1.0), m.get("offset", 0.0)
        else:
            tb = d.get("fixed_table") or guess_table(r.sample_point)
            col = L.suggest_item(tb, r.test_code)
            tgt, fac, off = (f"{tb}.{col}" if col else SKIP), 1.0, 0.0
        rows.append({"채취 지점": r.sample_point, "시험항목": r.test_code, "건수": r.n, "QMS 항목": tgt if tgt in opts or tgt == SKIP else SKIP,
                     "계수": fac, "오프셋": off})
    ed = pd.DataFrame(rows)
    n_auto = int((ed["QMS 항목"] != SKIP).sum())
    st.caption(f"시험항목 {len(ed)}개 중 {n_auto}개를 자동 추천했습니다. 가져오지 않을 항목은 '{SKIP}'로 두세요. "
               "QMS 값 = LIMS 값 × 계수 + 오프셋(단위 환산).")
    out = st.data_editor(ed, hide_index=True, key=f"ldb_map_{rev}_{d.get('table')}_{ss.get(key + '_v', 0)}", width="stretch", height=min(36 * len(ed) + 40, 560),
                         column_config={"채취 지점": st.column_config.TextColumn(disabled=True),
                                        "시험항목": st.column_config.TextColumn(disabled=True),
                                        "건수": st.column_config.NumberColumn(disabled=True, format="%d"),
                                        "QMS 항목": st.column_config.SelectboxColumn(options=[SKIP, *opts], required=True, width="large",
                                                                                   format_func=lambda k: opts.get(k, k),
                                                                                   help="표시: 시료 종류 · 항목 이름"),
                                        "계수": st.column_config.NumberColumn(format="%.4g"),
                                        "오프셋": st.column_config.NumberColumn(format="%.4g")})
    d["mapping"] = [{"sample_point": str(r["채취 지점"]).strip().upper(), "test_code": str(r["시험항목"]).strip().upper(),
                     "table": r["QMS 항목"].split(".", 1)[0], "column": r["QMS 항목"].split(".", 1)[1],
                     "factor": float(r["계수"]) if pd.notna(r["계수"]) else 1.0,
                     "offset": float(r["오프셋"]) if pd.notna(r["오프셋"]) else 0.0}
                    for _, r in out.iterrows() if r["QMS 항목"] and r["QMS 항목"] != SKIP]


def _match_wide(d: dict, cols: list[str], prev: pd.DataFrame, registry, rev: int) -> None:
    st.markdown("**4. 시험항목 열 ↔ QMS 항목 매칭**")
    tb = d.get("fixed_table")
    if not tb or not d["cols"].get("sampled_at"):
        st.info("3에서 채취 일시 열과 이 표의 시료 종류를 고르세요.")
        return
    used = set(d["cols"].values()) | {d.get("filter_col")}
    cand = [c for c in cols if c not in used]
    opts = item_options(registry, [tb])
    code = lims.SAMPLE_POINTS[tb]
    cur = {str(m["test_code"]).upper(): m for m in d.get("mapping") or []}
    rows = []
    for c in cand:
        m = cur.get(str(c).upper())
        if m:
            tgt, fac, off = f"{m['table']}.{m['column']}", m.get("factor", 1.0), m.get("offset", 0.0)
        else:
            col = L.suggest_item(tb, c)
            tgt, fac, off = (f"{tb}.{col}" if col else SKIP), 1.0, 0.0
        ex = next((str(v) for v in prev[c].tolist() if v is not None and str(v).strip() not in ("", "nan", "None")), "") if c in prev else ""
        rows.append({"DB 열": c, "예시 값": ex[:20], "QMS 항목": tgt if tgt in opts or tgt == SKIP else SKIP, "계수": fac, "오프셋": off})
    ed = pd.DataFrame(rows)
    st.caption(f"열 {len(ed)}개 중 {int((ed['QMS 항목'] != SKIP).sum())}개를 자동 추천했습니다({TABLES[tb]['label']} 항목). "
               f"시료번호·비고 같은 열은 '{SKIP}'로 두세요.")
    out = st.data_editor(ed, hide_index=True, key=f"ldb_wmap_{rev}_{tb}", width="stretch", height=min(36 * len(ed) + 40, 560),
                         column_config={"DB 열": st.column_config.TextColumn(disabled=True),
                                        "예시 값": st.column_config.TextColumn(disabled=True),
                                        "QMS 항목": st.column_config.SelectboxColumn(options=[SKIP, *opts], required=True, width="large",
                                                                                   format_func=lambda k: opts.get(k, k)),
                                        "계수": st.column_config.NumberColumn(format="%.4g"),
                                        "오프셋": st.column_config.NumberColumn(format="%.4g")})
    sel = out[out["QMS 항목"] != SKIP]
    d["item_cols"] = list(sel["DB 열"])
    d["mapping"] = [{"sample_point": code, "test_code": str(r["DB 열"]).strip().upper(), "table": r["QMS 항목"].split(".", 1)[0],
                     "column": r["QMS 항목"].split(".", 1)[1], "factor": float(r["계수"]) if pd.notna(r["계수"]) else 1.0,
                     "offset": float(r["오프셋"]) if pd.notna(r["오프셋"]) else 0.0} for _, r in sel.iterrows()]


def _draft_to_src(d: dict) -> dict:
    src = {k: d.get(k) for k in ("name", "database", "schema", "table", "layout", "cols", "item_cols", "filter_col", "filter_values",
                                 "date_format", "updated_format", "mapping", "ship_map", "enabled")}
    src["name"] = (src.get("name") or d.get("table") or "").strip()
    src["date_format"] = src.get("date_format") or "datetime"
    src["updated_format"] = src.get("updated_format") or "datetime"
    if d.get("fixed_table"):
        src["fixed_sample_point"] = lims.SAMPLE_POINTS[d["fixed_table"]]
    if src["layout"] != "wide":
        src["item_cols"] = []
    if src["layout"] != "ship":
        src["ship_map"] = {}
    return src


def _validate(src: dict) -> list[str]:
    p = []
    lay, c = src.get("layout"), src.get("cols") or {}
    if not src.get("name"):
        p.append("가져올 곳 이름을 입력하세요.")
    if lay == "ship":
        if not (src.get("ship_map") or {}).get("date"):
            p.append("출하시멘트: 채취일 열을 고르세요.")
        elif len(src["ship_map"]) < 2:
            p.append("출하시멘트: 가져올 항목 열을 하나 이상 고르세요.")
        return p
    if not c.get("sampled_at"):
        p.append("채취 일시 열을 고르세요.")
    if lay == "long":
        if not c.get("test_code") or not c.get("value"):
            p.append("긴 형식: 시험항목 코드 열과 결과값 열을 고르세요.")
        if not c.get("sample_point") and not src.get("fixed_sample_point"):
            p.append("채취 지점 열 또는 시료 종류를 고르세요.")
    if lay == "wide" and not src.get("fixed_sample_point"):
        p.append("가로형: 이 표의 시료 종류를 고르세요.")
    if not src.get("mapping"):
        p.append("4에서 QMS 항목으로 가져올 시험항목을 하나 이상 매칭하세요.")
    return p


def show_report(rep, preview: bool = False) -> None:
    (st.error if rep.errors else st.success)(("[미리보기 — 저장 안 함] " if preview else "") + rep.summary_text())
    for m in rep.messages:
        st.info(m)
    if rep.sources:
        st.dataframe(pd.DataFrame([{"가져올 곳": s["name"], "표": s.get("table"), "조회": s.get("fetched"), "반영": s.get("mapped"),
                                    "워터마크": s.get("watermark", ""), "오류": s.get("error", "")} for s in rep.sources]),
                     hide_index=True, width="stretch")
    if rep.unmapped:
        st.warning("매칭하지 않은 시험항목(가져오지 않음): " + ", ".join(f"{sp}/{tc} {n}건" for sp, tc, n in rep.unmapped[:12]))
    if rep.n_censored:
        st.caption(f"부등호 값(<, >) {rep.n_censored}건은 숫자 부분만 사용했습니다(검출한계 표시값).")
    for table, wdf in rep.wide.items():
        label = TABLES[table]["label"] if table in TABLES else "출하시멘트"
        with st.expander(f"{label} — {len(wdf)}행"):
            st.dataframe(wdf.tail(50), hide_index=True)
