"""데이터 저장소 (SQLite) 및 엑셀 업로드 처리.

- 원 데이터(산화물·운전값·시험값)만 저장하고, LSF·Bogue 등 파생값은 불러올 때 계산한다.
- 업로드 시 (timestamp[, product]) 기준으로 열 단위 병합한다(upsert). 새 값이 있는 칸만 덮어쓰고
  빈 칸은 기존 값을 유지하므로, LIMS 결과가 시험 항목별로 늦게 들어와도 먼저 들어온 값이 지워지지 않는다.
- 알림 처리 상태(확인/조치중/종결, 담당자, 메모, 발송 여부)도 같은 DB에 저장한다.
"""

from __future__ import annotations

import io
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
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
    # line = 공정구분(호기·밀: 4K~7K, 4R/M~7R/M, 2C/M …), grade = 종류(LIMS 품명 원문, 예: 1종조합원료·1/2종크링커)
    "raw_meal": ["line", "grade", "rm_cao", "rm_sio2", "rm_al2o3", "rm_fe2o3", "rm_mgo", "rm_so3", "rm_k2o", "rm_na2o",
                 "rm_r90", "rm_r200", "rm_loi",
                 # 조합원료 투입비율(%) — 원료 배합. 라인(4·5/6·7)에 따라 쓰는 원료가 다르다.
                 "rm_mx_lime", "rm_mx_shale", "rm_mx_silica", "rm_mx_silica2", "rm_mx_ash", "rm_mx_sago",
                 "rm_mx_iron", "rm_mx_sand", "rm_mx_total"],
    "kiln": ["line", "kiln_feed", "coal_rate", "kiln_bzt", "kiln_o2", "kiln_co", "kiln_torque", "kiln_calc_temp",
             "kiln_sec_air"],
    "clinker": ["line", "grade", "clk_cao", "clk_sio2", "clk_al2o3", "clk_fe2o3", "clk_mgo", "clk_so3", "clk_k2o", "clk_na2o",
                "clk_fcao", "clk_lw"],
    "cement": ["line", "product", "cem_blaine", "cem_r45", "cem_so3", "cem_loi", "cem_mgo", "cem_ls", "cem_mill_feed",
               "cem_mill_temp",
               # 완성시멘트(밀 출구) 화학성분 — LSF·SM·IM 참고지수 계산에 사용
               "cem_cao", "cem_sio2", "cem_al2o3", "cem_fe2o3", "cem_na2o", "cem_k2o", "cem_cl", "cem_fcao"],
    "physical": ["product", "phy_ist", "phy_fst", "phy_autoclave", "phy_s1", "phy_s3", "phy_s7", "phy_s28",
                 "phy_crvi", "lab_temp", "lab_rh", "lab_cure_temp", "sand_lot", "operator"],
    "xrd": ["line", "grade", "xrd_alite", "xrd_belite", "xrd_c3a", "xrd_c4af", "xrd_fcao", "xrd_periclase", "clk_cr", "clk_crvi"],
}
TEXT_COLUMNS = {"product", "sand_lot", "operator", "line", "grade"}
# 공정구분(line)을 갖는 표 — 같은 채취 시각이라도 호기·밀이 다르면 다른 행(예: 6K·7K 동시 채취)
LINE_TABLES = ("raw_meal", "kiln", "clinker", "cement", "xrd")
TIME_MIN_COLUMNS = {"phy_ist", "phy_fst"}      # 응결시간: 분 단위 저장('HH:MM'·시각으로 들어오면 변환)


def _to_minutes(v):
    """'06:33'·datetime.time → 분. 이미 숫자면 그대로. 변환 불가면 그대로 둬 to_numeric 이 NaN 처리."""
    import datetime as _dt

    if v is None or (isinstance(v, float) and np.isnan(v)):
        return v
    if isinstance(v, _dt.time):
        return v.hour * 60 + v.minute
    if isinstance(v, _dt.datetime):
        return v.hour * 60 + v.minute
    s = str(v).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return v
    return v

