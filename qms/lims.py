"""LIMS(실험실정보관리시스템) 연동 — LIMS 시험 결과를 QMS 모니터링 데이터로 자동 반영한다.

연동 방식(공장 LIMS 제품·보안 정책에 맞게 선택)
  sql   LIMS DB 직접 조회(읽기 전용 계정 권장) — SQLAlchemy URL (MSSQL·Oracle·PostgreSQL·MySQL·SQLite 등)
  rest  LIMS REST API(JSON) — Bearer 토큰 인증
  file  LIMS 내보내기 파일(CSV·XLSX, 긴 형식) 폴더
  demo  시연용 LIMS DB(data/lims_demo.db, SQLite) — 데모 데이터에서 생성

표준 형식(긴 형식) — 한 행 = 시험 결과 1건
  sampled_at    시료 채취 일시            sample_point  채취 지점(KILN_FEED, CLINKER, CLINKER_DAILY, CEMENT_MILL, CEMENT_LOT)
  test_code     시험 항목 코드(CAO, BLAINE, CS28 …)    value  결과값('<0.1' 같은 부등호 값은 숫자만 쓰고 건수를 보고)
  product       품종 코드(OPC, HES …, 시멘트·물성만)     status 결과 상태(승인된 결과만 반영)
  unit          단위                          updated_at    결과 확정·수정 일시(증분 동기화 기준)
  LIMS 열 이름이 다르면 column_map 으로 바꾸거나, SQL 조회문에서 AS 별칭으로 맞춘다.

매핑   (sample_point, test_code) → (QMS 테이블, 열, 환산계수, 오프셋)  — 화면에서 수정, data/lims.json 에 저장
동기화 워터마크(updated_at 최댓값) 이후 결과만 조회 → 승인 필터 → 매핑 → 넓은 형식 → 열 단위 병합 저장(store.save_raw)
       → 늦게 나온 28일 강도도 같은 로트 행에 채워지고, 먼저 들어온 값은 지워지지 않는다.
비밀값 DB 비밀번호·API 토큰은 환경변수 QMS_LIMS_PASSWORD / QMS_LIMS_TOKEN 또는 .streamlit/secrets.toml [lims]
       (password, token) 에 둔다. 설정 파일(lims.json)·저장소에는 저장하지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import numpy as np
import pandas as pd

from .standards import DATA_DIR, TABLES
from .store import DB_PATH, RAW_COLUMNS, TEXT_COLUMNS, load_raw, save_raw

LIMS_CONFIG_PATH = DATA_DIR / "lims.json"
LIMS_LOG_PATH = DATA_DIR / "lims_log.jsonl"
LIMS_DEMO_DB = DATA_DIR / "lims_demo.db"
SECRETS_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
STD_COLUMNS = ["sampled_at", "sample_point", "test_code", "value", "product", "status", "unit", "updated_at"]
MODES = {"demo": "데모 LIMS(시연용 SQLite)", "sql": "DB 직접 조회(SQL)", "rest": "REST API", "file": "내보내기 파일 폴더"}

SAMPLE_POINTS = {"raw_meal": "KILN_FEED", "clinker": "CLINKER", "xrd": "CLINKER_DAILY", "cement": "CEMENT_MILL",
                 "physical": "CEMENT_LOT"}
# QMS 열 → LIMS 시험코드(기본값 예시 — 공장 LIMS 코드표로 교체)
TEST_CODES = {
    "rm_cao": "CAO", "rm_sio2": "SIO2", "rm_al2o3": "AL2O3", "rm_fe2o3": "FE2O3", "rm_mgo": "MGO", "rm_so3": "SO3",
    "rm_k2o": "K2O", "rm_na2o": "NA2O", "rm_r90": "R90", "rm_r200": "R200", "rm_loi": "LOI",
    "clk_cao": "CAO", "clk_sio2": "SIO2", "clk_al2o3": "AL2O3", "clk_fe2o3": "FE2O3", "clk_mgo": "MGO",
    "clk_so3": "SO3", "clk_k2o": "K2O", "clk_na2o": "NA2O", "clk_fcao": "FCAO", "clk_lw": "LW",
    "xrd_alite": "ALITE", "xrd_belite": "BELITE", "xrd_c3a": "C3A", "xrd_c4af": "C4AF", "xrd_fcao": "FCAO_XRD",
    "xrd_periclase": "PERICLASE", "clk_cr": "CR_TOTAL", "clk_crvi": "CR6",
    "cem_blaine": "BLAINE", "cem_r45": "R45", "cem_so3": "SO3", "cem_loi": "LOI", "cem_mgo": "MGO", "cem_ls": "LS_ADD",
    "phy_ist": "IST", "phy_fst": "FST", "phy_autoclave": "AUTOCLAVE", "phy_s1": "CS1", "phy_s3": "CS3", "phy_s7": "CS7",
    "phy_s28": "CS28", "phy_crvi": "CR6", "lab_temp": "LAB_TEMP", "lab_rh": "LAB_RH", "lab_cure_temp": "CURE_TEMP",
    "sand_lot": "SAND_LOT", "operator": "OPERATOR",
}
# DCS 운전값(밀 투입량·온도 등)은 LIMS 대상이 아니므로 매핑하지 않는다.
DCS_ONLY = {"cem_mill_feed", "cem_mill_temp"}

DEFAULT_QUERY = """SELECT s.sampled_at   AS sampled_at,
       s.sample_point AS sample_point,
       r.test_code    AS test_code,
       r.value        AS value,
       s.product      AS product,
       r.status       AS status,
       r.unit         AS unit,
       r.approved_at  AS updated_at
