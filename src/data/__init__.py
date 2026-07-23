"""데이터 로딩 · 검증 모듈 [Data-Analyst]."""

from src.data.loader import (
    inspect_excel,
    inspect_raw_dir,
    load_source,
    load_all_sources,
    ExcelInspection,
)
from src.data.validation import (
    Severity,
    Issue,
    ValidationReport,
    validate_source,
    check_value_range,
    check_non_negative,
    check_missing,
    check_duplicates,
    check_process_time_order,
)

__all__ = [
    "inspect_excel",
    "inspect_raw_dir",
    "load_source",
    "load_all_sources",
    "ExcelInspection",
    "Severity",
    "Issue",
    "ValidationReport",
    "validate_source",
    "check_value_range",
    "check_non_negative",
    "check_missing",
    "check_duplicates",
    "check_process_time_order",
]