# LIMS 내보내기는 '미시험' 칸을 0 으로 채운다 → 0 은 빈 값으로 본다(28일 강도 0 MPa 같은 가짜 이탈 방지).
# 0 이 실제 값일 수 있는 항목(배합 투입비율·석회석 첨가율)과 DCS 운전값(킬른)은 제외.
ZERO_IS_MISSING_TABLES = ("raw_meal", "clinker", "cement", "physical", "xrd")
ZERO_OK = {"cem_ls", "rm_mx_lime", "rm_mx_shale", "rm_mx_silica", "rm_mx_silica2", "rm_mx_ash", "rm_mx_sago",
           "rm_mx_iron", "rm_mx_sand", "rm_mx_total"}
SAMPLE_TIME_NAMES = ("채취시간", "시료채취시간", "채취시각", "채취time")


def zero_to_nan(df: pd.DataFrame, name: str) -> tuple[pd.DataFrame, dict]:
    """측정 항목의 0 을 NaN 으로(미시험). → (df, {열: 바꾼 건수})."""
    counts: dict[str, int] = {}
    if name not in ZERO_IS_MISSING_TABLES:
        return df, counts
    for c in RAW_COLUMNS.get(name, []):
        if c in TEXT_COLUMNS or c in ZERO_OK or c not in df.columns:
            continue
        col = pd.to_numeric(df[c], errors="coerce")
        m = col == 0
        if m.any():
            counts[c] = int(m.sum())
            df[c] = col.mask(m)
    return df, counts


def _combine_sample_time(df: pd.DataFrame) -> pd.DataFrame:
    """'채취일'(날짜) + '채취시간'(HH:MM) 을 합쳐 timestamp 로 — 하루 여러 시료가 한 행으로 합쳐지지 않게."""
    tcol = next((c for c in df.columns if _norm_header(c) in {_norm_header(x) for x in SAMPLE_TIME_NAMES}), None)
    if tcol is None or "timestamp" not in df.columns:
        return df
    base = pd.to_datetime(df["timestamp"], errors="coerce", format="mixed")
    if base.dropna().empty or ((base.dropna() - base.dropna().dt.normalize()) != pd.Timedelta(0)).any():
        return df.drop(columns=[tcol])                  # 이미 시각이 들어 있으면 그대로
    mins = df[tcol].map(_to_minutes)
    off = pd.to_timedelta(pd.to_numeric(mins, errors="coerce").fillna(0), unit="m")
    df = df.copy()
    df["timestamp"] = base.dt.normalize() + off
    return df.drop(columns=[tcol])


# 엑셀 템플릿 시트명 ↔ 테이블
SHEET_NAMES = {"raw_meal": "원료", "kiln": "킬른", "clinker": "클링커", "cement": "시멘트", "physical": "물성",
               "xrd": "클링커일일"}
# 업로드 양식의 안내용 시트(자료로 읽지 않음)
INFO_SHEETS = frozenset({"사용법", "항목사전", "공정구분", "코드표", "LIMS매핑", "작성예시"})
SHEET_ALIASES = {"XRD": "xrd", "클링커XRD": "xrd", "생료": "raw_meal"}   # 생료: 예전 양식 시트 이름(호환)

# LIMS·사람이 읽는 한글 머리글 → 내부 열 이름. LIMS에서 받은 엑셀을 그대로 붙여넣어도 인식한다.
# 같은 이름(예: CaO)이 표마다 다른 열로 가므로 표별로 따로 둔다. 키는 정규화해 비교한다.
_COMMON_ALIASES = {"채취일": "timestamp", "시료채취일": "timestamp", "채취일시": "timestamp", "검사일": "timestamp",
                   "검사일자": "timestamp", "일자": "timestamp", "날짜": "timestamp", "품명": "product", "품종": "product"}