FROM lims_result r
JOIN lims_sample s ON s.sample_id = r.sample_id
WHERE r.approved_at > :since
ORDER BY r.approved_at"""


def default_mapping() -> list[dict]:
    rows = []
    for table, cols in RAW_COLUMNS.items():
        if table not in SAMPLE_POINTS:
            continue
        for c in cols:
            if c == "product" or c in DCS_ONLY or c not in TEST_CODES:
                continue
            rows.append({"sample_point": SAMPLE_POINTS[table], "test_code": TEST_CODES[c], "table": table, "column": c,
                         "factor": 1.0, "offset": 0.0})
    return rows


@dataclass
class LimsConfig:
    enabled: bool = False
    mode: str = "demo"
    sql_url: str = ""                  # 예: mssql+pyodbc://qms_reader:{password}@LIMS-DB/LIMS?driver=ODBC+Driver+18+for+SQL+Server
    sql_query: str = DEFAULT_QUERY
    rest_url: str = ""
    rest_records_path: str = "data"    # 응답 JSON에서 결과 목록 위치(점 표기, 예: result.items)
    rest_since_param: str = "updated_since"
    file_dir: str = ""
    column_map: dict = field(default_factory=dict)     # LIMS 열 이름 → 표준 열 이름
    product_map: dict = field(default_factory=lambda: {"OPC": "1종", "HES": "3종", "1종": "1종", "3종": "3종"})
    status_ok: list = field(default_factory=lambda: ["APPROVED", "승인", "A", "FINAL"])
    lookback_days: int = 35
    watermark: str | None = None
    mapping: list = field(default_factory=default_mapping)

    def to_dict(self) -> dict:
        return asdict(self)


def load_lims_config(path: Path = LIMS_CONFIG_PATH) -> LimsConfig:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    return LimsConfig(**{k: v for k, v in data.items() if k in LimsConfig.__dataclass_fields__})


def save_lims_config(cfg: LimsConfig, path: Path = LIMS_CONFIG_PATH) -> None:
    d = cfg.to_dict()
    if "{password}" not in d.get("sql_url", "") and re.search(r"://[^:/@]+:[^@{]+@", d.get("sql_url", "")):
        raise ValueError("DB 비밀번호를 URL에 직접 넣지 마세요. {password} 자리표시자를 쓰고 QMS_LIMS_PASSWORD 로 설정하세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _secret(name: str) -> str:
    env = {"password": "QMS_LIMS_PASSWORD", "token": "QMS_LIMS_TOKEN"}[name]
    if os.environ.get(env):
        return os.environ[env]
    if SECRETS_PATH.exists():
        try:
            import tomllib
            return str(tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8")).get("lims", {}).get(name, ""))
        except Exception:  # noqa: BLE001 - 비밀 설정 파싱 실패 시 빈 값
            return ""
    return ""


def secret_status() -> dict[str, bool]:
    return {"password": bool(_secret("password")), "token": bool(_secret("token"))}


# ── 조회 ────────────────────────────────────────────────────────────────
def _since(cfg: LimsConfig, now: datetime | None = None) -> datetime:
    if cfg.watermark:
        try:
            return pd.Timestamp(cfg.watermark).to_pydatetime()
        except (ValueError, TypeError):
            pass
    return (now or datetime.now()) - timedelta(days=int(cfg.lookback_days))


def _engine_url(cfg: LimsConfig) -> str:
    if cfg.mode == "demo":
        return f"sqlite:///{LIMS_DEMO_DB}"
    url = cfg.sql_url
    if "{password}" in url:
        url = url.replace("{password}", quote_plus(_secret("password")))
    return url


def fetch_sql(cfg: LimsConfig, since: datetime) -> pd.DataFrame:
    url = _engine_url(cfg)
    if not url:
        raise ValueError("SQL 연결 주소(sql_url)가 비어 있습니다.")
    if url.startswith("sqlite:///"):
        path = Path(url[len("sqlite:///"):])
        if not path.exists():
            raise FileNotFoundError(f"LIMS DB 파일이 없습니다: {path}")
        with closing(sqlite3.connect(path)) as con:
            q = cfg.sql_query.replace(":since", "?")
            return pd.read_sql(q, con, params=(since.strftime("%Y-%m-%d %H:%M:%S"),))
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:  # pragma: no cover - 선택 패키지
        raise RuntimeError("SQL 연동에는 SQLAlchemy와 DB 드라이버가 필요합니다(pip install sqlalchemy pyodbc 등).") from exc
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(cfg.sql_query), conn, params={"since": since})
    finally:
        engine.dispose()


def _dig(obj, path: str):
    for part in [p for p in path.split(".") if p]:
        obj = obj.get(part, []) if isinstance(obj, dict) else []
    return obj


def fetch_rest(cfg: LimsConfig, since: datetime, session=None) -> pd.DataFrame:
    if not cfg.rest_url:
        raise ValueError("REST API 주소(rest_url)가 비어 있습니다.")
    import requests

    sess = session or requests
    headers = {"Accept": "application/json"}
    token = _secret("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = sess.get(cfg.rest_url, params={cfg.rest_since_param: since.isoformat(timespec="seconds")}, headers=headers,
                    timeout=30)
    resp.raise_for_status()
    records = _dig(resp.json(), cfg.rest_records_path) if cfg.rest_records_path else resp.json()
    return pd.DataFrame(records if isinstance(records, list) else [])


def fetch_files(cfg: LimsConfig) -> pd.DataFrame:
    folder = Path(cfg.file_dir)
    if not cfg.file_dir or not folder.is_dir():
        raise ValueError(f"내보내기 폴더가 없습니다: {cfg.file_dir}")
    frames = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() == ".csv":
            frames.append(pd.read_csv(f))
        elif f.suffix.lower() in (".xlsx", ".xls"):
            frames.append(pd.read_excel(f))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STD_COLUMNS)


def fetch(cfg: LimsConfig, since: datetime, session=None) -> pd.DataFrame:
    if cfg.mode in ("sql", "demo"):
        return fetch_sql(cfg, since)
    if cfg.mode == "rest":
        return fetch_rest(cfg, since, session)
    if cfg.mode == "file":
        return fetch_files(cfg)
    raise ValueError(f"알 수 없는 연동 방식: {cfg.mode}")


# ── 변환 ────────────────────────────────────────────────────────────────
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")


def parse_value(v) -> tuple[float, bool]:
    """결과값 → (숫자, 부등호 여부). '<0.1' → (0.1, True), '12,345' → 12345, 숫자 아님 → (nan, False)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return float("nan"), False
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v), False
    s = str(v).strip()
    censored = s.startswith(("<", ">", "≤", "≥"))
    s2 = s.replace(",", "") if re.fullmatch(r"[<>≤≥]?\s*\d{1,3}(,\d{3})+(\.\d+)?", s) else s.replace(",", ".")
    m = _NUM.search(s2)
    return (float(m.group()) if m else float("nan")), censored


