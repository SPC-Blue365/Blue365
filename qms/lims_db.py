"""LIMS DB 간편 연결 — IP·호스트·포트·DB 이름·아이디·비밀번호만 입력해 접속하고, 가져올 표와 열을 화면에서 고른다.

흐름  ① 접속 정보 입력(비밀번호는 secret_store 에 암호화 저장) → ② 연결 진단(주소 → 포트 → 드라이버 → 로그인 → 권한)
      → ③ DB·스키마·표(뷰) 고르기 → 미리보기 → ④ 열 역할(채취일시·채취 지점·시험코드·결과값 …) 지정
      → ⑤ 시험항목 ↔ QMS 항목 매칭 → '가져올 곳(소스)' 으로 저장 → 동기화 때 소스마다 SELECT 만 실행
안전  조회문은 SQLAlchemy Core 로 만든 SELECT 만 실행(직접 입력한 SQL 없음), PostgreSQL·MySQL 은 읽기 전용 세션,
      오류 메시지에서 비밀번호를 지운다. LIMS DB 에는 읽기 전용 계정을 쓰는 것을 권장한다.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
from datetime import date, datetime
from urllib.parse import quote_plus

import numpy as np
import pandas as pd

from .store import RAW_COLUMNS

PW_NAME = "lims_db_password"           # secret_store 이름
MAX_ROWS = 300_000                     # 소스 1개를 한 번에 읽는 최대 행 수(넘으면 경고 — 기간을 줄이거나 확정일시 열 지정)
TIMEOUT = 10                           # 접속 대기(초)

DB_TYPES = {
    "mssql": {"label": "MS SQL Server", "port": 1433, "drivers": {"pymssql": "pymssql(추가 설치 없음, 권장)",
                                                                 "pyodbc": "pyodbc(Windows ODBC 드라이버 사용)"}},
    "oracle": {"label": "Oracle", "port": 1521, "drivers": {"oracledb": "oracledb(Thin — Oracle Client 불필요)"}},
    "postgresql": {"label": "PostgreSQL", "port": 5432, "drivers": {"psycopg2": "psycopg2"}},
    "mysql": {"label": "MySQL·MariaDB", "port": 3306, "drivers": {"pymysql": "PyMySQL"}},
    "sqlite": {"label": "연습용 데모 DB(SQLite 파일)", "port": 0, "drivers": {"sqlite": "내장"}},
}
PORT_HINT = {1433: "mssql", 1434: "mssql", 1521: "oracle", 1522: "oracle", 5432: "postgresql", 3306: "mysql", 3307: "mysql"}
DRIVER_MODULE = {"pymssql": "pymssql", "pyodbc": "pyodbc", "oracledb": "oracledb", "psycopg2": "psycopg2",
                 "pymysql": "pymysql", "sqlite": "sqlite3"}
ODBC_DEFAULT = "ODBC Driver 17 for SQL Server"

SYSTEM_SCHEMAS = {
    "information_schema", "pg_catalog", "pg_toast", "sys", "guest", "mysql", "performance_schema",
    "db_owner", "db_accessadmin", "db_securityadmin", "db_ddladmin", "db_backupoperator", "db_datareader",
    "db_datawriter", "db_denydatareader", "db_denydatawriter",
    "system", "outln", "dbsnmp", "appqossys", "xdb", "ctxsys", "mdsys", "ordsys", "ordplugins", "orddata", "olapsys",
    "wmsys", "exfsys", "lbacsys", "dvsys", "dvf", "gsmadmin_internal", "ojvmsys", "audsys", "dbsfwuser",
    "remote_scheduler_agent", "gsmcatuser", "sysbackup", "sysdg", "syskm", "sysrac", "anonymous", "xs$null", "gsmuser",
    "mddata", "si_informtn_schema", "flows_files", "apex_public_user", "spatial_csw_admin_usr", "spatial_wfs_admin_usr",
    "dip", "oracle_ocm", "ggsys", "dgpdb_int", "pdbadmin", "sysman", "mgmt_view", "scott", "baassys", "ggsharedcap",
    "sys$umf", "vecsys", "dbsfwuser", "gsmrootuser", "opsg_admin", "sysbackup", "c##dbaas",
}

# ── 열 역할 ─────────────────────────────────────────────────────────────
ROLES = {   # 키: (화면 이름, 필수 여부, 설명)
    "sampled_at": ("채취 일시", True, "시료를 채취한 날짜(·시각)"),
    "time": ("채취 시각(따로 있을 때)", False, "날짜와 시각이 다른 열에 있으면 시각 열"),
    "sample_point": ("채취 지점·시료 구분", False, "KILN_FEED·CLINKER 처럼 시료 종류를 나타내는 열(없으면 아래에서 시료 종류를 고정)"),
    "test_code": ("시험항목 코드", True, "긴 형식 — 시험항목 이름·코드가 든 열"),
    "value": ("결과값", True, "긴 형식 — 시험 결과 숫자가 든 열"),
    "product": ("품종", False, "OPC·HES·1종·3종 등(시멘트·물성 결과에 필요)"),
    "status": ("결과 상태", False, "승인·확정 여부(지정하면 승인된 결과만 반영)"),
    "unit": ("단위", False, ""),
    "updated_at": ("결과 확정·수정 일시", False, "지정하면 그 이후 바뀐 결과만 조회(권장). 없으면 최근 N일 채취분을 매번 다시 읽음"),
}
ROLE_ALIASES = {
    "sampled_at": ("채취일시", "시료채취일시", "채취일", "채취일자", "시료채취일", "채취날짜", "sampledat", "sampledate", "sampledt",
                   "smpdt", "smpdate", "sampletime", "sampledatetime", "collectdate", "collectiondate", "samplingdate",
                   "samplingdt", "시료일시", "시험일시", "시험일", "접수일시", "date", "dt"),
    "time": ("채취시각", "채취시간", "시료채취시각", "smptm", "smptime", "sampletm", "samplinghour", "time", "tm"),
    "sample_point": ("채취지점", "채취장소", "채취지점코드", "시료지점", "시료구분", "시료종류", "시료유형", "samplepoint", "smppt",
                     "smppoint", "sampletype", "smptype", "samplelocation", "location", "point", "spoint"),
    "test_code": ("시험항목코드", "시험코드", "항목코드", "시험항목", "시험항목명", "항목", "항목명", "testcode", "itemcode", "itemcd",
                  "testitem", "analyte", "paramcode", "parameter", "testcd", "item"),
    "value": ("결과값", "시험결과", "결과", "측정값", "분석값", "값", "resultvalue", "result", "value", "val", "rslt", "rsltval",
              "numvalue"),
    "product": ("품종", "품종코드", "제품", "제품코드", "품명", "product", "productcode", "prodcd", "prod", "grade"),
    "status": ("결과상태", "승인상태", "상태", "진행상태", "status", "stat", "resultstatus", "apprstat", "apprstatus"),
    "unit": ("단위", "unit", "uom"),
    "updated_at": ("승인일시", "확정일시", "결과확정일시", "결과승인일시", "수정일시", "변경일시", "최종수정일시", "approvedat",
                   "approvaldate", "apprdt", "approvedt", "updatedat", "updatedt", "updatedate", "moddate", "moddt",
                   "lastupdate", "lastupdated", "modifieddate", "updtdt", "approveddt", "approvaldt", "approveddate", "confirmdt",
                   "confirmdate", "confdt", "finaldt", "resultdt", "판정일시", "검토일시"),
}
LAYOUTS = {"long": "긴 형식 — 한 행에 시험 결과 1개(시험항목 코드 열 + 결과값 열)",
           "wide": "가로형 — 한 행에 시료 1개(시험항목이 열로 나열됨)",
           "ship": "출하시멘트 성적(가로형) → 🚢 출하시멘트 화면으로"}
LAYOUT_ROLES = {"long": ["sampled_at", "time", "sample_point", "test_code", "value", "product", "status", "unit", "updated_at"],
                "wide": ["sampled_at", "time", "product", "status", "updated_at"],
                "ship": ["updated_at"]}

# ── 시험항목 이름 → 표준 시험코드(자동 추천용) ─────────────────────────────
CODE_ALIASES = {
    "CAO": ("cao", "산화칼슘"), "SIO2": ("sio2", "이산화규소"), "AL2O3": ("al2o3", "산화알루미늄"), "FE2O3": ("fe2o3", "산화철"),
    "MGO": ("mgo", "산화마그네슘"), "SO3": ("so3", "so3xrf", "삼산화황"), "K2O": ("k2o",), "NA2O": ("na2o",),
    "LOI": ("loi", "강열감량", "igloss", "ignitionloss", "ig"), "R90": ("r90", "90um", "90um잔사", "90um잔분", "잔사90"),
    "R200": ("r200", "200um", "200um잔사", "200um잔분"), "R45": ("r45", "45um", "45um잔사", "45um잔분", "잔사45"),
    "FCAO": ("fcao", "freecao", "freelime", "flime", "유리석회", "fcaoxrd"), "LW": ("lw", "리터중량", "literweight", "litreweight"),
    "ALITE": ("alite", "c3s"), "BELITE": ("belite", "c2s"), "C3A": ("c3a",), "C4AF": ("c4af",), "PERICLASE": ("periclase",),
    "CR_TOTAL": ("crtotal", "totalcr", "총크롬", "cr"), "CR6": ("cr6", "crvi", "6가크롬", "육가크롬", "cr6plus"),
    "BLAINE": ("blaine", "분말도", "비표면적", "blainecm2g"), "LS_ADD": ("lsadd", "석회석", "석회석비율", "석회석첨가량", "ls"),
    "IST": ("ist", "초결", "초결시간", "initialset", "initialsetting"), "FST": ("fst", "종결", "종결시간", "finalset", "finalsetting"),
    "AUTOCLAVE": ("autoclave", "오토클레이브", "안정도", "오토클레이브팽창도"),
    "CS1": ("cs1", "s1", "1일강도", "압축강도1일", "강도1일", "1d", "1day"), "CS3": ("cs3", "s3", "3일강도", "압축강도3일", "강도3일", "3d"),
    "CS7": ("cs7", "s7", "7일강도", "압축강도7일", "강도7일", "7d"), "CS28": ("cs28", "s28", "28일강도", "압축강도28일", "강도28일", "28d"),
    "LAB_TEMP": ("labtemp", "실험실온도", "시험실온도"), "LAB_RH": ("labrh", "실험실습도", "시험실습도", "습도"),
    "CURE_TEMP": ("curetemp", "양생온도", "양생수온도"), "SAND_LOT": ("sandlot", "표준사lot", "표준사"), "OPERATOR": ("operator", "시험조", "시험자"),
}


def norm(s) -> str:
    """이름 정규화: NFKC(㎛→μm, 아래첨자→숫자) · 괄호 안 단위 제거 · 소문자 · 영숫자/한글만."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s)).lower().replace("μ", "u").replace("µ", "u")
    t = re.sub(r"\((%|wt%|mpa|min|분|cm2/g|㎠/g|g/l|ppm|mm|um)\)", "", t)
    return re.sub(r"[^0-9a-z$ㄱ-ㆎ가-힣]", "", t)