_LINE_ALIASES = {"공정구분": "line", "공정": "line", "호기": "line", "라인": "line", "line": "line", "공정구분(호기)": "line"}
_GRADE_ALIASES = {"품명": "grade", "품종": "grade", "종류": "grade", "품명(종류)": "grade"}   # 품종 구분이 없는 표: 품명 = 종류(참고)
COL_ALIASES: dict[str, dict[str, str]] = {
    "raw_meal": {**_COMMON_ALIASES, **_LINE_ALIASES, **_GRADE_ALIASES, "킬른호기": "line", "원료밀": "line",
                 "cao": "rm_cao", "sio2": "rm_sio2", "al2o3": "rm_al2o3", "fe2o3": "rm_fe2o3",
                 "mgo": "rm_mgo", "so3(xrf)": "rm_so3", "so3": "rm_so3", "k2o": "rm_k2o", "na2o": "rm_na2o",
                 "90㎛": "rm_r90", "90um": "rm_r90", "r90": "rm_r90", "200㎛": "rm_r200", "200um": "rm_r200",
                 "r200": "rm_r200", "loi": "rm_loi", "강열감량": "rm_loi",
                 "석회석(%)": "rm_mx_lime", "석회석": "rm_mx_lime", "경석(%)": "rm_mx_shale", "shale(%)": "rm_mx_shale",
                 "규석(%)": "rm_mx_silica", "규석": "rm_mx_silica", "실리카(%)": "rm_mx_silica2", "실리카": "rm_mx_silica2",
                 "석탄회(%)": "rm_mx_ash", "coalshale(%)": "rm_mx_ash", "삼고(%)": "rm_mx_sago",
                 "고품위삼고(%)": "rm_mx_sago", "철질(%)": "rm_mx_iron", "철질": "rm_mx_iron", "주물사(%)": "rm_mx_sand",
                 "주물사": "rm_mx_sand", "투입량계(%)": "rm_mx_total", "투입량계": "rm_mx_total"},
    "kiln": {**_COMMON_ALIASES, **_LINE_ALIASES, "킬른": "line", "킬른호기": "line", "일시": "timestamp",
             "원료투입량": "kiln_feed", "킬른피드": "kiln_feed", "킬른피드량": "kiln_feed", "kilnfeed": "kiln_feed",
             "석탄투입량": "coal_rate", "석탄": "coal_rate", "coal": "coal_rate", "소성대온도": "kiln_bzt", "bzt": "kiln_bzt",
             "o2": "kiln_o2", "킬른입구o2": "kiln_o2", "co": "kiln_co", "킬른입구co": "kiln_co",
             "주모터부하": "kiln_torque", "킬른부하": "kiln_torque", "torque": "kiln_torque",
             "하소로출구온도": "kiln_calc_temp", "하소로온도": "kiln_calc_temp", "2차공기온도": "kiln_sec_air"},
    "clinker": {**_COMMON_ALIASES, **_LINE_ALIASES, **_GRADE_ALIASES, "클링커공정": "line", "크링커공정": "line",
                "킬른": "line", "cao": "clk_cao", "sio2": "clk_sio2", "al2o3": "clk_al2o3", "fe2o3": "clk_fe2o3",
                "mgo": "clk_mgo", "so3(xrf)": "clk_so3", "so3": "clk_so3", "k2o": "clk_k2o", "na2o": "clk_na2o",
                "f-cao(습식)": "clk_fcao", "f-cao(xrf)": "clk_fcao", "fcao": "clk_fcao", "유리석회": "clk_fcao",
                "자유석회": "clk_fcao", "용적비중": "clk_lw", "리터중량": "clk_lw", "용중": "clk_lw", "lw": "clk_lw"},
    "cement": {**_COMMON_ALIASES, **_LINE_ALIASES, "시멘트밀공정": "line", "시멘트밀": "line", "밀": "line",
               "종류": "product", "blaine": "cem_blaine", "분말도": "cem_blaine", "45㎛": "cem_r45", "45um": "cem_r45",
               "so3(xrf)": "cem_so3", "so3": "cem_so3", "loi": "cem_loi", "강열감량": "cem_loi", "mgo": "cem_mgo",
               "석회석비율": "cem_ls", "석회석": "cem_ls", "밀피드": "cem_mill_feed", "밀출구온도": "cem_mill_temp",
               "원료온도": "cem_mill_temp", "cao": "cem_cao", "sio2": "cem_sio2", "al2o3": "cem_al2o3",
               "fe2o3": "cem_fe2o3", "na2o": "cem_na2o", "k2o": "cem_k2o", "cl(xrf)": "cem_cl", "cl": "cem_cl",
               "f-cao(xrf)": "cem_fcao", "f-cao(습식)": "cem_fcao", "fcao": "cem_fcao"},
    "physical": {**_COMMON_ALIASES, "초결시간(분)": "phy_ist", "초결시간": "phy_ist", "초결": "phy_ist",
                 "종결시간(hh:mm)": "phy_fst", "종결시간": "phy_fst", "종결": "phy_fst", "autoclave": "phy_autoclave",
                 "오토클레이브": "phy_autoclave", "압축강도1일(mpa)": "phy_s1", "압축강도1일": "phy_s1", "강도1일": "phy_s1",
                 "압축강도3일(mpa)": "phy_s3", "압축강도3일": "phy_s3", "강도3일": "phy_s3",
                 "압축강도7일(mpa)": "phy_s7", "압축강도7일": "phy_s7", "강도7일": "phy_s7",
                 "압축강도28일(mpa)": "phy_s28", "압축강도28일": "phy_s28", "강도28일": "phy_s28",
                 "6가크롬": "phy_crvi", "6가크롬(cr6)": "phy_crvi", "crvi": "phy_crvi", "담당자": "operator",
                 "표준사lot": "sand_lot", "표준사": "sand_lot"},
    "xrd": {**_COMMON_ALIASES, **_LINE_ALIASES, **_GRADE_ALIASES, "클링커공정": "line", "크링커공정": "line",
            "킬른": "line", "alite": "xrd_alite", "alite(c3s)": "xrd_alite", "c3s": "xrd_alite",
            "belite": "xrd_belite", "belite(c2s)": "xrd_belite", "c2s": "xrd_belite", "c3a": "xrd_c3a",
            "c4af": "xrd_c4af", "fcao": "xrd_fcao", "f-cao": "xrd_fcao", "유리석회": "xrd_fcao",
            "periclase": "xrd_periclase", "주기석": "xrd_periclase", "mgo결정": "xrd_periclase",
            "총크롬": "clk_cr", "총크롬(cr)": "clk_cr", "6가크롬": "clk_crvi", "6가크롬(cr6)": "clk_crvi"},
}
_TS_ALIASES = {k for k, v in _COMMON_ALIASES.items() if v == "timestamp"} | {"timestamp", "일시"}
# 품명(품종) 값 정규화: LIMS '1종시멘트 벌크' 등 → '1종'
PRODUCT_ALIASES = [("고로", "고로슬래그 2종"), ("슬래그", "고로슬래그 2종"), ("1종", "1종"), ("opc", "1종"),
                   ("3종", "3종"), ("조강", "3종"), ("hes", "3종"), ("중용열", "2종"), ("2종", "2종"), ("4종", "4종"),
                   ("5종", "5종"), ("내황산", "5종"), ("플라이", "플라이애시"), ("fly", "플라이애시")]


