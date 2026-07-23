"""공정별 데이터 스키마 스펙 & 확정 규칙 (Source Spec).

data_v1.xlsx 기준. EDA + 사용자 확인으로 확정된 값 (docs/data_schema.md 와 동기화).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# === 시트명 상수 ===
SHEET_MINE_49Q = "광산(49Q)_XRF"
SHEET_MINE_47Q = "광산(47Q)_감마레이"
SHEET_MINE_45Q = "45Q 감마레이 data"
SHEET_OSP_OLD = "OSP인출_기존"       # 기존 라인
SHEET_OSP_NEW = "OSP인출_신설"       # 신설 라인
SHEET_YARD_CNA = "CNA data"          # ⭐️ 최종 목표 기준 (야드 실시간 분석기)

# === 라인 구분 (공정구분) ===
LINE_OLD = "기존"
LINE_NEW = "신설"
LINE_IDLE = "운휴"

# === OSP 인출 P/W 컬럼 (라인별 사용 분리) ===
PW_COLS_OLD = [" P/W1호", " P/W2호"]   # 기존 라인이 사용
PW_COLS_NEW = [" P/W3호", " P/W4호"]   # 신설 라인이 사용
PW_COLS_ALL = [" P/W1호", " P/W2호", " P/W3호", " P/W4호"]

# === 확정 규칙 ===
# 인출량(총톤)은 한 회차에 적힌 구역 수로 '균등 배분'한다. (사용자 확인)
WITHDRAWAL_SPLIT = "equal"

# 복합 구역코드(예: "50/55", "55-45", "100-0", "15~35") 분리 구분자
ZONE_DELIMITERS = r"[/\-~]"


@dataclass
class SourceSpec:
    """검증 게이트용 역할 컬럼 매핑 (src/data/validation.py 에서 사용)."""

    name: str
    filename: Optional[str] = None
    sheet: Optional[str] = None
    time_col: Optional[str] = None
    cao_col: Optional[str] = None
    tonnage_col: Optional[str] = None
    key_cols: list[str] = field(default_factory=list)

    def is_ready(self) -> bool:
        return bool(self.filename and self.time_col and self.key_cols)

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.filename:
            missing.append("filename")
        if not self.time_col:
            missing.append("time_col")
        if not self.cao_col:
            missing.append("cao_col")
        if not self.key_cols:
            missing.append("key_cols")
        return missing


# 데이터파일 (로컬 전용)
DATA_FILE = "data_v1.xlsx"

# 검증용 스펙 (원시 시트 기준 역할 컬럼)
MINE = SourceSpec(
    name="mine_49Q", filename=DATA_FILE, sheet=SHEET_MINE_49Q,
    time_col="채굴일자", cao_col="CaO품위", tonnage_col="이송물량(톤)",
    key_cols=["채굴일자", "공정구분", "OSP적재구역"],
)
OSP = SourceSpec(
    name="osp_old", filename=DATA_FILE, sheet=SHEET_OSP_OLD,
    time_col="일자", cao_col=None, tonnage_col="인출량",
    key_cols=["일자", "인출시간"],
)
YARD = SourceSpec(
    name="yard_cna", filename=DATA_FILE, sheet=SHEET_YARD_CNA,
    time_col="일자", cao_col="CaO", tonnage_col="적재물량(TPH)",
    key_cols=["일자", "시간"],
)

ALL_SOURCES: list[SourceSpec] = [MINE, OSP, YARD]


# === 최종 품질 목표 (CLAUDE.md §1) ===
@dataclass(frozen=True)
class Target:
    cao_mean: float = 44.6
    cao_std_max: float = 0.5
    tol: float = 0.5

    @property
    def lower(self) -> float:
        return self.cao_mean - self.tol

    @property
    def upper(self) -> float:
        return self.cao_mean + self.tol


TARGET = Target()
