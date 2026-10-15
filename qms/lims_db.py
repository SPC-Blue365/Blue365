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
                   "samplingdt", "시료일시", "시험일시", "시험일", "시험일자", "측정일자", "측정일", "측정일시", "분석일자", "분석일",
                   "분석일시", "검사일자", "검사일", "검사일시", "생산일자", "생산일", "접수일시", "date", "dt"),
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
            od = conn.get("odbc_driver") or ODBC_DEFAULT
            q = {"driver": od, "TrustServerCertificate": "yes"}
            if "18" in od:                                # ODBC Driver 18 은 암호화가 기본 필수
                q["Encrypt"] = "yes"
            return URL.create("mssql+pyodbc", database=db or None, **common, query=q)
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
        args = {"login_timeout": TIMEOUT, "timeout": 300}
        if conn.get("tds_version"):                   # 🔧 연결 방법 자동 찾기에서 정한 값(예: 7.0)
            args["tds_version"] = conn["tds_version"]
        if conn.get("encryption"):                    # off·request·require
            args["encryption"] = conn["encryption"]
        return args
    if t == "mssql":
        return {"timeout": TIMEOUT}
    if t == "postgresql":
        return {"connect_timeout": TIMEOUT, "options": "-c default_transaction_read_only=on"}
    if t == "mysql":
        return {"connect_timeout": TIMEOUT, "read_timeout": 300, "init_command": "SET SESSION TRANSACTION READ ONLY"}
    if t == "oracle":
        return {"tcp_connect_timeout": float(TIMEOUT)}
    return {}


DRIVER_PIP = {"pymssql": "pymssql>=2.3", "pyodbc": "pyodbc>=5.1", "oracledb": "oracledb>=2.0", "psycopg2": "psycopg2-binary>=2.9",
              "pymysql": "PyMySQL>=1.1", "sqlalchemy": "SQLAlchemy>=2.0"}


def driver_ok(drv: str) -> bool:
    """이 실행 환경(파이썬)에 드라이버 구성요소가 있는가(불러오지 않고 찾기만)."""
    import importlib.util

    try:
        return importlib.util.find_spec(DRIVER_MODULE.get(drv, drv)) is not None
    except (ImportError, ValueError):
        return False


def runtime_python() -> str:
    import sys
    return sys.executable