# LIMS 원본 내보내기 파일 제목(A1 등) → QMS 표. 받은 파일을 그대로 폴더에 넣어도 인식한다.
# 인수검사(원료·석고·고령토)는 현재 QMS 공정 표가 없어 매핑하지 않는다(무시).
LIMS_TITLE_MAP = [("조합원료", "raw_meal"), ("크링커", "clinker"), ("클링커", "clinker"),
                  ("시멘트공정", "cement"), ("시멘트성적", "physical")]
LIMS_SKIP_TITLES = ("인수검사", "고령토", "석고")


def _norm_header(s) -> str:
    """머리글 정규화: NFKC(㎛·아래첨자 변환) · 소문자 · 공백/기호 제거(㎛, um 은 보존)."""
    import re
    import unicodedata

    if s is None or (isinstance(s, float) and np.isnan(s)):     # 빈 칸(NaN)을 'nan' 글자로 세지 않게
        return ""
    t = unicodedata.normalize("NFKC", str(s)).strip().lower().replace("μ", "u").replace("µ", "u")
    return re.sub(r"\s+", "", t)


def normalize_product(v) -> str:
    """품명 문자열을 품종 코드로. 이미 '1종' 등이면 그대로, LIMS '1종시멘트 벌크'면 '1종'."""
    if v is None:
        return ""
    s = _norm_header(v)
    for key, code in PRODUCT_ALIASES:
        if _norm_header(key) in s:
            return code
    return str(v).strip()