_ALIAS_TO_CODE = {}
for _code, _al in CODE_ALIASES.items():
    _ALIAS_TO_CODE[norm(_code)] = _code
    for _a in _al:
        _ALIAS_TO_CODE.setdefault(norm(_a), _code)


def code_of(name) -> str | None:
    return _ALIAS_TO_CODE.get(norm(name))


def table_codes() -> dict[str, dict[str, str]]:
    """{QMS 테이블: {표준 시험코드: QMS 열}} — lims.TEST_CODES 기준."""
    from .lims import DCS_ONLY, TEST_CODES

    out: dict[str, dict[str, str]] = {}
    for table, cols in RAW_COLUMNS.items():
        for c in cols:
            if c in TEST_CODES and c not in DCS_ONLY:
                out.setdefault(table, {}).setdefault(TEST_CODES[c], c)
                if TEST_CODES[c].endswith("_XRD"):                    # FCAO_XRD → XRD 시료의 f-CaO
                    out[table].setdefault(TEST_CODES[c][:-4], c)
    return out


def suggest_item(table: str | None, name) -> str | None:
    """시험항목 이름(코드·열 이름) → 그 시료 종류(QMS 테이블)의 QMS 열 추천."""
    code = code_of(name)
    if not table or not code:
        return None
    return table_codes().get(table, {}).get(code)


