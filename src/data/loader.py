"""엑셀 데이터 로딩 + 구조 파악(EDA 1단계) [Data-Analyst].

두 가지 용도:
  1) inspect_excel / inspect_raw_dir — 스키마를 모르는 상태에서 파일 구조(시트·컬럼·
     dtype·샘플)를 '파악'한다. Data-Analyst가 data_schema.md 를 채우기 위한 정찰용.
  2) load_source / load_all_sources — 스키마(config.schema)가 확정된 뒤 실제 데이터를 읽는다.

⚠️ 컬럼명을 하드코딩하지 않는다. 실제 컬럼은 config.schema 의 SourceSpec 을 통해 참조한다
   (CLAUDE.md §2, §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from config.paths import RAW_DIR
from config.schema import SourceSpec, ALL_SOURCES


# --------------------------------------------------------------------------- #
# 1) 구조 파악 (스키마 미확정 단계)
# --------------------------------------------------------------------------- #
@dataclass
class ExcelInspection:
    """엑셀 한 파일의 구조 정찰 결과."""

    path: Path
    sheets: dict[str, "SheetInspection"] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"📄 {self.path.name}  (시트 {len(self.sheets)}개)"]
        for name, s in self.sheets.items():
            lines.append(f"  └ [{name}] {s.n_rows}행 × {s.n_cols}열")
            lines.append(f"      컬럼: {', '.join(map(str, s.columns))}")
        return "\n".join(lines)


@dataclass
class SheetInspection:
    """엑셀 한 시트의 구조."""

    name: str
    n_rows: int
    n_cols: int
    columns: list = field(default_factory=list)
    dtypes: dict = field(default_factory=dict)
    na_counts: dict = field(default_factory=dict)
    head: Optional[pd.DataFrame] = None


def inspect_excel(path: Union[str, Path], n_head: int = 5) -> ExcelInspection:
    """엑셀 파일의 모든 시트 구조를 파악한다 (스키마 확정 전 정찰용).

    실제 데이터 값은 지어내지 않으며, 파일에 실재하는 컬럼/타입/결측/샘플만 보고한다.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    xls = pd.ExcelFile(path)
    inspection = ExcelInspection(path=path)
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        inspection.sheets[sheet] = SheetInspection(
            name=sheet,
            n_rows=len(df),
            n_cols=df.shape[1],
            columns=list(df.columns),
            dtypes={c: str(t) for c, t in df.dtypes.items()},
            na_counts={c: int(df[c].isna().sum()) for c in df.columns},
            head=df.head(n_head),
        )
    return inspection


def inspect_raw_dir(raw_dir: Union[str, Path] = RAW_DIR) -> list[ExcelInspection]:
    """data/raw/ 내 모든 엑셀 파일을 파악한다. 업로드 직후 첫 실행용."""
    raw_dir = Path(raw_dir)
    files = sorted(
        [p for p in raw_dir.glob("*") if p.suffix.lower() in (".xlsx", ".xls", ".xlsm")]
    )
    if not files:
        raise FileNotFoundError(
            f"{raw_dir} 에 엑셀 파일이 없습니다. 광산/OSP/야드 데이터를 업로드해 주세요."
        )
    return [inspect_excel(p) for p in files]


# --------------------------------------------------------------------------- #
# 2) 실제 로딩 (스키마 확정 후)
# --------------------------------------------------------------------------- #
def load_source(spec: SourceSpec, raw_dir: Union[str, Path] = RAW_DIR) -> pd.DataFrame:
    """SourceSpec 에 따라 한 공정 데이터를 로드한다.

    스키마가 아직 확정되지 않았으면(파일명 미설정) 지어내지 않고 명확한 에러를 던진다.
    """
    if not spec.filename:
        raise ValueError(
            f"[{spec.name}] 파일명이 아직 설정되지 않았습니다. "
            f"inspect_raw_dir()로 구조를 파악하고 config/schema.py 의 "
            f"{spec.name.upper()} 스펙을 채운 뒤 다시 호출하세요. "
            f"미확정 항목: {spec.missing_fields()}"
        )
    path = Path(raw_dir) / spec.filename
    if not path.exists():
        raise FileNotFoundError(f"[{spec.name}] 파일이 없습니다: {path}")

    df = pd.read_excel(path, sheet_name=spec.sheet or 0)

    # 시각 컬럼이 지정되어 있으면 datetime 으로 파싱 (Time-Lag 계산 대비)
    if spec.time_col and spec.time_col in df.columns:
        df[spec.time_col] = pd.to_datetime(df[spec.time_col], errors="coerce")
    return df


def load_all_sources(
    specs: list[SourceSpec] = ALL_SOURCES, raw_dir: Union[str, Path] = RAW_DIR
) -> dict[str, pd.DataFrame]:
    """확정된 모든 공정 스펙을 로드해 {name: DataFrame} 으로 반환한다."""
    return {spec.name: load_source(spec, raw_dir) for spec in specs}