def normalize_line(v) -> str:
    """공정구분 값 정규화: '4호기'·'4 k'·'#4' → '4K', '6RM'·'6 R/M' → '6R/M', '2CM' → '2C/M'. 모르면 원문(공백 제거)."""
    import re
    import unicodedata

    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    t = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(v))).upper().lstrip("#")
    if t in ("", "NAN", "NONE", "0"):
        return ""
    m = re.fullmatch(r"(\d+)(?:K|KILN|호기|호|호킬른|킬른)", t)
    if m:
        return f"{int(m.group(1))}K"
    m = re.fullmatch(r"(\d+)(?:R/?M|원료밀)", t)
    if m:
        return f"{int(m.group(1))}R/M"
    m = re.fullmatch(r"(\d+)(?:C/?M|시멘트밀|밀)", t)
    if m:
        return f"{int(m.group(1))}C/M"
    if re.fullmatch(r"\d+", t):                     # 숫자만 → 킬른 호기로 본다
        return f"{int(t)}K"
    return t


def line_sort_key(v: str):
    """4K·5K·6K·7K → 4R/M… → 2C/M… 순(킬른 피드가 먼저)."""
    import re

    m = re.match(r"(\d+)(.*)", v or "")
    order = {"K": 0, "R/M": 1, "C/M": 2}
    return (order.get(m.group(2), 3), int(m.group(1)), v) if m else (9, 0, v or "")


def line_label(v: str) -> str:
    """화면 표시용: 6K → '6K (킬른)', 6R/M → '6R/M (원료밀)', 2C/M → '2C/M (시멘트밀)'."""
    if not v:
        return "구분 없음"
    if v.endswith("R/M"):
        return f"{v} (원료밀)"
    if v.endswith("C/M"):
        return f"{v} (시멘트밀)"
    if v.endswith("K"):
        return f"{v} (킬른)"
    return v


def detect_lims_sheet(raw: pd.DataFrame) -> tuple[str, int] | None:
    """LIMS 원본 내보내기 시트(제목 1행 + 머리글 3행 구조) → (QMS 표, 머리글행 번호). 아니면 None."""
    nrows = min(len(raw), 8)
    ts_aliases = {k for k, v in _COMMON_ALIASES.items() if v == "timestamp"}
    hrow = None
    for r in range(nrows):
        cells = [_norm_header(v) for v in raw.iloc[r].tolist()]
        if sum(bool(c) for c in cells) >= 6 and any(c in ts_aliases for c in cells):
            hrow = r
            break
    if hrow is None:
        return None
    title = " ".join(_norm_header(v) for r in range(hrow) for v in raw.iloc[r].tolist() if _norm_header(v))
    if any(skip in title for skip in (_norm_header(s) for s in LIMS_SKIP_TITLES)):
        return None
    for key, tbl in LIMS_TITLE_MAP:
        if _norm_header(key) in title:
            return tbl, hrow
    return None


@lru_cache(maxsize=None)
def _registry_aliases(name: str) -> dict[str, str]:
    """관리항목 이름(예: '클링커 자유석회(f-CaO)', '원료 투입량(t/h)')도 머리글로 인식 — 업로드 양식은 이 이름을 쓴다."""
    from .standards import _default_items

    out: dict[str, str] = {}
    for it in _default_items():
        if it.table != name or it.prediction or it.key not in RAW_COLUMNS.get(name, []):
            continue
        out[_norm_header(it.name)] = it.key
        if it.unit:
            out[_norm_header(f"{it.name}({it.unit})")] = it.key
    return out


