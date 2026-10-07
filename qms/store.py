"""데이터 저장소 (SQLite) 및 엑셀 업로드 처리.

- 원 데이터(산화물·운전값·시험값)만 저장하고, LSF·Bogue 등 파생값은 불러올 때 계산한다.
- 업로드 시 (timestamp[, product]) 기준으로 중복을 덮어쓴다(upsert).
- 알림 처리 상태(확인/조치중/종결, 담당자, 메모, 발송 여부)도 같은 DB에 저장한다.
"""

from __future__ import annotations

import io
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import chemistry as chem
from .standards import DATA_DIR, TABLES, SpecRegistry

DB_PATH = DATA_DIR / "qms.db"
ALERT_DB_PATH = DATA_DIR / "alerts.db"   # 알림 처리상태는 별도 DB(데이터 캐시와 분리)

# 업로드·저장 대상 원 데이터 열(파생값 제외)
RAW_COLUMNS: dict[str, list[str]] = {
    "raw_meal": ["rm_cao", "rm_sio2", "rm_al2o3", "rm_fe2o3", "rm_mgo", "rm_so3", "rm_k2o", "rm_na2o",
                 "rm_r90", "rm_r200"],
    "kiln": ["kiln_feed", "coal_rate", "kiln_bzt", "kiln_o2", "kiln_co", "kiln_torque", "kiln_calc_temp",
             "kiln_sec_air"],
    "clinker": ["clk_cao", "clk_sio2", "clk_al2o3", "clk_fe2o3", "clk_mgo", "clk_so3", "clk_k2o", "clk_na2o",
                "clk_fcao", "clk_lw"],
    "cement": ["product", "cem_blaine", "cem_r45", "cem_so3", "cem_loi", "cem_mgo", "cem_mill_feed",
               "cem_mill_temp"],
    "physical": ["product", "phy_ist", "phy_fst", "phy_autoclave", "phy_s1", "phy_s3", "phy_s7", "phy_s28",
                 "lab_temp", "lab_rh", "lab_cure_temp", "sand_lot", "operator"],
}
TEXT_COLUMNS = {"product", "sand_lot", "operator"}

