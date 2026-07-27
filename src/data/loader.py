"""엑셀 구조 정찰 (EDA 1단계) [Data-Analyst].

inspect_excel / inspect_raw_dir — 스키마를 모르는 새 데이터의 구조(시트·컬럼·dtype·결측·샘플)를
'파악'한다. 값을 지어내지 않고 파일에 실재하는 것만 보고한다 (CLAUDE.md §2).
실제 로딩·정제는 src/data/clean.py + src/models/dataset.py 가 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from config.paths import RAW_DIR


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