@dataclass
class SyncReport:
    mode: str
    since: str
    n_fetched: int = 0
    n_status_skipped: int = 0
    n_invalid: int = 0
    n_censored: int = 0
    n_unmapped: int = 0
    unmapped: list = field(default_factory=list)       # [(sample_point, test_code, 건수)]
    n_mapped: int = 0
    rows_by_table: dict = field(default_factory=dict)
    cells_new: int = 0
    cells_changed: int = 0
    watermark_after: str | None = None
    saved: bool = False
    errors: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    wide: dict = field(default_factory=dict, repr=False)

    def summary_text(self) -> str:
        if self.errors:
            return "실패: " + "; ".join(self.errors)
        t = ", ".join(f"{TABLES[k]['label']} {v}행" for k, v in self.rows_by_table.items()) or "반영할 결과 없음"
        return (f"조회 {self.n_fetched}건 → 반영 {self.n_mapped}건({t}) · 신규 칸 {self.cells_new} · 변경 칸 {self.cells_changed} · "
                f"미승인 제외 {self.n_status_skipped} · 미매핑 {self.n_unmapped} · 숫자 아님 {self.n_invalid}")


def normalize(df: pd.DataFrame, cfg: LimsConfig, rep: SyncReport) -> pd.DataFrame:
    d = df.rename(columns={k: v for k, v in (cfg.column_map or {}).items() if k in df.columns}).copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    missing = [c for c in ("sampled_at", "sample_point", "test_code", "value") if c not in d.columns]
    if missing:
        raise ValueError(f"LIMS 결과에 필수 열이 없습니다: {', '.join(missing)} (column_map 또는 SQL 별칭으로 맞추세요)")
    for c in ("product", "status", "unit", "updated_at"):
        if c not in d:
            d[c] = None
    d["sampled_at"] = pd.to_datetime(d["sampled_at"], errors="coerce", format="mixed")
    d["updated_at"] = pd.to_datetime(d["updated_at"], errors="coerce", format="mixed")
    d = d[d["sampled_at"].notna()].copy()
    d["sample_point"] = d["sample_point"].astype(str).str.strip().str.upper()
    d["test_code"] = d["test_code"].astype(str).str.strip().str.upper()
    if cfg.status_ok:
        ok = {str(s).strip().upper() for s in cfg.status_ok}
        st = d["status"].astype(str).str.strip().str.upper()
        keep = d["status"].isna() | st.isin(ok)
        rep.n_status_skipped = int((~keep).sum())
        d = d[keep].copy()
    pm = {str(k).strip().upper(): v for k, v in (cfg.product_map or {}).items()}
    d["product"] = d["product"].map(lambda p: pm.get(str(p).strip().upper(), p) if pd.notna(p) and str(p).strip() else None)
    return d