def suggest_roles(columns: list[str], layout: str = "long") -> dict[str, str]:
    """열 이름으로 역할 추천(정확히 같은 이름 우선, 그다음 포함)."""
    nc = {c: norm(c) for c in columns}
    out: dict[str, str] = {}
    used: set[str] = set()
    for role in LAYOUT_ROLES.get(layout, []):
        al = [norm(a) for a in ROLE_ALIASES.get(role, ())]
        hit = next((c for a in al for c in columns if nc[c] == a and c not in used), None)
        if hit is None:
            hit = next((c for a in al if len(a) >= 4 for c in columns if a in nc[c] and c not in used), None)
        if hit is not None:
            out[role] = hit
            used.add(hit)
    return out


def guess_layout(columns: list[str]) -> str:
    r = suggest_roles(columns, "long")
    if "test_code" in r and "value" in r:
        return "long"
    from .shipment import BY_KEY, match_headers

    idx = match_headers(list(columns))                      # 출하시멘트 머리글(채취일·첨가재명칭·비고·강도…)
    if "date" in idx and ("additive" in idx or "ships" in idx) and sum(k in BY_KEY for k in idx) >= 3:
        return "ship"
    return "wide"


# ── 접속 정보 ───────────────────────────────────────────────────────────
def empty_conn() -> dict:
    return {"type": "mssql", "ip": "", "host": "", "port": 1433, "database": "", "user": "", "driver": "pymssql",
            "odbc_driver": ODBC_DEFAULT, "oracle_mode": "service"}