def apply_column_aliases(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """엑셀 머리글(내부 이름 또는 LIMS·한글 이름)을 내부 열 이름으로 바꾼다. 매핑이 겹치면 먼저 나온 열을 쓴다."""
    amap = {**_registry_aliases(name), **COL_ALIASES.get(name, {})}
    valid = set(RAW_COLUMNS.get(name, [])) | {"timestamp", "product"}
    rename, seen = {}, set()
    for col in df.columns:
        if col in valid and col not in seen:                       # 이미 내부 이름
            seen.add(col)
            continue
        h = _norm_header(col)
        key = amap.get(h) or amap.get(re.sub(r"\([^()]*\)$", "", h))   # '용중(g/L)'·'소성대 온도(℃)' → 단위 괄호 빼고 다시
        if key and key not in seen:
            rename[col] = key
            seen.add(key)
    return df.rename(columns=rename) if rename else df


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
               start: datetime | None = None, end: datetime | None = None, line: str | None = None) -> pd.Series:
        """항목의 시계열(timestamp 인덱스, 결측 제거). line(공정구분)을 주면 그 호기·밀만."""
        df = self.table_of(key, registry)
        if df is None or key not in df.columns:              # 빈 결과도 시각 인덱스(기간 비교 시 TypeError 방지)
            return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="timestamp"))
        if product is not None and "product" in df.columns:
            df = df[df["product"] == product]
        if line is not None and "line" in df.columns:        # "" = 공정구분 없는 예전 자료만
            df = df[df["line"].fillna("") == line]
        s = df.set_index("timestamp")[key].astype(float).dropna()
        if start is not None:
            s = s[s.index >= pd.Timestamp(start)]
        if end is not None:
            s = s[s.index <= pd.Timestamp(end)]
        return s.sort_index()

    def lines(self, table: str) -> list[str]:
        """표에 들어 있는 공정구분(호기·밀) 목록 — 4K, 5K … 순. 구분 없는 예전 자료만 있으면 []."""
        df = self.tables.get(table)
        if df is None or "line" not in df.columns or df.empty:
            return []
        return sorted({v for v in df["line"].fillna("").astype(str) if v}, key=line_sort_key)

    def item_lines(self, key: str, registry: SpecRegistry, product: str | None = None) -> list[str]:
        """해당 항목 값이 실제로 있는 공정구분 목록."""
        df = self.table_of(key, registry)
        if df is None or key not in df.columns or "line" not in df.columns:
            return []
        if product is not None and "product" in df.columns:
            df = df[df["product"] == product]
        df = df[df[key].notna()]
        return sorted({v for v in df["line"].fillna("").astype(str) if v}, key=line_sort_key)

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
        for c in RAW_COLUMNS.get(name, []):        # 일부 항목만 들어온 경우(LIMS 연동 등)에도 파생값 계산이 멈추지 않게 빈 열 보충
            if c not in df.columns:
                df[c] = None if c in TEXT_COLUMNS else np.nan
        if name in LINE_TABLES:
            df["line"] = df["line"].map(normalize_line) if len(df) else df["line"]
        df, _ = zero_to_nan(df, name)                 # 예전에 0(미시험)으로 저장된 값도 빈 값으로
        if name == "raw_meal" and len(df):
            df = chem.add_raw_meal_moduli(df)
        if name == "clinker" and len(df):
            df = chem.add_clinker_derived(df)
        if name == "cement" and len(df) and df.get("cem_cao") is not None and df["cem_cao"].notna().any():
            df = chem.add_raw_meal_moduli(df, prefix="cem_")   # 완성시멘트 LSF·SM·IM(참고) — Bogue 는 석고·석회석 영향으로 미산출
        out[name] = df
    return out


def build_store(raw: dict[str, pd.DataFrame]) -> DataStore:
    return DataStore(enrich(raw))


