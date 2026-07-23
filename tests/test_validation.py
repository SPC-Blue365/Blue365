"""검증 게이트 단위 테스트.

여기 쓰인 DataFrame 은 '분석 결과'가 아니라 검증 로직의 동작을 확인하기 위한
테스트 픽스처다 (실데이터·분석수치를 지어내는 것이 아님, CLAUDE.md §2 무관).

실행:
    pytest -q          # 또는  python -m pytest tests/
"""

from __future__ import annotations

import pandas as pd

from config.schema import SourceSpec
from src.data.validation import (
    Severity,
    check_value_range,
    check_non_negative,
    check_missing,
    check_duplicates,
    check_process_time_order,
    validate_source,
)


# --- check_value_range ---
def test_value_range_flags_out_of_bounds():
    df = pd.DataFrame({"cao": [44.0, 101.0, -3.0]})
    issue = check_value_range(df, "cao", lo=0, hi=100)
    assert issue is not None and issue.severity is Severity.ERROR
    assert issue.count == 2


def test_value_range_ok_when_in_bounds():
    df = pd.DataFrame({"cao": [44.0, 44.6, 45.1]})
    assert check_value_range(df, "cao", lo=0, hi=100) is None


def test_value_range_none_col_warns():
    df = pd.DataFrame({"cao": [44.0]})
    issue = check_value_range(df, None, lo=0, hi=100)
    assert issue is not None and issue.severity is Severity.WARNING


# --- check_non_negative ---
def test_non_negative_flags_zero_and_negative():
    df = pd.DataFrame({"ton": [10.0, 0.0, -5.0]})
    issue = check_non_negative(df, "ton", allow_zero=False)
    assert issue is not None and issue.severity is Severity.ERROR
    assert issue.count == 2


def test_non_negative_allow_zero():
    df = pd.DataFrame({"ton": [10.0, 0.0, -5.0]})
    issue = check_non_negative(df, "ton", allow_zero=True)
    assert issue is not None and issue.count == 1  # 음수 1개만


# --- check_missing ---
def test_missing_flags_na_in_keys():
    df = pd.DataFrame({"lot": ["A", None], "zone": ["Z1", "Z2"]})
    issue = check_missing(df, ["lot", "zone"])
    assert issue is not None and issue.severity is Severity.ERROR
    assert issue.count == 1


def test_missing_absent_column_is_error():
    df = pd.DataFrame({"lot": ["A", "B"]})
    issue = check_missing(df, ["lot", "zone"])
    assert issue is not None and "없음" in issue.message


# --- check_duplicates ---
def test_duplicates_flagged_as_warning():
    df = pd.DataFrame({"lot": ["A", "A", "B"], "zone": ["Z1", "Z1", "Z2"]})
    issue = check_duplicates(df, ["lot", "zone"])
    assert issue is not None and issue.severity is Severity.WARNING
    assert issue.count == 2


# --- check_process_time_order ---
def test_time_order_detects_reversal():
    merged = pd.DataFrame(
        {
            "t_mine": ["2026-01-01 08:00", "2026-01-02 08:00"],
            "t_osp": ["2026-01-01 10:00", "2026-01-02 07:00"],   # 두번째 행 역전
            "t_yard": ["2026-01-01 12:00", "2026-01-02 09:00"],
        }
    )
    issue = check_process_time_order(merged, "t_mine", "t_osp", "t_yard")
    assert issue is not None and issue.severity is Severity.ERROR
    assert issue.count == 1


# --- validate_source (오케스트레이션) ---
def test_validate_source_with_full_spec_passes_clean_data():
    spec = SourceSpec(
        name="yard",
        filename="yard.xlsx",
        time_col="t",
        cao_col="cao",
        tonnage_col="ton",
        key_cols=["lot"],
    )
    df = pd.DataFrame({"t": ["2026-01-01"], "cao": [44.6], "ton": [100.0], "lot": ["A"]})
    report = validate_source(df, spec)
    assert report.passed
    assert len(report.errors) == 0


def test_validate_source_unset_schema_warns_not_blocks():
    # 스키마 미확정(모든 역할 컬럼 None) → WARNING 만, ERROR 없음 → 통과
    spec = SourceSpec(name="mine")
    df = pd.DataFrame({"a": [1, 2, 3]})
    report = validate_source(df, spec)
    assert report.passed
    assert len(report.warnings) >= 1