def apply_mapping(d: pd.DataFrame, cfg: LimsConfig, rep: SyncReport) -> dict[str, pd.DataFrame]:
    mp = pd.DataFrame(cfg.mapping or [])
    if len(mp) == 0:
        rep.n_unmapped = len(d)
        return {}
    mp = mp.copy()
    mp["sample_point"] = mp["sample_point"].astype(str).str.strip().str.upper()
    mp["test_code"] = mp["test_code"].astype(str).str.strip().str.upper()
    mp["factor"] = pd.to_numeric(mp.get("factor", 1.0), errors="coerce").fillna(1.0)
    mp["offset"] = pd.to_numeric(mp.get("offset", 0.0), errors="coerce").fillna(0.0)
    m = d.merge(mp[["sample_point", "test_code", "table", "column", "factor", "offset"]],
                on=["sample_point", "test_code"], how="left")
    unm = m[m["table"].isna()]
    rep.n_unmapped = len(unm)
    rep.unmapped = [(sp, tc, int(n)) for (sp, tc), n in Counter(zip(unm["sample_point"], unm["test_code"])).most_common(20)]
    m = m[m["table"].notna()].copy()
    m = m[m["table"].isin(RAW_COLUMNS) & m.apply(lambda r: r["column"] in RAW_COLUMNS.get(r["table"], []), axis=1)] \
        if len(m) else m
    text = m["column"].isin(TEXT_COLUMNS)
    parsed = m["value"].map(parse_value)
    m["num"] = [p[0] for p in parsed]
    m["censored"] = [p[1] for p in parsed]
    m.loc[~text, "num"] = m.loc[~text, "num"] * m.loc[~text, "factor"] + m.loc[~text, "offset"]
    bad = (~text) & m["num"].isna()
    rep.n_invalid = int(bad.sum())
    rep.n_censored = int(m.loc[~text, "censored"].sum())
    m = m[~bad].copy()
    text = m["column"].isin(TEXT_COLUMNS)
    m["val"] = m["num"].astype(object)
    m.loc[text, "val"] = m.loc[text, "value"].astype(str)
    m = m.sort_values("updated_at", na_position="first", kind="stable")
    out: dict[str, pd.DataFrame] = {}
    for table, g in m.groupby("table"):
        by_product = TABLES[table]["by_product"]
        if by_product:
            miss = g["product"].isna() | ~g["product"].isin(["1종", "3종"] + list(set((cfg.product_map or {}).values())))
            if miss.any():
                rep.messages.append(f"[{TABLES[table]['label']}] 품종을 알 수 없는 결과 {int(miss.sum())}건 제외(product_map 확인)")
            g = g[~miss]
        if len(g) == 0:
            continue
        keys = ["sampled_at"] + (["product"] if by_product else [])
        # 같은 시료·항목이 여러 번 나오면(재시험·수정) 가장 늦게 확정된 값을 쓴다
        wide = g.groupby(keys + ["column"], sort=False)["val"].last().unstack("column").reset_index()
        wide = wide.rename(columns={"sampled_at": "timestamp"})
        wide.columns.name = None
        for c in wide.columns:
            if c not in TEXT_COLUMNS and c not in ("timestamp", "product"):
                wide[c] = pd.to_numeric(wide[c], errors="coerce")
        out[table] = wide
        rep.rows_by_table[table] = len(wide)
    rep.n_mapped = int(len(m))
    return out