def guess_type(port) -> str | None:
    try:
        return PORT_HINT.get(int(port))
    except (TypeError, ValueError):
        return None


def server_of(conn: dict) -> str:
    """접속에 쓸 주소: IP 우선, 없으면 호스트 이름."""
    return (conn.get("ip") or "").strip() or (conn.get("host") or "").strip()


def default_driver(dbtype: str) -> str:
    return next(iter(DB_TYPES.get(dbtype, DB_TYPES["mssql"])["drivers"]))


def build_url(conn: dict, password: str = "", database: str | None = None):
    from sqlalchemy.engine import URL

    t = conn.get("type", "mssql")
    db = conn.get("database", "") if database is None else database
    if t == "sqlite":
        return URL.create("sqlite", database=str(db))
    drv = conn.get("driver") or default_driver(t)
    port = int(conn["port"]) if str(conn.get("port") or "").strip() not in ("", "0") else None
    common = dict(username=(conn.get("user") or "").strip() or None, password=password or None, host=server_of(conn) or None,
                  port=port)
    if t == "mssql":
        if drv == "pyodbc":
            return URL.create("mssql+pyodbc", database=db or None, **common,
                              query={"driver": conn.get("odbc_driver") or ODBC_DEFAULT, "TrustServerCertificate": "yes"})
        return URL.create("mssql+pymssql", database=db or None, **common)
    if t == "oracle":
        if conn.get("oracle_mode", "service") == "service":
            return URL.create("oracle+oracledb", **common, query={"service_name": db} if db else {})
        return URL.create("oracle+oracledb", database=db or None, **common)
    if t == "postgresql":
        return URL.create("postgresql+psycopg2", database=db or "postgres", **common)
    if t == "mysql":
        return URL.create("mysql+pymysql", database=db or None, **common, query={"charset": "utf8mb4"})
    raise ValueError(f"알 수 없는 DB 종류: {t}")


def connect_args(conn: dict) -> dict:
    t, drv = conn.get("type"), conn.get("driver") or default_driver(conn.get("type", "mssql"))
    if t == "mssql" and drv == "pymssql":
        return {"login_timeout": TIMEOUT, "timeout": 300}
    if t == "mssql":
        return {"timeout": TIMEOUT}
    if t == "postgresql":
        return {"connect_timeout": TIMEOUT, "options": "-c default_transaction_read_only=on"}
    if t == "mysql":
        return {"connect_timeout": TIMEOUT, "read_timeout": 300, "init_command": "SET SESSION TRANSACTION READ ONLY"}
    if t == "oracle":
        return {"tcp_connect_timeout": float(TIMEOUT)}
    return {}


def make_engine(conn: dict, password: str = "", database: str | None = None):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    return create_engine(build_url(conn, password, database), connect_args=connect_args(conn), poolclass=NullPool)


def sanitize(msg: str, password: str = "") -> str:
    msg = str(msg)
    if password:
        for p in {password, quote_plus(password)}:
            msg = msg.replace(p, "****")
    msg = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1****@", msg)
    return msg[:600]


