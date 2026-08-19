"""검증 게이트 (Validation Gate) [Data-Analyst / Matching-Agent].

CLAUDE.md §3 Matching-Agent 규칙 구현:
    조인 '전에' 기본 무결성을 검사한다 — CaO 범위(0~100%), 음수/0 물량,
    시간 역전(야드 < 광산), 식별자 중복·결측. 이상은 조용히 넘기지 않고 보고한다.

설계 원칙:
  - 컬럼명을 하드코딩하지 않는다. SourceSpec 이 지정한 역할 컬럼만 검사한다.
  - 값을 지어내거나 이상치를 임의 삭제하지 않는다. '발견하고 보고'만 한다.
  - 스펙의 역할 컬럼이 아직 미설정(None)이면 그 검사는 건너뛰되 WARNING 으로 알린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd

from config.schema import SourceSpec


class Severity(str, Enum):
    ERROR = "ERROR"      # 매칭 진행 불가 — 반드시 사용자에게 보고 후 조치
    WARNING = "WARNING"  # 주의 — 확인 필요하나 즉시 차단은 아님


@dataclass
class Issue:
    """검증에서 발견된 단일 이슈."""

    check: str
    severity: Severity
    message: str
    count: int = 0                      # 해당 이슈 행 수
    sample_index: list = field(default_factory=list)  # 예시 행 인덱스 (최대 5개)

    def __str__(self) -> str:
        loc = f" (행 {self.count}개)" if self.count else ""
        return f"[{self.severity.value}] {self.check}: {self.message}{loc}"


@dataclass
class ValidationReport:
    """한 데이터 소스에 대한 검증 결과 모음."""

    source: str
    n_rows: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def passed(self) -> bool:
        """ERROR 가 하나도 없으면 통과."""
        return len(self.errors) == 0

    def add(self, issue: Optional[Issue]) -> None:
        if issue is not None:
            self.issues.append(issue)

    def summary(self) -> str:
        status = "✅ 통과" if self.passed else "❌ 차단"
        head = (
            f"[검증] {self.source}: {status}  "
            f"(행 {self.n_rows} · ERROR {len(self.errors)} · WARNING {len(self.warnings)})"
        )
        if not self.issues:
            return head + "\n  이상 없음."
        return head + "\n" + "\n".join(f"  - {i}" for i in self.issues)


# --------------------------------------------------------------------------- #
# 개별 검사 함수 (모두 Issue 또는 None 반환)
# --------------------------------------------------------------------------- #
def _sample_idx(mask: pd.Series, k: int = 5) -> list:
    return list(mask[mask].index[:k])


def check_value_range(
    df: pd.DataFrame,
    col: Optional[str],
    lo: float,
    hi: float,
    severity: Severity = Severity.ERROR,
) -> Optional[Issue]:
    """수치 컬럼이 [lo, hi] 범위를 벗어나는 행을 검출 (예: CaO 0~100%)."""
    if col is None:
        return Issue("value_range", Severity.WARNING, "검사 대상 컬럼 미설정(스키마 확정 필요)")
    if col not in df.columns:
        return Issue("value_range", Severity.ERROR, f"컬럼 '{col}' 이(가) 데이터에 없음")
    vals = pd.to_numeric(df[col], errors="coerce")
    mask = (vals < lo) | (vals > hi)
    if mask.any():
        return Issue(
            "value_range",
            severity,
            f"'{col}' 값이 허용범위 [{lo}, {hi}] 를 벗어남",
            count=int(mask.sum()),
            sample_index=_sample_idx(mask),
        )
    return None


def check_non_negative(
    df: pd.DataFrame, col: Optional[str], allow_zero: bool = False
) -> Optional[Issue]:
    """물량 등 음수(선택적으로 0)면 안 되는 컬럼 검사."""
    if col is None:
        return Issue("non_negative", Severity.WARNING, "검사 대상 컬럼 미설정(스키마 확정 필요)")
    if col not in df.columns:
        return Issue("non_negative", Severity.ERROR, f"컬럼 '{col}' 이(가) 데이터에 없음")
    vals = pd.to_numeric(df[col], errors="coerce")
    mask = vals < 0 if allow_zero else vals <= 0
    if mask.any():
        bound = "음수" if allow_zero else "0 이하"
        return Issue(
            "non_negative",
            Severity.ERROR,
            f"'{col}' 에 {bound} 값 존재",
            count=int(mask.sum()),
            sample_index=_sample_idx(mask),
        )
    return None


def check_missing(df: pd.DataFrame, cols: list[str]) -> Optional[Issue]:
    """필수 컬럼(주로 Join Key)의 결측 검사."""
    cols = [c for c in cols if c]
    if not cols:
        return Issue("missing", Severity.WARNING, "필수 컬럼 미설정(스키마 확정 필요)")
    absent = [c for c in cols if c not in df.columns]
    if absent:
        return Issue("missing", Severity.ERROR, f"필수 컬럼 없음: {absent}")
    mask = df[cols].isna().any(axis=1)
    if mask.any():
        return Issue(
            "missing",
            Severity.ERROR,
            f"필수 컬럼 {cols} 에 결측 존재",
            count=int(mask.sum()),
            sample_index=_sample_idx(mask),
        )
    return None


def check_duplicates(df: pd.DataFrame, key_cols: list[str]) -> Optional[Issue]:
    """Join Key 조합의 중복 검사 (중복 시 조인에서 행 폭증 위험)."""
    key_cols = [c for c in key_cols if c]
    if not key_cols:
        return Issue("duplicates", Severity.WARNING, "Join Key 미설정(스키마 확정 필요)")
    absent = [c for c in key_cols if c not in df.columns]
    if absent:
        return Issue("duplicates", Severity.ERROR, f"Key 컬럼 없음: {absent}")
    mask = df.duplicated(subset=key_cols, keep=False)
    if mask.any():
        return Issue(
            "duplicates",
            Severity.WARNING,
            f"Key {key_cols} 조합 중복 존재 (조인 전 확인 필요)",
            count=int(mask.sum()),
            sample_index=_sample_idx(mask),
        )
    return None


def check_process_time_order(
    merged: pd.DataFrame,
    mine_time: str,
    osp_time: str,
    yard_time: str,
) -> Optional[Issue]:
    """공정 시간 순서 검증: 광산 ≤ OSP ≤ 야드 여야 한다 (시간 역전 검출).

    매칭(조인)으로 세 공정 시각이 한 행에 모인 통합 데이터에 적용한다.
    """
    for c in (mine_time, osp_time, yard_time):
        if c not in merged.columns:
            return Issue("time_order", Severity.ERROR, f"시각 컬럼 '{c}' 이(가) 통합데이터에 없음")
    t_mine = pd.to_datetime(merged[mine_time], errors="coerce")
    t_osp = pd.to_datetime(merged[osp_time], errors="coerce")
    t_yard = pd.to_datetime(merged[yard_time], errors="coerce")
    mask = (t_osp < t_mine) | (t_yard < t_osp)
    if mask.any():
        return Issue(
            "time_order",
            Severity.ERROR,
            "공정 시간 역전 발견 (광산 ≤ OSP ≤ 야드 위반) — Time-Lag/매칭 재확인 필요",
            count=int(mask.sum()),
            sample_index=_sample_idx(mask),
        )
    return None


# --------------------------------------------------------------------------- #
# 게이트 오케스트레이션
# --------------------------------------------------------------------------- #
def validate_source(df: pd.DataFrame, spec: SourceSpec) -> ValidationReport:
    """한 공정 소스에 대해 스펙 기반으로 적용 가능한 검사를 모두 수행한다.

    스펙의 역할 컬럼이 아직 미설정이면 해당 검사는 WARNING 으로 남고 통과를 막지 않는다.
    (스키마 확정 후 다시 실행하면 실제 무결성 검사가 작동한다.)
    """
    report = ValidationReport(source=spec.name, n_rows=len(df))
    # CaO 품위 0~100% (해당 컬럼이 있는 소스만)
    if spec.cao_col:
        report.add(check_value_range(df, spec.cao_col, lo=0.0, hi=100.0))
    # 물량 음수(스펙에 따라 0 허용) 검사
    if spec.tonnage_col:
        report.add(check_non_negative(df, spec.tonnage_col,
                                      allow_zero=getattr(spec, "allow_zero_tonnage", False)))
    # Join Key 결측
    report.add(check_missing(df, spec.key_cols))
    # Join Key 중복 (유일성이 기대되는 소스만)
    if getattr(spec, "expect_unique", True):
        report.add(check_duplicates(df, spec.key_cols))
    return report


# --------------------------------------------------------------------------- #
# 파이프라인 검증 게이트 (매칭 전 실행) — CLAUDE.md §3
# --------------------------------------------------------------------------- #
def validate_pipeline(mine, osp, yards: dict, yard_change=None) -> dict[str, ValidationReport]:
    """정제 완료된 프레임들을 매칭 전에 일괄 검증한다.

    반환: {소스명: ValidationReport}. 이상은 조용히 넘기지 않고 호출측에서 보고한다.
    """
    from config import schema as S

    reports: dict[str, ValidationReport] = {}
    if mine is not None:
        rep = validate_source(mine, S.SPEC_MINE)
        # ⭐️ 라인 라벨 점검 — 알 수 없는 라벨은 라인별 집계에서 통째로 빠지므로
        #    조용히 넘기지 않고 물량과 함께 보고한다(2026-08-05 실제로 21,065톤이 빠져 있었다).
        if "line" in mine:
            unknown = mine[~mine["line"].isin([S.LINE_OLD, S.LINE_NEW])]
            if len(unknown):
                ton = float(pd.to_numeric(unknown.get("tonnage"), errors="coerce").sum())
                rep.issues.append(Issue(
                    "line_unknown", Severity.ERROR,
                    f"알 수 없는 라인 라벨 {sorted(set(unknown['line']))[:5]} — "
                    f"{ton:,.0f}톤이 라인별 집계에서 제외됩니다", len(unknown)))
        reports["광산"] = rep
    if osp is not None:
        rep_o = validate_source(osp, S.SPEC_OSP)
        # ⭐️ 시각 미상 물량 — 엑셀에 날짜 없는 시각 셀은 1900년 epoch 로 읽혀 그날 00:00 이 된다.
        #    자정에 몰린 가짜 물량이 Time-Lag 추정을 뒤집으므로(신설 2h ↔ 11h) 반드시 표시한다.
        if "time_known" in osp:
            unk = osp[~osp["time_known"].fillna(True)]
            if len(unk):
                ton = float(pd.to_numeric(unk.get("withdrawn_ton"), errors="coerce").sum())
                tot = float(pd.to_numeric(osp.get("withdrawn_ton"), errors="coerce").sum())
                rep_o.issues.append(Issue(
                    "time_unknown", Severity.WARNING,
                    f"인출시각을 알 수 없는 행 — {ton:,.0f}톤"
                    f"({ton / tot * 100:.1f}%)이 그날 00:00 으로 들어갑니다. "
                    "물량 수지에는 쓰되 시간축 분석에서는 제외됩니다", len(unk)))
        reports["OSP인출"] = rep_o
    for line, ydf in (yards or {}).items():
        reports[f"야드({line})"] = validate_source(ydf, S.SPEC_YARD)
    if yard_change is not None and len(yard_change):
        reports["야드변경"] = validate_source(yard_change, S.SPEC_YARDCHANGE)
    return reports


def summarize_reports(reports: dict[str, ValidationReport]) -> str:
    """여러 리포트를 한 화면 요약으로. ERROR가 있으면 상단에 표시."""
    if not reports:
        return "[검증] 대상 없음"
    n_err = sum(len(r.errors) for r in reports.values())
    n_warn = sum(len(r.warnings) for r in reports.values())
    head = ("✅ 검증 통과" if n_err == 0 else f"❌ 검증 ERROR {n_err}건")
    lines = [f"[검증 게이트] {head} (WARNING {n_warn}건)"]
    for name, rep in reports.items():
        mark = "✅" if rep.passed else "❌"
        lines.append(f"  {mark} {name}: {rep.n_rows}행 · ERROR {len(rep.errors)} · WARNING {len(rep.warnings)}")
        for issue in rep.issues:
            lines.append(f"      - {issue}")
    return "\n".join(lines)