def install_driver(drv: str, timeout: int = 600) -> tuple[bool, str]:
    """실행 중인 파이썬에 드라이버를 pip 로 설치(인터넷 또는 사내 pip 저장소 필요). → (성공, 기록 끝부분)."""
    import importlib
    import site
    import subprocess
    import sys

    pkgs = [DRIVER_PIP.get(drv, drv)] + ([] if driver_ok("sqlalchemy") else [DRIVER_PIP["sqlalchemy"]])
    try:
        p = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *pkgs], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        log = (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    try:                                               # 사용자 폴더에 설치된 경우에도 바로 불러올 수 있게
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            site.addsitedir(user_site)
    except Exception:  # noqa: BLE001
        pass
    importlib.invalidate_caches()
    ok = p.returncode == 0 and driver_ok(drv)
    return ok, "\n".join(log.strip().splitlines()[-12:])


def b64_ip(text: str) -> str | None:
    """'MTcyLjE3LjIyLjEx' 처럼 Base64 로 인코딩된 IP 이면 풀어서 돌려준다(LIMS 설정 파일에서 복사한 값 안내용)."""
    import base64
    import binascii

    t = (text or "").strip()
    if not t or not re.fullmatch(r"[A-Za-z0-9+/]{8,}={0,2}", t):
        return None
    try:
        dec = base64.b64decode(t + "=" * (-len(t) % 4), validate=True).decode("ascii")
        ipaddress.ip_address(dec)
        return dec
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


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
    (r"20002|20017|tds server connection failed|unexpected eof from the server|adaptive server connection failed",
     "로그인 전 암호화(TLS) 단계에서 연결이 끊겼습니다(아이디·비밀번호 문제 아님). 서버 인증서·TLS 설정이 오래됐거나 중간 장비가 막는 경우가 많습니다 "
     "→ 아래 '🔧 연결 방법 자동 찾기'를 누르세요(Windows SQL Server 드라이버 등 다른 방법을 차례로 시도)."),
    (r"4060|cannot open database|database .* does not exist|ora-12514|ora-12505|unknown database|\(1049",
     "DB 이름(Oracle은 서비스 이름/SID)이 맞지 않습니다. MSSQL·PostgreSQL·MySQL은 DB 이름을 비우고 'DB 목록 불러오기'로 고를 수 있습니다."),
    (r"18456|login failed|password authentication failed|ora-01017|access denied for user|\(1045|authentication failed",
     "아이디 또는 비밀번호가 맞지 않습니다(대소문자 확인). 계정 잠김·만료 여부는 LIMS 담당자·IT에 확인하세요."),
    (r"data source name not found|im002|can't open lib|odbc driver.*not found",
     "Windows ODBC 드라이버가 없습니다. MS SQL Server는 접속 드라이버를 pymssql 로 바꾸세요."),
    (r"ssl|certificate|encrypt|tls", "암호화(SSL/TLS) 연결 설정 문제입니다. MS SQL Server는 드라이버를 바꿔 보세요(pymssql ↔ pyodbc)."),
    (r"permission denied|select permission|ora-00942|ora-01031|\(1142|not authorized",
     "이 계정에 읽기 권한이 없습니다. LIMS 담당자에게 해당 표·뷰의 SELECT 권한을 요청하세요."),
    (r"timed out|timeout|unable to connect|adaptive server is unavailable|could not connect|ora-12170|dpy-6005|ora-12541|"
     r"can't connect|\(2003|connection refused|no route|network",
     "서버에 연결하지 못했습니다(주소·포트·방화벽). 아래 '포트 연결' 결과를 확인하세요."),
]


def explain(msg: str) -> str:
    low = msg.lower()
    m = re.search(r"no module named '([\w.]+)'", low)
    if m:
        mod = m.group(1).split(".")[0]
        return (f"이 실행 환경(파이썬)에 DB 드라이버 '{mod}' 가 없습니다 → ① 연결 설정의 '⬇️ 드라이버 설치' 버튼을 누르거나, "
                "드라이버가 들어 있는 설치 앱(2_RUN.bat)·최신 RUN_CODE.bat 으로 실행하세요.")
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


# ── DB 종류 자동 확인(아이디·비밀번호 없이, 접속 첫 인사만 주고받음) ──────────────────────
MSSQL_YEARS = {16: "2022", 15: "2019", 14: "2017", 13: "2016", 12: "2014", 11: "2012", 10: "2008"}


