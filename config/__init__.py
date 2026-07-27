"""프로젝트 설정 패키지 (경로 · 스키마 스펙)."""

from config.paths import (
    PROJECT_ROOT,
    DATA_DIR,
    RAW_DIR,
    INTERIM_DIR,
    PROCESSED_DIR,
    EXTERNAL_DIR,
    OUTPUTS_DIR,
    FIGURES_DIR,
    PREDICTIONS_DIR,
    MODELS_DIR,
)
from config.schema import (
    SourceSpec,
    SPEC_MINE,
    SPEC_OSP,
    SPEC_YARD,
    SPEC_YARDCHANGE,
    TARGET,
    YARD_PAIR,
)

__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "RAW_DIR",
    "INTERIM_DIR",
    "PROCESSED_DIR",
    "EXTERNAL_DIR",
    "OUTPUTS_DIR",
    "FIGURES_DIR",
    "PREDICTIONS_DIR",
    "MODELS_DIR",
    "SourceSpec",
    "SPEC_MINE",
    "SPEC_OSP",
    "SPEC_YARD",
    "SPEC_YARDCHANGE",
    "TARGET",
    "YARD_PAIR",
]