_HINTS = [
    (r"4060|cannot open database|database .* does not exist|ora-12514|ora-12505|unknown database|\(1049",
     "DB 이름(Oracle은 서비스 이름/SID)이 맞지 않습니다. MSSQL·PostgreSQL·MySQL은 DB 이름을 비우고 'DB 목록 불러오기'로 고를 수 있습니다."),
    (r"18456|login failed|password authentication failed|ora-01017|access denied for user|\(1045|authentication failed",
     "아이디 또는 비밀번호가 맞지 않습니다(대소문자 확인). 계정 잠김·만료 여부는 LIMS 담당자·IT에 확인하세요."),
    (r"no module named|data source name not found|im002|can't open lib|driver.*not found",
     "DB 드라이버가 없습니다. MS SQL Server는 드라이버를 pymssql 로 바꿔 보세요(추가 설치 불필요)."),
    (r"ssl|certificate|encrypt|tls", "암호화(SSL/TLS) 연결 설정 문제입니다. MS SQL Server는 드라이버를 바꿔 보세요(pymssql ↔ pyodbc)."),
    (r"permission denied|select permission|ora-00942|ora-01031|\(1142|not authorized",
     "이 계정에 읽기 권한이 없습니다. LIMS 담당자에게 해당 표·뷰의 SELECT 권한을 요청하세요."),
    (r"timed out|timeout|unable to connect|adaptive server is unavailable|could not connect|ora-12170|dpy-6005|ora-12541|"
     r"can't connect|\(2003|connection refused|no route|network",
     "서버에 연결하지 못했습니다(주소·포트·방화벽). 아래 '포트 연결' 결과를 확인하세요."),
]


def explain(msg: str) -> str:
    low = msg.lower()
    return next((h for p, h in _HINTS if re.search(p, low)), "")