# ── SQLite 입출력 ───────────────────────────────────────────────────────
def merge_rows(old: pd.DataFrame | None, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """같은 키(timestamp[, product])의 행을 열 단위로 병합한다. 새 값이 있는 칸만 덮어쓴다."""
    frames = [f for f in (old, new) if f is not None and len(f)]
    if not frames:
        return new.iloc[0:0]
    both = pd.concat(frames, ignore_index=True)
    # GroupBy.last() 는 열마다 마지막 '비어있지 않은' 값을 취한다(skipna) → 늦게 들어온 일부 항목만 갱신
    merged = both.groupby(keys, as_index=False, sort=False, dropna=False).last()
    return merged.sort_values(keys).reset_index(drop=True)


def save_raw(raw: dict[str, pd.DataFrame], path: Path = DB_PATH, replace: bool = False) -> dict[str, int]:
    """원 데이터를 DB에 저장한다. replace=False 이면 기존 데이터와 열 단위로 병합(upsert)."""
    counts = {}
    with closing(_connect(path)) as con:
        for name, df in raw.items():
            if name not in RAW_COLUMNS:
                continue
            cols = ["timestamp"] + [c for c in RAW_COLUMNS[name] if c in df.columns]
            new = df[cols].copy()
            new["timestamp"] = pd.to_datetime(new["timestamp"])
            old = None
            if not replace:
                try:
                    old = pd.read_sql(f"SELECT * FROM {name}", con, parse_dates=["timestamp"])
                except (pd.errors.DatabaseError, sqlite3.OperationalError):
                    old = None
            keys = ["timestamp"] + (["line"] if name in LINE_TABLES else []) + (["product"] if TABLES[name]["by_product"] else [])
            if name in LINE_TABLES:
                new["line"] = new["line"].map(normalize_line) if "line" in new.columns else ""
                if old is not None and len(old):
                    old["line"] = old["line"].map(normalize_line) if "line" in old.columns else ""
                    # 공정구분 없이 저장됐던 예전 행(같은 시각의 호기끼리 덮어써진 행)은, 같은 시각 자료가 구분과 함께 다시 들어오면 지운다
                    lined = set(new.loc[new["line"] != "", "timestamp"])
                    if lined:
                        old = old[~((old["line"] == "") & old["timestamp"].isin(lined))]
            if TABLES[name]["by_product"] and "product" not in new.columns:
                if len(new):
                    raise ValueError(f"[{SHEET_NAMES[name]}] product(품종) 열이 필요합니다.")
                new["product"] = pd.Series(dtype=object)
            new = merge_rows(old, new, keys)
            new["timestamp"] = pd.to_datetime(new["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
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
    guide.append(["4. 같은 timestamp(+품종)가 이미 있으면 값이 있는 칸만 덮어씁니다(빈 칸은 기존 값 유지)."])
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


CSV_ENCODINGS = ("utf-8-sig", "cp949")   # 한글 Windows 엑셀의 'CSV(쉼표로 분리)' 저장 파일은 CP949


def read_csv_bytes(data: bytes, **kwargs) -> pd.DataFrame:
    """CSV를 UTF-8(BOM 포함) → CP949 순서로 시도해 읽는다(LIMS·엑셀 내보내기 파일 대응). kwargs 는 pd.read_csv 로 전달."""
    for enc in CSV_ENCODINGS[:-1]:
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, **kwargs)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.BytesIO(data), encoding=CSV_ENCODINGS[-1], **kwargs)


def parse_upload(file_bytes: bytes, filename: str = "upload.xlsx", skip_sheets: set[str] | frozenset = frozenset()) -> UploadResult:
    """엑셀(시트=테이블) 또는 CSV(파일명에 테이블명 포함) 업로드를 검증·변환한다. skip_sheets·안내 시트는 읽지 않는다."""
    messages: list[str] = []
    errors: list[str] = []
    tables: dict[str, pd.DataFrame] = {}
    name_by_sheet = {v: k for k, v in SHEET_NAMES.items()} | {k: k for k in SHEET_NAMES} | SHEET_ALIASES

    if filename.lower().endswith(".csv"):
        target = next((t for t in RAW_COLUMNS if t in filename.lower()), None)
        if target is None:
            return UploadResult({}, [], ["CSV 파일명에 테이블명(raw_meal/kiln/clinker/cement/physical/xrd)을 포함하세요."])
        try:
            frames = {target: read_csv_bytes(file_bytes)}
        except Exception as exc:  # noqa: BLE001 - 사용자에게 원인 메시지 표시
            return UploadResult({}, [], [f"CSV 파일을 읽을 수 없습니다: {exc}"])
    else:
        try:
            sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None)
        except Exception as exc:  # noqa: BLE001 - 사용자에게 원인 메시지 표시
            return UploadResult({}, [], [f"엑셀 파일을 읽을 수 없습니다: {exc}"])
        frames = {}
        for s, raw in sheets.items():
            if raw.empty or s in skip_sheets or s in INFO_SHEETS:
                continue
            if s in name_by_sheet:                     # 템플릿 시트(시트명으로 인식) — 머리글은 채취일이 있는 첫 행(위에 제목 행 허용)
                tbl = name_by_sheet[s]
                hrow = next((r for r in range(min(len(raw), 6))
                             if any(_norm_header(v) in _TS_ALIASES for v in raw.iloc[r].tolist())), 0)
            else:                                      # LIMS 원본 파일(제목+머리글 3행으로 인식)
                det = detect_lims_sheet(raw)
                if det is None:
                    continue
                tbl, hrow = det
            df = raw.iloc[hrow + 1:].copy()
            df.columns = [c if c is not None else "" for c in raw.iloc[hrow].tolist()]
            frames.setdefault(tbl, df)                 # 같은 표가 여러 시트면 첫 시트만
        if not frames:
            return UploadResult({}, [], [("인식 가능한 시트가 없습니다. 템플릿 시트명(원료/클링커/시멘트/물성/클링커일일) "
                                          "또는 LIMS 원본 파일(조합원료·크링커·시멘트공정·시멘트성적)을 사용하세요.")])

    for name, df in frames.items():
        df = apply_column_aliases(df.copy(), name)      # LIMS·한글 머리글 → 내부 열 이름
        if "timestamp" not in df.columns:
            errors.append(f"[{SHEET_NAMES[name]}] 채취일(timestamp) 열이 없습니다.")
            continue
        df = _combine_sample_time(df)                    # 채취일 + 채취시간
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", format="mixed")
        df = df[df["timestamp"].notna()]  # 설명 행·빈 행 제거
        if TABLES[name]["by_product"] and "product" not in df.columns:
            errors.append(f"[{SHEET_NAMES[name]}] 품명(product) 열이 필요합니다.")
            continue
        if "product" in df.columns:
            df["product"] = df["product"].map(normalize_product)
        if "line" in df.columns:
            df["line"] = df["line"].map(normalize_line)
        if "grade" in df.columns:
            df["grade"] = df["grade"].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip())
        known = [c for c in RAW_COLUMNS[name] if c in df.columns]
        unknown = [c for c in df.columns if c not in RAW_COLUMNS[name] and c != "timestamp"]
        if unknown:
            messages.append(f"[{SHEET_NAMES[name]}] 인식하지 않은 열은 무시: {', '.join(map(str, unknown))}")
        for c in known:
            if c in TIME_MIN_COLUMNS:                       # 응결시간: 'HH:MM'·시각값도 분으로
                df[c] = df[c].map(_to_minutes)
            if c not in TEXT_COLUMNS:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df, zeros = zero_to_nan(df, name)
        if zeros:
            messages.append(f"[{SHEET_NAMES[name]}] 값 0 = '미시험'으로 보고 빈 칸 처리: "
                            + ", ".join(f"{c} {n}건" for c, n in zeros.items()))
        df = df[["timestamp"] + known]
        if len(df) == 0:
            messages.append(f"[{SHEET_NAMES[name]}] 데이터 행이 없습니다.")
            continue
        tables[name] = df
        messages.append(f"[{SHEET_NAMES[name]}] {len(df)}행 인식 ({df['timestamp'].min():%Y-%m-%d} ~ "
                        f"{df['timestamp'].max():%Y-%m-%d})")
    return UploadResult(tables, messages, errors)