def _exchange(host: str, port: int, payload: bytes | None, timeout: float) -> bytes:
    """새로 접속해 payload 를 보내고(없으면 서버가 먼저 말하기를 기다림) 처음 받은 바이트를 돌려준다."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            if payload:
                s.sendall(payload)
            try:
                return s.recv(4096)
            except (TimeoutError, socket.timeout, ConnectionResetError, OSError):
                return b""
    except OSError:
        return b""


def _tds_prelogin() -> bytes:
    # MS SQL Server TDS PRELOGIN: VERSION(6바이트) · ENCRYPTION(1바이트, 0x02=암호화 안 씀) · 끝(0xFF)
    opts = bytes([0x00, 0x00, 0x0B, 0x00, 0x06, 0x01, 0x00, 0x11, 0x00, 0x01, 0xFF])
    data = opts + bytes([0x0F, 0x00, 0x00, 0x00, 0x00, 0x00]) + bytes([0x02])
    n = 8 + len(data)
    return bytes([0x12, 0x01, n >> 8, n & 0xFF, 0x00, 0x00, 0x01, 0x00]) + data


def _tns_version() -> bytes:
    # Oracle TNS CONNECT(COMMAND=version) — 리스너가 버전 또는 거절(REFUSE) 패킷으로 답한다
    cd = b"(CONNECT_DATA=(COMMAND=version))"
    body = bytes.fromhex("0136012c00000800" "7fff7f0800000001") + len(cd).to_bytes(2, "big") + (58).to_bytes(2, "big")
    body += b"\x00" * (58 - 8 - len(body))
    n = 8 + len(body) + len(cd)
    return n.to_bytes(2, "big") + b"\x00\x00\x01\x00\x00\x00" + body + cd


def _classify(data: bytes) -> dict | None:
    if not data:
        return None
    if len(data) > 6 and data[4] == 10 and b"\x00" in data[5:60]:                 # MySQL·MariaDB 첫 인사(프로토콜 10)
        ver = data[5:data.index(b"\x00", 5)].decode("ascii", "replace")
        if re.match(r"\d+\.\d+", ver):
            return {"type": "mysql", "version": ("MariaDB " if "mariadb" in ver.lower() else "MySQL ") + ver.split("-")[0]}
    if len(data) >= 8 and data[0] == 0x04 and int.from_bytes(data[2:4], "big") >= 8:   # TDS 응답 = MS SQL Server
        ver, enc = "", ""
        try:
            p = data[8:]
            i = 0
            while i < len(p) and p[i] != 0xFF:
                tok, off, ln = p[i], int.from_bytes(p[i + 1:i + 3], "big"), int.from_bytes(p[i + 3:i + 5], "big")
                if tok == 0x00 and ln >= 6:
                    major, minor, build = p[off], p[off + 1], int.from_bytes(p[off + 2:off + 4], "big")
                    ver = f"SQL Server {MSSQL_YEARS.get(major, '')} ({major}.{minor}.{build})".replace("  ", " ")
                if tok == 0x01 and ln >= 1:
                    # 이쪽이 '암호화 안 씀'으로 물었을 때의 서버 답: 2 = 강제 아님(암호화 없이도 접속 허용), 3 = 서버가 암호화를 강제
                    enc = {0: "선택", 1: "사용", 2: "강제 아님(암호화 없이도 접속 허용)", 3: "필수(서버가 강제)"}.get(p[off], "")
                i += 5
        except IndexError:
            pass
        return {"type": "mssql", "version": ver, **({"encryption": enc} if enc else {})}
    if data in (b"S", b"N") or (data[:1] == b"E" and b"SFATAL" in data):            # PostgreSQL SSL 요청 응답
        return {"type": "postgresql", "version": ""}
    if len(data) >= 8 and data[4] in (2, 4, 5, 11, 12) and (b"DESCRIPTION" in data or b"VSNNUM" in data
                                                           or b"ERR=" in data or data[4] == 11):
        m = re.search(rb"VSNNUM=(\d+)", data)
        ver = ""
        if m and int(m.group(1)) > 0:                                             # 보안 설정이면 VSNNUM=0(버전 숨김)
            v = int(m.group(1))
            ver = f"Oracle {v >> 24}.{(v >> 20) & 0xF}"
        return {"type": "oracle", "version": ver}
    return None


def detect_type(host: str, port: int, timeout: float = 3.0) -> dict:
    """IP·포트만으로 DB 종류 확인 → {'type','label','version','msg'}. type 이 None 이면 알아내지 못함."""
    ok, msg = tcp_check(host, port, timeout)
    if not ok:
        return {"type": None, "label": "", "version": "", "msg": msg}
    probes = [(None, 1.5), (_tds_prelogin(), timeout), (b"\x00\x00\x00\x08\x04\xd2\x16\x2f", timeout), (_tns_version(), timeout)]
    for payload, to in probes:                    # MySQL(서버가 먼저 인사) → MS SQL → PostgreSQL → Oracle 순서
        hit = _classify(_exchange(host, port, payload, to))
        if hit:
            label = DB_TYPES[hit["type"]]["label"]
            return {**hit, "label": label, "msg": f"이 서버는 **{label}** 입니다" + (f" — {hit['version']}" if hit["version"] else "")
                    + (f" · 암호화 연결: {hit['encryption']}" if hit.get("encryption") else "")}
    hint = guess_type(port)
    return {"type": None, "label": "", "version": "",
            "msg": "포트는 열려 있지만 DB 종류를 알아내지 못했습니다(중계 장비·암호화 전용 설정 등)."
                   + (f" 포트 {port} 는 보통 {DB_TYPES[hint]['label']} 입니다." if hint else " LIMS 담당자에게 확인하세요.")}


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
                dec = b64_ip(host)
                msgs.append(f"호스트 {host}: 이름 확인 안 됨" + (" (IP로 접속)" if ip else "")
                            + (f" — 이 값은 Base64로 인코딩된 IP {dec} 입니다(LIMS 설정 파일 값으로 보임)" if dec else ""))
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
        det = detect_type(server_of(conn), int(port))
        if det["type"] and det["type"] != t:
            add("DB 종류", False, f"입력한 종류는 {DB_TYPES[t]['label']} 이지만 서버는 {det['label']}{' ' + det['version'] if det['version'] else ''} 입니다 — "
                "DB 종류를 바꾸세요('🔎 DB 종류 자동 확인'을 누르면 자동으로 맞춥니다).")
            return out
        if det["type"]:
            add("DB 종류", True, det["label"] + (f" — {det['version']}" if det["version"] else "")
                + (f" · 암호화 연결: {det['encryption']}" if det.get("encryption") else ""))
    drv = conn.get("driver") or default_driver(t)
    try:
        __import__(DRIVER_MODULE.get(drv, drv))
        add("드라이버", True, DB_TYPES[t]["drivers"].get(drv, drv))
    except ImportError:
        add("드라이버", False, f"이 실행 환경에 '{drv}' 드라이버가 없습니다 — '⬇️ 드라이버 설치' 버튼(인터넷 필요)을 누르거나 "
            f"설치 앱(2_RUN.bat)으로 실행하세요. 실행 중인 파이썬: {runtime_python()}")
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
    q = {"mssql": "SELECT name FROM sys.databases WHERE name NOT IN ('master','tempdb','model','msdb') "
                  "AND HAS_DBACCESS(name) = 1 AND state = 0 ORDER BY name",
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


def list_schemas(conn: dict, password: str, database: str | None = None) -> tuple[list[str], str | None]:
    from sqlalchemy import inspect

    eng = make_engine(conn, password, database or None)
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


def list_objects(conn: dict, password: str, schema: str | None, database: str | None = None) -> pd.DataFrame:
    from sqlalchemy import inspect

    eng = make_engine(conn, password, database or None)
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


def get_columns(conn: dict, password: str, schema: str | None, table: str, database: str | None = None) -> pd.DataFrame:
    from sqlalchemy import inspect

    eng = make_engine(conn, password, database or None)
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


def preview(conn: dict, password: str, schema: str | None, table: str, n: int = 20,
            database: str | None = None) -> pd.DataFrame:
    from sqlalchemy import select

    cols = list(get_columns(conn, password, schema, table, database)["열"])
    t = _table({"table": table, "schema": schema}, cols)
    eng = make_engine(conn, password, database or None)
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
    eng = make_engine(conn, password, src.get("database") or None)
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
    eng = make_engine(conn, password, src.get("database") or None)
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
            grp = [_col(t, cols["sample_point"], fix)] if cols.get("sample_point") else []   # 선택한 식 그대로 묶음(TEXT 형 대비)
            q = q.group_by(*[g.element if hasattr(g, "element") else g for g in grp + [tc]]).order_by(desc(n)).limit(limit)
            d = pd.read_sql(q, c)
    finally:
        eng.dispose()
    if not cols.get("sample_point"):
        d["sample_point"] = src.get("fixed_sample_point") or ""
    d["sample_point"] = d["sample_point"].astype(str).str.strip()
    d["test_code"] = d["test_code"].astype(str).str.strip()
    return d


# ── DB 구조 자동 탐색: 표·열 목록을 한 번에 읽고, 시험 결과가 있을 법한 표를 점수로 고른다 ─────────
_GOOD_WORDS = ("result", "rslt", "결과", "시험", "test", "qc", "sample", "smp", "성적", "lab", "lims", "분석", "analysis",
               "inspect", "검사", "품질", "quality", "assay", "measure", "측정", "출하", "ship", "cement", "시멘트", "clinker",
               "클링커", "강도", "strength")
_BAD_WORDS = ("log", "hist", "bak", "backup", "tmp", "temp", "user", "menu", "auth", "config", "sys", "dict", "error",
              "session", "file", "attach", "mail", "msg", "role", "perm", "audit", "trace")
_DATE_TYPES = ("date", "time")
_TEXT_TYPES = ("char", "text", "string", "clob", "varchar")


def _norm_name(n: str, dialect: str) -> str:
    """Oracle 은 대문자 이름을 소문자로(SQLAlchemy 반영 이름과 같게)."""
    return n.lower() if dialect == "oracle" and n == n.upper() else n


def catalog(conn: dict, password: str, database: str | None = None) -> pd.DataFrame:
    """DB 안의 표·뷰와 열 목록(권한이 있는 것만) → [database, schema, table, kind, column, dtype]."""
    from sqlalchemy import text

    t = conn.get("type")
    cols = ["database", "schema", "table", "kind", "column", "dtype"]
    if t == "sqlite":
        import sqlite3
        from contextlib import closing
        rows = []
        with closing(sqlite3.connect(conn.get("database") or "")) as con:
            for name, typ in con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
                                         "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
                for r in con.execute(f'PRAGMA table_info("{name}")').fetchall():
                    rows.append(("", "main", name, "뷰" if typ == "view" else "표", r[1], str(r[2] or "").lower()))
        return pd.DataFrame(rows, columns=cols)
    if t == "oracle":
        sysq = ",".join(f"'{x.upper()}'" for x in sorted(SYSTEM_SCHEMAS) if "'" not in x)
        q = ("SELECT c.owner, c.table_name, CASE WHEN v.view_name IS NULL THEN 'BASE TABLE' ELSE 'VIEW' END, c.column_name, "
             "c.data_type FROM all_tab_columns c LEFT JOIN all_views v ON v.owner = c.owner AND v.view_name = c.table_name "
             f"WHERE c.owner NOT IN ({sysq}) AND c.owner NOT LIKE 'APEX%' AND c.owner NOT LIKE 'FLOWS%' "
             "AND c.table_name NOT LIKE 'BIN$%' ORDER BY c.owner, c.table_name, c.column_id")
    else:
        where = "WHERE c.TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys') " if t == "mysql" else \
            ("WHERE c.TABLE_SCHEMA NOT IN ('pg_catalog','information_schema') " if t == "postgresql" else "")
        q = ("SELECT c.TABLE_SCHEMA, c.TABLE_NAME, t.TABLE_TYPE, c.COLUMN_NAME, c.DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS c "
             "JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME "
             + ("AND t.TABLE_CATALOG = c.TABLE_CATALOG " if t != "mysql" else "") + where
             + "ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION")
    eng = make_engine(conn, password, database or None)
    try:
        with eng.connect() as c:
            res = c.execute(text(q)).fetchall()
    finally:
        eng.dispose()
    db = database if database is not None else (conn.get("database") or "")
    out = [(db if t != "mysql" else str(r[0]), _norm_name(str(r[0]), t), _norm_name(str(r[1]), t),
            "뷰" if "VIEW" in str(r[2]).upper() else "표", _norm_name(str(r[3]), t), str(r[4]).lower()) for r in res]
    return pd.DataFrame(out, columns=cols)


def score_table(table: str, cols: list[tuple[str, str]]) -> dict:
    """열 이름·자료형으로 '시험 결과 표일 가능성' 점수와 추정 형식·근거."""
    from .shipment import BY_KEY, match_headers

    names = [c for c, _ in cols]
    if len(names) < 3:
        return {"score": 0, "layout": "", "reasons": "열이 너무 적음"}
    score, reasons, layout = 0, [], ""
    roles = suggest_roles(names, "long")
    dates = [c for c, ty in cols if any(k in ty for k in _DATE_TYPES)] or ([roles["sampled_at"]] if roles.get("sampled_at") else []) \
        or [c for c in names if norm(c).endswith(("일자", "일시", "날짜", "date", "dt", "datetime"))]
    if dates:
        score += 2
        reasons.append("날짜 " + ", ".join(dates[:2]))
    if roles.get("test_code") and roles.get("value"):
        score += 6
        layout = "long"
        reasons.append(f"시험항목 {roles['test_code']} · 결과 {roles['value']}")
    items = [c for c in names if code_of(c)]
    if len(items) >= 2:
        score += min(10, 2 * len(items))
        layout = layout or "wide"
        reasons.append("시험항목 열 " + ", ".join(items[:6]) + (f" 외 {len(items) - 6}" if len(items) > 6 else ""))
    idx = match_headers(names)
    if "date" in idx and ("additive" in idx or "ships" in idx) and sum(k in BY_KEY for k in idx) >= 3:
        score += 8
        layout = "ship"
        reasons.append("출하시멘트 성적 머리글")
    extra = [r for r in ("sample_point", "product", "status", "updated_at") if roles.get(r)]
    score += len(extra)
    if extra:
        reasons.append("·".join(ROLES[r][0] for r in extra))
    n = norm(table)
    if any(norm(w) in n for w in _GOOD_WORDS):
        score += 2
    if any(w in n for w in _BAD_WORDS):
        score -= 3
    if not dates:
        score = min(score, 3)                                  # 날짜 열이 없으면 결과 표로 쓰기 어려움
    return {"score": max(score, 0), "layout": layout or "wide", "reasons": " / ".join(reasons) or "-"}


def explore(conn: dict, password: str, all_dbs: bool = False, max_dbs: int = 30, progress=None) -> dict:
    """DB 전체(또는 모든 DB)의 표를 훑어 후보 순위표를 만든다 → {'candidates', 'catalog', 'errors', 'databases'}."""
    t = conn.get("type")
    dbs: list[str | None] = [None]
    errors = []
    if t in ("mssql", "postgresql") and (all_dbs or not conn.get("database")):
        try:
            dbs = list_databases(conn, password)[:max_dbs] or [None]
        except Exception as exc:  # noqa: BLE001
            errors.append(sanitize(f"DB 목록을 읽지 못했습니다(접속한 DB만 찾습니다) — {exc}", password))
    frames = []
    for i, db in enumerate(dbs, 1):
        if progress:
            progress(i, len(dbs), db or conn.get("database") or "")
        try:
            frames.append(catalog(conn, password, db))
        except Exception as exc:  # noqa: BLE001 - 권한 없는 DB 는 건너뜀
            m = sanitize(f"{type(exc).__name__}: {exc}", password)
            hint = explain(m)
            errors.append(f"[{db or conn.get('database') or '기본 DB'}] " + (f"건너뜀 — {hint}" if hint else m[:300]))
    cat = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["database", "schema", "table", "kind", "column", "dtype"])
    rows = []
    for (db, sch, tb, kind), g in cat.groupby(["database", "schema", "table", "kind"], sort=False):
        sc = score_table(tb, list(zip(g["column"], g["dtype"])))
        rows.append({"database": db, "schema": sch, "table": tb, "kind": kind, "n_cols": len(g), **sc})
    cand = pd.DataFrame(rows, columns=["database", "schema", "table", "kind", "n_cols", "score", "layout", "reasons"])
    cand = cand.sort_values(["score", "kind", "n_cols"], ascending=[False, False, False]).reset_index(drop=True)
    return {"candidates": cand, "catalog": cat, "errors": errors, "databases": [d for d in dbs if d]}


def find_term(conn: dict, password: str, cat: pd.DataFrame, cand: pd.DataFrame, term: str, max_queries: int = 150) -> pd.DataFrame:
    """이름·값으로 찾기: 열 이름에 term 이 든 곳 + (후보 상위 표의 문자 열) 값에 term 이 든 곳."""
    from sqlalchemy import select

    term = (term or "").strip()
    cols = ["찾은 곳", "DB", "스키마", "표", "열", "예시"]
    if not term:
        return pd.DataFrame(columns=cols)
    nt = norm(term)
    out = [("열 이름", r.database, r.schema, r.table, r.column, "") for r in cat.itertuples()
           if nt and nt in norm(r.column)]
    top = cand[cand["score"] > 0].head(40)
    budget = max_queries
    for r in top.itertuples():
        tcols = cat[(cat["database"] == r.database) & (cat["schema"] == r.schema) & (cat["table"] == r.table)]
        text_cols = [c for c, ty in zip(tcols["column"], tcols["dtype"]) if any(k in ty for k in _TEXT_TYPES)][:8]
        if not text_cols or budget <= 0:
            continue
        src = {"table": r.table, "schema": r.schema or None, "database": r.database or None}
        try:
            eng = make_engine(conn, password, r.database or None)
            with eng.connect() as c:
                fix = _text_fix(c, src["schema"], r.table)
                t = _table(src, text_cols)
                for col in text_cols:
                    if budget <= 0:
                        break
                    budget -= 1
                    e = _col(t, col, fix)
                    v = c.execute(select(e).where(t.c[col].like(f"%{term}%")).limit(1)).scalar()
                    if v is not None:
                        out.append(("값", r.database, r.schema, r.table, col, str(v)[:40]))
            eng.dispose()
        except Exception:  # noqa: BLE001 - 읽을 수 없는 표는 건너뜀
            continue
    return pd.DataFrame(out, columns=cols)


def structure_workbook(res: dict, samples: dict | None = None) -> bytes:
    """LIMS DB 구조 엑셀(추천 표·표 목록·열 목록·예시 데이터) — LIMS 담당자·지원 담당자와 함께 보기용."""
    import io

    cand, cat = res["candidates"], res["catalog"]
    lay = {"long": "긴 형식", "wide": "가로형", "ship": "출하시멘트"}
    top = cand.head(30).rename(columns={"database": "DB", "schema": "스키마", "table": "표", "kind": "종류", "n_cols": "열 수",
                                        "score": "점수", "layout": "추정 형식", "reasons": "근거"})
    top["추정 형식"] = top["추정 형식"].map(lambda x: lay.get(x, x))
    tables = cand.rename(columns={"database": "DB", "schema": "스키마", "table": "표", "kind": "종류", "n_cols": "열 수", "score": "점수"})
    colsheet = cat.rename(columns={"database": "DB", "schema": "스키마", "table": "표", "kind": "종류", "column": "열", "dtype": "자료형"})
    colsheet["역할 추정"] = [next((ROLES[k][0] for k, v in suggest_roles([c], "long").items() if v == c), "") for c in colsheet["열"]]
    colsheet["시험항목 추정"] = colsheet["열"].map(lambda c: code_of(c) or "")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        top.to_excel(xw, sheet_name="① 추천 표", index=False)
        tables[["DB", "스키마", "표", "종류", "열 수", "점수"]].to_excel(xw, sheet_name="② 표 목록", index=False)
        colsheet.to_excel(xw, sheet_name="③ 열 목록", index=False)
        if samples:
            r0 = 0
            for name, df in samples.items():
                pd.DataFrame([[name]]).to_excel(xw, sheet_name="④ 예시 데이터", index=False, header=False, startrow=r0)
                df.to_excel(xw, sheet_name="④ 예시 데이터", index=False, startrow=r0 + 1)
                r0 += len(df) + 4
        for ws in xw.book.worksheets:
            for col in ws.columns:
                w = max(len(str(c.value or "")) for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(60, max(8, w * 1.3))
            ws.freeze_panes = "A2"
    return buf.getvalue()


# ── 🔧 연결 방법 자동 찾기(MS SQL Server): 드라이버·설정을 바꿔 가며 실제 로그인까지 시도 ───────────────
_ODBC_ORDER = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "ODBC Driver 13 for SQL Server",
               "SQL Server Native Client 11.0", "SQL Server Native Client 10.0", "SQL Server")


def odbc_drivers() -> list[str]:
    """이 PC(Windows)에 설치된 SQL Server ODBC 드라이버 — 좋은 것부터. Windows 에는 'SQL Server'(기본 내장)가 항상 있다."""
    try:
        import pyodbc
        have = [d for d in pyodbc.drivers() if "sql server" in d.lower()]
    except Exception:  # noqa: BLE001 - pyodbc·ODBC 관리자 없음
        return []
    return sorted(have, key=lambda d: (_ODBC_ORDER.index(d) if d in _ODBC_ORDER else len(_ODBC_ORDER), d))


def connection_plans(conn: dict, allow_plain: bool = False) -> list[tuple[str, dict]]:
    """시도할 연결 방법 목록(앞쪽이 권장) — (설명, conn 에 덮어쓸 값)."""
    if conn.get("type") != "mssql":
        return [("기본", {})]
    base = {"tds_version": None, "encryption": None}
    plans = [("pymssql(기본)", {**base, "driver": "pymssql"}),
             ("pymssql · TDS 7.4", {**base, "driver": "pymssql", "tds_version": "7.4"})]
    plans += [(f"Windows ODBC · {d}", {**base, "driver": "pyodbc", "odbc_driver": d}) for d in odbc_drivers()]
    if allow_plain:
        plans += [("pymssql · 암호화 없이(사내망 전용)", {**base, "driver": "pymssql", "encryption": "off"}),
                  ("pymssql · TDS 7.0(암호화 없음, 오래된 방식)", {**base, "driver": "pymssql", "tds_version": "7.0"})]
    return plans


def try_plan(conn: dict, password: str) -> tuple[bool, str]:
    from sqlalchemy import text

    drv = conn.get("driver") or default_driver(conn.get("type", "mssql"))
    if not driver_ok(drv):
        return False, f"'{drv}' 드라이버 없음"
    try:
        eng = make_engine(conn, password)
        try:
            with eng.connect() as c:
                c.execute(text(_probe_sql(conn.get("type", "mssql")))).fetchall()
        finally:
            eng.dispose()
        return True, "연결 성공"
    except Exception as exc:  # noqa: BLE001
        m = sanitize(f"{type(exc).__name__}: {exc}", password)
        h = explain(m)
        return False, (h.split("→")[0].strip() + " · " if h else "") + m[:220]


def find_connection(conn: dict, password: str, allow_plain: bool = False, progress=None) -> tuple[dict | None, list[dict]]:
    """방법을 차례로 시도해 처음 성공한 접속 정보를 돌려준다. 아이디·비밀번호·DB 이름 오류면 더 시도하지 않는다."""
    plans = connection_plans(conn, allow_plain)
    tried = []
    for i, (label, patch) in enumerate(plans, 1):
        if progress:
            progress(i, len(plans), label)
        cand = {**conn, **patch}
        ok, msg = try_plan(cand, password)
        tried.append({"방법": label, "결과": "✅ 성공" if ok else "❌ 실패", "내용": msg})
        if ok:
            return cand, tried
        if re.search(r"18456|login failed|4060|cannot open database", msg.lower()):
            tried.append({"방법": "(중단)", "결과": "—", "내용": "아이디·비밀번호 또는 DB 이름 문제라 다른 방법으로는 해결되지 않습니다."})
            break
    return None, tried