# 엑셀 템플릿 시트명 ↔ 테이블
SHEET_NAMES = {"raw_meal": "생료", "kiln": "킬른", "clinker": "클링커", "cement": "시멘트", "physical": "물성"}


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def _ensure_alert_table(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS alert_status (
            event_id TEXT PRIMARY KEY,
            status TEXT DEFAULT '신규',
            assignee TEXT DEFAULT '',
            note TEXT DEFAULT '',
            notified INTEGER DEFAULT 0,
            updated_at TEXT
        )""")


@dataclass
class DataStore:
    """공정·품질 데이터 묶음. tables 는 파생값이 계산된 상태."""
    tables: dict[str, pd.DataFrame]

    # 조회 ---------------------------------------------------------------
    def table_of(self, key: str, registry: SpecRegistry) -> pd.DataFrame | None:
        item = registry.get(key)
        if item is None:
            return None
        return self.tables.get(item.table)

    def series(self, key: str, registry: SpecRegistry, product: str | None = None,
               start: datetime | None = None, end: datetime | None = None) -> pd.Series:
        """항목의 시계열(timestamp 인덱스, 결측 제거)."""
        df = self.table_of(key, registry)
        if df is None or key not in df.columns:
            return pd.Series(dtype=float)
        if product is not None and "product" in df.columns:
            df = df[df["product"] == product]
        s = df.set_index("timestamp")[key].astype(float).dropna()
        if start is not None:
            s = s[s.index >= pd.Timestamp(start)]
        if end is not None:
            s = s[s.index <= pd.Timestamp(end)]
        return s.sort_index()

    def period(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        stamps = [df["timestamp"] for df in self.tables.values() if len(df)]
        if not stamps:
            return None
        allts = pd.concat(stamps)
        return allts.min(), allts.max()

    def is_empty(self) -> bool:
        return all(len(df) == 0 for df in self.tables.values())

    def filtered(self, start=None, end=None) -> "DataStore":
        out = {}
        for name, df in self.tables.items():
            m = pd.Series(True, index=df.index)
            if start is not None:
                m &= df["timestamp"] >= pd.Timestamp(start)
            if end is not None:
                m &= df["timestamp"] <= pd.Timestamp(end)
            out[name] = df[m].reset_index(drop=True)
        return DataStore(out)


# ── 파생값 계산 ─────────────────────────────────────────────────────────
def enrich(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """원 데이터에 파생값(LSF·SM·IM·Bogue 등)을 추가한다."""
    out = {}
    for name in TABLES:
        df = raw.get(name, pd.DataFrame(columns=["timestamp"])).copy()
        if "timestamp" in df:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        if name == "raw_meal" and len(df):
            df = chem.add_raw_meal_moduli(df)
        if name == "clinker" and len(df):
            df = chem.add_clinker_derived(df)
        out[name] = df
    return out


def build_store(raw: dict[str, pd.DataFrame]) -> DataStore:
    return DataStore(enrich(raw))


# ── SQLite 입출력 ───────────────────────────────────────────────────────
def save_raw(raw: dict[str, pd.DataFrame], path: Path = DB_PATH, replace: bool = False) -> dict[str, int]:
    """원 데이터를 DB에 저장한다. replace=False 이면 기존 데이터와 병합(upsert)."""
    counts = {}
    with closing(_connect(path)) as con:
        for name, df in raw.items():
            if name not in RAW_COLUMNS:
                continue
            cols = ["timestamp"] + [c for c in RAW_COLUMNS[name] if c in df.columns]
            new = df[cols].copy()
            new["timestamp"] = pd.to_datetime(new["timestamp"])
            if not replace:
                try:
                    old = pd.read_sql(f"SELECT * FROM {name}", con, parse_dates=["timestamp"])
                    new = pd.concat([old, new], ignore_index=True)
                except (pd.errors.DatabaseError, sqlite3.OperationalError):
                    pass
            keys = ["timestamp"] + (["product"] if "product" in new.columns else [])
            new = new.drop_duplicates(subset=keys, keep="last").sort_values("timestamp")
            new["timestamp"] = new["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
            new.to_sql(name, con, if_exists="replace", index=False)
            counts[name] = len(new)
        con.commit()
    return counts


def load_raw(path: Path = DB_PATH) -> dict[str, pd.DataFrame]:
    raw: dict[str, pd.DataFrame] = {}
    if not path.exists():
        return {name: pd.DataFrame(columns=["timestamp"] + RAW_COLUMNS[name]) for name in TABLES}
    with closing(_connect(path)) as con:
        for name in TABLES:
            try:
                raw[name] = pd.read_sql(f"SELECT * FROM {name}", con, parse_dates=["timestamp"])
            except (pd.errors.DatabaseError, sqlite3.OperationalError):
                raw[name] = pd.DataFrame(columns=["timestamp"] + RAW_COLUMNS[name])
    return raw


def load_store(path: Path = DB_PATH) -> DataStore:
    return build_store(load_raw(path))


def clear_db(path: Path = DB_PATH, alert_path: Path | None = ALERT_DB_PATH) -> None:
    for p in (path, alert_path):
        if p is not None and p.exists():
            p.unlink()


def db_mtime(path: Path = DB_PATH) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


# ── 알림 상태 ───────────────────────────────────────────────────────────
def load_alert_status(path: Path = ALERT_DB_PATH) -> pd.DataFrame:
    with closing(_connect(path)) as con:
        _ensure_alert_table(con)
        return pd.read_sql("SELECT * FROM alert_status", con)


def update_alert_status(event_id: str, path: Path = ALERT_DB_PATH, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("status", "assignee", "note", "notified")}
    allowed["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(_connect(path)) as con:
        _ensure_alert_table(con)
        con.execute("INSERT OR IGNORE INTO alert_status(event_id) VALUES (?)", (event_id,))
        sets = ", ".join(f"{k} = ?" for k in allowed)
        con.execute(f"UPDATE alert_status SET {sets} WHERE event_id = ?", (*allowed.values(), event_id))
        con.commit()


# ── 엑셀 템플릿 / 업로드 ────────────────────────────────────────────────
def template_workbook(registry: SpecRegistry, sample: dict[str, pd.DataFrame] | None = None) -> bytes:
    """데이터 입력용 엑셀 템플릿(시트별 열 정의 + 예시 행)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    guide = wb.active
    guide.title = "작성안내"
    guide.append(["Blue365 QMS 데이터 입력 템플릿"])
    guide["A1"].font = Font(bold=True, size=14)
    guide.append([])
    guide.append(["1. 시트별로 timestamp(측정일시, 예: 2026-10-07 14:00) 열은 필수입니다."])
    guide.append(["2. 시멘트·물성 시트는 product(품종: 1종/3종) 열이 필수입니다."])
    guide.append(["3. 2행(회색)은 항목 설명이며 업로드 시 자동으로 무시됩니다. 3행부터 입력하세요."])
    guide.append(["4. 같은 timestamp(+품종)가 이미 있으면 업로드 값으로 덮어씁니다."])
    guide.append(["5. LSF·SM·IM·C3S 등 파생값은 시스템이 자동 계산하므로 입력하지 않습니다."])
    guide.column_dimensions["A"].width = 90

    head_fill = PatternFill("solid", fgColor="1F3A5F")
    desc_fill = PatternFill("solid", fgColor="E7EBF0")
    for name, cols in RAW_COLUMNS.items():
        ws = wb.create_sheet(SHEET_NAMES[name])
        header = ["timestamp"] + cols
        ws.append(header)
        desc = ["측정일시"]
        for c in cols:
            item = registry.get(c)
            desc.append(item.label() if item else {"product": "품종(1종/3종)", "sand_lot": "표준사 Lot",
                                                    "operator": "시험 조"}.get(c, c))
        ws.append(desc)
        if sample is not None and name in sample and len(sample[name]):
            ex = sample[name].head(5)
            for _, r in ex.iterrows():
                vals = []
                for c in header:
                    v = r.get(c)
                    if isinstance(v, pd.Timestamp):
                        v = v.to_pydatetime()
                    elif isinstance(v, (float, np.floating)) and np.isnan(v):
                        v = None
                    vals.append(v)
                ws.append(vals)
        for ci in range(1, len(header) + 1):
            cell = ws.cell(row=1, column=ci)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center")
            d = ws.cell(row=2, column=ci)
            d.fill = desc_fill
            d.font = Font(italic=True, color="555555", size=9)
            ws.column_dimensions[get_column_letter(ci)].width = 18 if ci == 1 else 14
        ws.freeze_panes = "B3"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@dataclass
class UploadResult:
    tables: dict[str, pd.DataFrame]
    messages: list[str]
    errors: list[str]


def parse_upload(file_bytes: bytes, filename: str = "upload.xlsx") -> UploadResult:
    """엑셀(시트=테이블) 또는 CSV(파일명에 테이블명 포함) 업로드를 검증·변환한다."""
    messages: list[str] = []
    errors: list[str] = []
    tables: dict[str, pd.DataFrame] = {}
    name_by_sheet = {v: k for k, v in SHEET_NAMES.items()} | {k: k for k in SHEET_NAMES}

    if filename.lower().endswith(".csv"):
        target = next((t for t in RAW_COLUMNS if t in filename.lower()), None)
        if target is None:
            return UploadResult({}, [], ["CSV 파일명에 테이블명(raw_meal/kiln/clinker/cement/physical)을 포함하세요."])
        frames = {target: pd.read_csv(io.BytesIO(file_bytes))}
    else:
        try:
            sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
        except Exception as exc:  # noqa: BLE001 - 사용자에게 원인 메시지 표시
            return UploadResult({}, [], [f"엑셀 파일을 읽을 수 없습니다: {exc}"])
        frames = {name_by_sheet[s]: df for s, df in sheets.items() if s in name_by_sheet}
        if not frames:
            return UploadResult({}, [], ["인식 가능한 시트가 없습니다. 템플릿의 시트명(생료/킬른/클링커/시멘트/물성)을 사용하세요."])

    for name, df in frames.items():
        if "timestamp" not in df.columns:
            errors.append(f"[{SHEET_NAMES[name]}] timestamp 열이 없습니다.")
            continue
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", format="mixed")
        df = df[df["timestamp"].notna()]  # 설명 행·빈 행 제거
        if TABLES[name]["by_product"] and "product" not in df.columns:
            errors.append(f"[{SHEET_NAMES[name]}] product(품종) 열이 필요합니다.")
            continue
        known = [c for c in RAW_COLUMNS[name] if c in df.columns]
        unknown = [c for c in df.columns if c not in RAW_COLUMNS[name] and c != "timestamp"]
        if unknown:
            messages.append(f"[{SHEET_NAMES[name]}] 인식하지 않은 열은 무시: {', '.join(map(str, unknown))}")
        for c in known:
            if c not in TEXT_COLUMNS:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["timestamp"] + known]
        if len(df) == 0:
            messages.append(f"[{SHEET_NAMES[name]}] 데이터 행이 없습니다.")
            continue
        tables[name] = df
        messages.append(f"[{SHEET_NAMES[name]}] {len(df)}행 인식 ({df['timestamp'].min():%Y-%m-%d} ~ "
                        f"{df['timestamp'].max():%Y-%m-%d})")
    return UploadResult(tables, messages, errors)