def _cell_diff(before: dict[str, pd.DataFrame], wide: dict[str, pd.DataFrame]) -> tuple[int, int]:
    new = changed = 0
    for table, w in wide.items():
        b = before.get(table)
        keys = ["timestamp"] + (["product"] if TABLES[table]["by_product"] else [])
        cols = [c for c in w.columns if c not in keys]
        if b is None or len(b) == 0:
            new += int(w[cols].notna().sum().sum())
            continue
        b = b.copy()
        b["timestamp"] = pd.to_datetime(b["timestamp"])
        j = w.merge(b[keys + [c for c in cols if c in b.columns]], on=keys, how="left", suffixes=("", "__old"))
        for c in cols:
            old = j[f"{c}__old"] if f"{c}__old" in j else pd.Series(np.nan, index=j.index)
            has_new = j[c].notna()
            new += int((has_new & old.isna()).sum())
            if c in TEXT_COLUMNS:
                changed += int((has_new & old.notna() & (j[c].astype(str) != old.astype(str))).sum())
            else:
                diff = (pd.to_numeric(j[c], errors="coerce") - pd.to_numeric(old, errors="coerce")).abs() > 1e-9
                changed += int((has_new & old.notna() & diff).sum())
    return new, changed


def sync(cfg: LimsConfig, db_path: Path = DB_PATH, dry_run: bool = False, now: datetime | None = None,
         session=None, log_path: Path = LIMS_LOG_PATH, persist_watermark: bool = True) -> SyncReport:
    """LIMS → QMS 증분 동기화. dry_run=True 이면 저장·워터마크 갱신 없이 결과만 보고."""
    since = _since(cfg, now)
    rep = SyncReport(cfg.mode, since.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        if cfg.mode == "demo" and not LIMS_DEMO_DB.exists():
            create_demo_lims(load_raw(db_path), LIMS_DEMO_DB)
            rep.messages.append("데모 LIMS DB를 새로 만들었습니다.")
        raw = fetch(cfg, since, session)
        rep.n_fetched = len(raw)
        if len(raw):
            d = normalize(raw, cfg, rep)
            if cfg.mode == "file" and d["updated_at"].notna().any():
                d = d[d["updated_at"].isna() | (d["updated_at"] > pd.Timestamp(since))]
            wide = apply_mapping(d, cfg, rep)
            rep.wide = wide
            if wide:
                rep.cells_new, rep.cells_changed = _cell_diff(load_raw(db_path), wide)
                if not dry_run:
                    save_raw(wide, path=db_path, replace=False)
                    rep.saved = True
            wm = d["updated_at"].max() if "updated_at" in d and d["updated_at"].notna().any() else None
            if wm is not None and pd.notna(wm):
                rep.watermark_after = pd.Timestamp(wm).strftime("%Y-%m-%d %H:%M:%S")
                if not dry_run and persist_watermark:
                    cfg.watermark = rep.watermark_after
                    save_lims_config(cfg)
    except Exception as exc:  # noqa: BLE001 - 연동 실패 원인을 화면·로그에 표시
        rep.errors.append(f"{type(exc).__name__}: {exc}")
    _log_sync(rep, dry_run, log_path)
    return rep


def _log_sync(rep: SyncReport, dry_run: bool, path: Path) -> None:
    entry = {k: v for k, v in asdict(rep).items() if k != "wide"}
    entry["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["dry_run"] = dry_run
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def read_sync_log(path: Path = LIMS_LOG_PATH, limit: int = 100) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def test_connection(cfg: LimsConfig, session=None) -> tuple[bool, str, pd.DataFrame]:
    """최근 lookback_days 범위를 조회해 연결·열 구성을 확인(저장 안 함)."""
    try:
        if cfg.mode == "demo" and not LIMS_DEMO_DB.exists():
            create_demo_lims(load_raw(), LIMS_DEMO_DB)
        df = fetch(cfg, datetime.now() - timedelta(days=int(cfg.lookback_days)), session)
    except Exception as exc:  # noqa: BLE001
        return False, f"연결 실패 — {type(exc).__name__}: {exc}", pd.DataFrame()
    cols = [str(c).lower() for c in df.rename(columns=cfg.column_map or {}).columns]
    miss = [c for c in ("sampled_at", "sample_point", "test_code", "value") if c not in cols]
    if miss:
        return False, f"연결은 되었으나 필수 열이 없습니다: {', '.join(miss)}", df.head(20)
    return True, f"연결 성공 — {len(df)}건 조회(최근 {cfg.lookback_days}일)", df.head(20)


# ── 데모 LIMS ───────────────────────────────────────────────────────────
TEST_TAT_HOURS = {"KILN_FEED": 1.0, "CLINKER": 1.5, "CLINKER_DAILY": 6.0, "CEMENT_MILL": 1.5}
AGE_DAYS = {"CS1": 1, "CS3": 3, "CS7": 7, "CS28": 28, "AUTOCLAVE": 1, "CR6": 1}


def create_demo_lims(raw: dict[str, pd.DataFrame], path: Path = LIMS_DEMO_DB, days: int = 10,
                     now: datetime | None = None) -> dict[str, int]:
    """QMS 데이터(최근 days 일)를 LIMS 형식(시료·결과 테이블)으로 만든다. 승인 대기·미등록 시험코드도 일부 포함."""
    rows_s, rows_r = [], []
    sid = 0
    product_code = {"1종": "OPC", "3종": "HES"}
    rng = np.random.default_rng(11)
    ends = [pd.to_datetime(df["timestamp"]).max() for df in raw.values() if len(df)]
    if not ends:
        return {"samples": 0, "results": 0}
    end = max(ends)
    now = now or end.to_pydatetime() + timedelta(hours=1)
    start = end - pd.Timedelta(days=days)
    for table, sp in SAMPLE_POINTS.items():
        df = raw.get(table)
        if df is None or len(df) == 0:
            continue
        df = df[pd.to_datetime(df["timestamp"]) >= start]
        for _, r in df.iterrows():
            sid += 1
            ts = pd.Timestamp(r["timestamp"])
            prod = product_code.get(r.get("product")) if "product" in df.columns else None
            rows_s.append((sid, sp, ts.strftime("%Y-%m-%d %H:%M:%S"), prod))
            for col in RAW_COLUMNS[table]:
                if col == "product" or col in DCS_ONLY or col not in TEST_CODES or col not in r or pd.isna(r[col]):
                    continue
                code = TEST_CODES[col]
                tat = timedelta(days=AGE_DAYS.get(code, 0), hours=TEST_TAT_HOURS.get(sp, 2.0))
                approved = ts + tat
                if approved > pd.Timestamp(now):
                    continue
                status = "PENDING" if rng.random() < 0.02 else "APPROVED"
                val = r[col]
                value = str(val) if col in TEXT_COLUMNS else (f"{float(val):.3f}")
                rows_r.append((sid, code, value, "", status, approved.strftime("%Y-%m-%d %H:%M:%S")))
            if sp == "CEMENT_LOT":       # QMS에 없는 시험(미매핑 예시)
                rows_r.append((sid, "WATER_DEMAND", f"{rng.normal(26.5, 0.4):.1f}", "%", "APPROVED",
                               (ts + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE lims_sample (sample_id INTEGER PRIMARY KEY, sample_point TEXT, sampled_at TEXT, product TEXT)")
        con.execute("CREATE TABLE lims_result (sample_id INTEGER, test_code TEXT, value TEXT, unit TEXT, status TEXT, "
                    "approved_at TEXT)")
        con.executemany("INSERT INTO lims_sample VALUES (?,?,?,?)", rows_s)
        con.executemany("INSERT INTO lims_result VALUES (?,?,?,?,?,?)", rows_r)
        con.commit()
    return {"samples": len(rows_s), "results": len(rows_r)}