def tcp_check(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, f"{host}:{port} 연결됨(포트 열림)"
    except socket.gaierror:
        return False, f"'{host}' 주소를 찾을 수 없습니다(호스트 이름 오타 또는 사내 DNS 미등록 → IP 주소로 입력해 보세요)."
    except ConnectionRefusedError:
        return False, (f"{host} 는 응답하지만 포트 {port} 가 닫혀 있습니다 — 포트 번호 또는 DB 서비스 실행 여부를 확인하세요"
                       "(MSSQL 기본 1433, Oracle 1521, PostgreSQL 5432, MySQL 3306).")
    except (TimeoutError, socket.timeout):
        return False, (f"{host}:{port} 응답 없음 — 사내 방화벽·네트워크 차단 가능성이 큽니다. IT에 'QMS PC → {host}:{port} TCP 허용'을 "
                       "요청하세요.")
    except OSError as exc:
        return False, f"{host}:{port} 연결 실패 — {exc}"


def _probe_sql(t: str) -> str:
    return "SELECT 1 FROM DUAL" if t == "oracle" else "SELECT 1"


def diagnose(conn: dict, password: str) -> list[dict]:
    """단계별 연결 진단 — [{'step', 'ok', 'msg'}]. 앞 단계가 실패하면 뒤 단계는 하지 않는다."""
    out: list[dict] = []
    t = conn.get("type", "mssql")

    def add(step, ok, msg):
        out.append({"step": step, "ok": ok, "msg": msg})
        return ok

    if t == "sqlite":
        from pathlib import Path
        ok = Path(conn.get("database") or "").exists()
        if not add("파일", ok, f"{conn.get('database')} {'있음' if ok else '없음'}"):
            return out
    else:
        ip, host = (conn.get("ip") or "").strip(), (conn.get("host") or "").strip()
        if not ip and not host:
            add("주소", False, "IP 주소 또는 호스트 이름을 입력하세요.")
            return out
        msgs = []
        if ip:
            try:
                ipaddress.ip_address(ip)
                msgs.append(f"IP {ip}")
            except ValueError:
                add("주소", False, f"IP 주소 형식이 아닙니다: {ip} (예: 10.20.30.40)")
                return out
        if host:
            try:
                addrs = sorted({a[4][0] for a in socket.getaddrinfo(host, None)})
                msgs.append(f"호스트 {host} → {', '.join(addrs[:3])}")
                if ip and ip not in addrs:
                    msgs.append("※ 호스트 이름의 IP와 입력한 IP가 다릅니다(IP로 접속합니다)")
            except socket.gaierror:
                msgs.append(f"호스트 {host}: 이름 확인 안 됨" + (" (IP로 접속)" if ip else ""))
                if not ip:
                    add("주소", False, f"'{host}' 주소를 찾을 수 없습니다. IP 주소를 입력하세요.")
                    return out
        add("주소", True, " · ".join(msgs))
        port = conn.get("port")
        if not port:
            add("포트 연결", False, "포트 번호를 입력하세요.")
            return out
        ok, msg = tcp_check(server_of(conn), int(port), 5)
        if not add("포트 연결", ok, msg):
            return out
    drv = conn.get("driver") or default_driver(t)
    try:
        __import__(DRIVER_MODULE.get(drv, drv))
        add("드라이버", True, DB_TYPES[t]["drivers"].get(drv, drv))
    except ImportError:
        add("드라이버", False, f"{drv} 구성요소가 없습니다(설치 패키지에는 포함 — 코드로 실행 중이면 pip install {drv}).")
        return out
    from sqlalchemy import inspect, text

    try:
        eng = make_engine(conn, password)
        try:
            with eng.connect() as c:
                c.execute(text(_probe_sql(t))).fetchall()
                ver = ""
                try:
                    ver = ".".join(str(x) for x in (eng.dialect.server_version_info or ())[:3])
                except Exception:  # noqa: BLE001
                    pass
                add("로그인·DB 접속", True, f"접속 성공{' · 서버 버전 ' + ver if ver else ''}"
                    + (f" · DB '{conn.get('database')}'" if conn.get("database") else " · 기본 DB(목록에서 고를 수 있음)"))
                try:
                    ins = inspect(c)
                    sch = ins.default_schema_name
                    counts = {}
                    others = [x for x in ins.get_schema_names() if x != sch and x.lower() not in SYSTEM_SCHEMAS
                              and not x.lower().startswith(("apex_", "pg_temp", "pg_toast", "flows_"))]
                    for x in [sch, *others][:30]:
                        try:
                            n = len(ins.get_table_names(x)) + len(ins.get_view_names(x))
                        except Exception:  # noqa: BLE001 - 권한 없는 스키마
                            n = 0
                        if n:
                            counts[x] = n
                    total = sum(counts.values())
                    add("읽기 권한", total > 0, ("표·뷰 " + " · ".join(f"{k} {v}개" for k, v in list(counts.items())[:6])
                                              + (" (기본 스키마 '" + str(sch) + "' 에는 없음 — 위 스키마를 고르세요)" if sch not in counts else ""))
                        if total else "보이는 표·뷰가 없습니다 — LIMS 담당자에게 결과 표·뷰의 SELECT 권한을 요청하세요.")
                except Exception as exc:  # noqa: BLE001
                    add("읽기 권한", False, sanitize(f"표 목록을 읽지 못했습니다 — {exc}", password))
        finally:
            eng.dispose()
    except Exception as exc:  # noqa: BLE001
        m = sanitize(f"{type(exc).__name__}: {exc}", password)
        add("로그인·DB 접속", False, (explain(m) + " · " if explain(m) else "") + "원문: " + m)
    return out


# ── 탐색 ────────────────────────────────────────────────────────────────
def list_databases(conn: dict, password: str) -> list[str]:
    from sqlalchemy import text

    t = conn.get("type")
    q = {"mssql": "SELECT name FROM sys.databases WHERE name NOT IN ('master','tempdb','model','msdb') ORDER BY name",
         "postgresql": "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1",
         "mysql": "SHOW DATABASES"}.get(t)
    if not q:
        return []
    eng = make_engine(conn, password, database="" if t != "postgresql" else (conn.get("database") or "postgres"))
    try:
        with eng.connect() as c:
            names = [str(r[0]) for r in c.execute(text(q)).fetchall()]
    finally:
        eng.dispose()
    return [n for n in names if n.lower() not in SYSTEM_SCHEMAS]


def list_schemas(conn: dict, password: str) -> tuple[list[str], str | None]:
    from sqlalchemy import inspect

    eng = make_engine(conn, password)
    try:
        with eng.connect() as c:
            ins = inspect(c)
            default = ins.default_schema_name
            names = [s for s in ins.get_schema_names() if s.lower() not in SYSTEM_SCHEMAS
                     and not s.lower().startswith(("apex_", "pg_temp", "pg_toast", "flows_"))]
    finally:
        eng.dispose()
    if default and default not in names:
        names.insert(0, default)
    names = sorted(names, key=lambda s: (s != default, s.lower()))
    return names, default


def list_objects(conn: dict, password: str, schema: str | None) -> pd.DataFrame:
    from sqlalchemy import inspect

    eng = make_engine(conn, password)
    try:
        with eng.connect() as c:
            ins = inspect(c)
            rows = [{"이름": n, "종류": "표"} for n in ins.get_table_names(schema)]
            try:
                rows += [{"이름": n, "종류": "뷰"} for n in ins.get_view_names(schema)]
            except NotImplementedError:
                pass
    finally:
        eng.dispose()
    return pd.DataFrame(rows, columns=["이름", "종류"]).sort_values(["종류", "이름"], key=lambda s: s.str.lower()) \
        .reset_index(drop=True)


def get_columns(conn: dict, password: str, schema: str | None, table: str) -> pd.DataFrame:
    from sqlalchemy import inspect

    eng = make_engine(conn, password)
    try:
        with eng.connect() as c:
            cols = inspect(c).get_columns(table, schema)
    finally:
        eng.dispose()
    return pd.DataFrame([{"열": col["name"], "자료형": str(col["type"])} for col in cols], columns=["열", "자료형"])


def _table(src: dict, cols: list[str]):
    from sqlalchemy import column, table

    return table(src["table"], *[column(c) for c in dict.fromkeys(cols)], schema=src.get("schema") or None)


def _text_fix(c, schema: str | None, table: str) -> set[str]:
    """MS SQL Server 의 비유니코드 문자 열(VARCHAR·CHAR·TEXT). Windows용 pymssql(FreeTDS)은 한국어 정렬(cp949) 문자를 바꾸지 못해
    한글이 깨지므로(예: 슬래그 → ½½·¡±×) 서버에서 NVARCHAR 로 바꿔 받는다."""
    if c.dialect.name != "mssql":
        return set()
    from sqlalchemy import inspect
    from sqlalchemy import types as T

    out = set()
    for col in inspect(c).get_columns(table, schema):
        ty = col["type"]
        if isinstance(ty, (T.String, T.Text)) and not isinstance(ty, (T.Unicode, T.UnicodeText)):
            out.add(col["name"])
    return out


def _col(t, name: str, fix: set[str], label: str | None = None):
    from sqlalchemy import cast
    from sqlalchemy.dialects.mssql import NVARCHAR

    e = cast(t.c[name], NVARCHAR("max")) if name in fix else t.c[name]
    lab = label or name
    return e.label(lab) if (name in fix or label) else e


def preview(conn: dict, password: str, schema: str | None, table: str, n: int = 20) -> pd.DataFrame:
    from sqlalchemy import select

    cols = list(get_columns(conn, password, schema, table)["열"])
    t = _table({"table": table, "schema": schema}, cols)
    eng = make_engine(conn, password)
    try:
        with eng.connect() as c:
            fix = _text_fix(c, schema, table)
            return pd.read_sql(select(*[_col(t, x, fix) for x in cols]).limit(n), c)
    finally:
        eng.dispose()


def guess_date_format(values) -> str:
    """날짜 열의 저장 형식 → 증분 조회 비교 방식. 'datetime'(날짜형) · strftime 형식(문자열) · 'int:%Y%m%d'(숫자)."""
    vals = [v for v in list(values) if v is not None and not (isinstance(v, float) and np.isnan(v))][:50]
    if not vals:
        return "datetime"
    if all(isinstance(v, (datetime, date, pd.Timestamp, np.datetime64)) for v in vals):
        return "datetime"
    if all(isinstance(v, (int, np.integer)) for v in vals):
        lens = {len(str(int(v))) for v in vals}
        return "int:%Y%m%d" if lens == {8} else ("int:%Y%m%d%H%M%S" if lens == {14} else "datetime")
    s = [str(v).strip() for v in vals]
    pats = [(r"\d{8}", "%Y%m%d"), (r"\d{14}", "%Y%m%d%H%M%S"), (r"\d{12}", "%Y%m%d%H%M"),
            (r"\d{4}-\d{2}-\d{2}([ T].*)?", "%Y-%m-%d %H:%M:%S"), (r"\d{4}\.\d{2}\.\d{2}.*", "%Y.%m.%d"),
            (r"\d{4}/\d{2}/\d{2}.*", "%Y/%m/%d")]
    for p, fmt in pats:
        if all(re.fullmatch(p, x) for x in s):
            return fmt
    return "datetime"


def _since_param(fmt: str, since: datetime):
    if fmt.startswith("int:"):
        return int(since.strftime(fmt[4:]))
    if fmt != "datetime":
        return since.strftime(fmt)
    return since


def _where(src: dict, t, since: datetime | None):
    from sqlalchemy import and_

    conds = []
    cols = src.get("cols", {})
    if since is not None:
        if cols.get("updated_at"):
            conds.append(t.c[cols["updated_at"]] > _since_param(src.get("updated_format", "datetime"), since))
        elif src.get("layout") == "ship" and src.get("ship_map", {}).get("date"):
            conds.append(t.c[src["ship_map"]["date"]] >= _since_param(src.get("date_format", "datetime"), since))
        elif cols.get("sampled_at"):
            conds.append(t.c[cols["sampled_at"]] >= _since_param(src.get("date_format", "datetime"), since))
    fc, fv = src.get("filter_col"), [v.strip() for v in str(src.get("filter_values") or "").split(",") if v.strip()]
    if fc and fv:
        conds.append(t.c[fc].in_(fv))
    return and_(*conds) if conds else None


def needed_columns(src: dict) -> list[str]:
    cols = [c for c in src.get("cols", {}).values() if c]
    if src.get("layout") == "wide":
        cols += list(src.get("item_cols") or [])
    if src.get("layout") == "ship":
        cols += [c for c in (src.get("ship_map") or {}).values() if c]
    if src.get("filter_col"):
        cols.append(src["filter_col"])
    return list(dict.fromkeys(cols))


def _combine_time(d: pd.DataFrame) -> pd.DataFrame:
    if "time" not in d.columns:
        return d
    def hhmm(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "00:00:00"
        s = str(v).strip()
        if re.fullmatch(r"\d{3,4}", s):
            s = s.zfill(4)
            return f"{s[:2]}:{s[2:]}:00"
        if re.fullmatch(r"\d{6}", s):
            return f"{s[:2]}:{s[2:4]}:{s[4:]}"
        return s[-8:] if " " in s else s
    day = pd.to_datetime(d["sampled_at"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
    d = d.copy()
    d["sampled_at"] = pd.to_datetime(day + " " + d["time"].map(hhmm), errors="coerce", format="mixed")
    return d.drop(columns=["time"])


def fetch_source(conn: dict, password: str, src: dict, since: datetime | None, max_rows: int = MAX_ROWS) -> tuple[pd.DataFrame, bool]:
    """소스 1개 조회 → (DataFrame, 최대 행 수 도달 여부). long·wide 는 표준 열 이름, ship 은 원래 열 이름."""
    from sqlalchemy import select

    layout = src.get("layout", "long")
    t = _table(src, needed_columns(src))
    cols = src.get("cols", {})
    eng = make_engine(conn, password)
    try:
        with eng.connect() as c:
            fix = _text_fix(c, src.get("schema") or None, src["table"])
            if layout == "ship":
                sel = [_col(t, x, fix) for x in dict.fromkeys(x for x in (src.get("ship_map") or {}).values() if x)]
            else:
                roles = [r for r in LAYOUT_ROLES[layout] if cols.get(r)]
                sel = [_col(t, cols[r], fix, label=r) for r in roles]
                if layout == "wide":
                    sel += [_col(t, x, fix) for x in src.get("item_cols") or [] if x not in cols.values()]
            q = select(*sel)
            w = _where(src, t, since)
            if w is not None:
                q = q.where(w)
            d = pd.read_sql(q.limit(max_rows + 1), c)
    finally:
        eng.dispose()
    capped = len(d) > max_rows
    d = d.head(max_rows)
    if layout != "ship":
        d = _combine_time(d)
        if "sample_point" not in d.columns and src.get("fixed_sample_point"):
            d["sample_point"] = src["fixed_sample_point"]
    return d, capped


def distinct_codes(conn: dict, password: str, src: dict, since: datetime | None, limit: int = 3000) -> pd.DataFrame:
    """긴 형식: 최근 기간의 (채취 지점, 시험코드, 건수) — 항목 매칭 표를 만드는 데 쓴다."""
    from sqlalchemy import desc, func, literal, select

    cols = src.get("cols", {})
    t = _table(src, needed_columns(src))
    eng = make_engine(conn, password)
    try:
        with eng.connect() as c:
            fix = _text_fix(c, src.get("schema") or None, src["table"])
            sp = _col(t, cols["sample_point"], fix, "sample_point") if cols.get("sample_point") else \
                literal(src.get("fixed_sample_point") or "").label("sample_point")
            tc = _col(t, cols["test_code"], fix, "test_code")
            n = func.count().label("n")
            q = select(sp, tc, n)
            w = _where(src, t, since)
            if w is not None:
                q = q.where(w)
            grp = [t.c[cols["sample_point"]]] if cols.get("sample_point") else []
            q = q.group_by(*grp, t.c[cols["test_code"]]).order_by(desc(n)).limit(limit)
            d = pd.read_sql(q, c)
    finally:
        eng.dispose()
    if not cols.get("sample_point"):
        d["sample_point"] = src.get("fixed_sample_point") or ""
    d["sample_point"] = d["sample_point"].astype(str).str.strip()
    d["test_code"] = d["test_code"].astype(str).str.strip()
    return d
