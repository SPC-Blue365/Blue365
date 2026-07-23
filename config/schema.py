"""공정별 데이터 스키마 스펙 (Source Spec).

⚠️ 중요 (CLAUDE.md §2 가상데이터 금지):
    실제 컬럼명·파일명은 아직 확정되지 않았다. 아래 값은 모두 `None` 플레이스홀더이며,
    데이터 업로드 후 EDA(loader.inspect_excel)로 실제 구조를 파악한 뒤
    이 파일과 docs/data_schema.md 를 함께 채운다. 추측으로 채우지 말 것.

각 공정 데이터의 '역할 컬럼'을 이름으로 매핑해 두면, loader/validation/matching 코드가
컬럼명을 하드코딩하지 않고 스펙만 보고 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceSpec:
    """한 공정(광산/OSP/야드) 데이터의 구조 스펙."""

    name: str                                   # 공정 이름 (mine/osp/yard)
    filename: Optional[str] = None              # data/raw/ 내 파일명 (예: "mine_xrf.xlsx")
    sheet: Optional[str] = None                 # 엑셀 시트명 (None이면 첫 시트)

    # --- 역할 컬럼 (EDA 후 실제 컬럼명으로 채움) ---
    time_col: Optional[str] = None              # 공정 시각/일자 (Time-Lag 계산 기준)
    cao_col: Optional[str] = None               # CaO 품위(%) 컬럼
    tonnage_col: Optional[str] = None           # 물량(Ton) 컬럼
    key_cols: list[str] = field(default_factory=list)  # Join Key 후보 (로트/차량/구역코드 등)

    def is_ready(self) -> bool:
        """매칭에 필요한 최소 정보(파일명 + 시각 + 최소 1개 Key)가 채워졌는지."""
        return bool(self.filename and self.time_col and self.key_cols)

    def missing_fields(self) -> list[str]:
        """아직 확정되지 않은(=None/빈) 필수 항목 목록. 사용자 질문용."""
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


# === 3개 공정 스펙 (모두 미확정 상태) ===
# TODO(schema): 데이터 업로드 후 아래 None/[] 값을 실제 컬럼명으로 채우고
#               docs/data_schema.md 와 동기화할 것.

MINE = SourceSpec(name="mine")   # 광산: 시추코어 XRF, 감마레이
OSP = SourceSpec(name="osp")     # OSP: 품위별 적재 위치·물량
YARD = SourceSpec(name="yard")   # 야드: CNA 실시간 분석기

ALL_SOURCES: list[SourceSpec] = [MINE, OSP, YARD]


# === 최종 품질 목표 (CLAUDE.md §1) ===
@dataclass(frozen=True)
class Target:
    cao_mean: float = 44.6      # 목표 평균 CaO 품위 (%)
    cao_std_max: float = 0.5    # 허용 표준편차 상한
    tol: float = 0.5            # 목표 허용 오차 (±)

    @property
    def lower(self) -> float:
        return self.cao_mean - self.tol

    @property
    def upper(self) -> float:
        return self.cao_mean + self.tol


TARGET = Target()
