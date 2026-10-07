"""테스트 공통 설정: 임시 데이터 폴더 + 데모 데이터 픽스처."""

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

# qms 모듈을 불러오기 전에 데이터 폴더를 임시 폴더로 돌린다(실제 data/ 보호).
_TMP = tempfile.mkdtemp(prefix="qms_test_")
os.environ["QMS_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from qms.alerts import detect_events  # noqa: E402
from qms.demo import generate_demo_data  # noqa: E402
from qms.prediction import attach_predictions  # noqa: E402
from qms.standards import DEFAULT_SETTINGS, SpecRegistry  # noqa: E402
from qms.store import build_store  # noqa: E402

END = date(2026, 10, 7)


@pytest.fixture(scope="session")
def demo_raw():
    return generate_demo_data(end=END, days=120, seed=7)


@pytest.fixture(scope="session")
def demo(demo_raw):
    """(store, registry, settings, models, events) — 세션 공유(읽기 전용으로 사용)."""
    store = build_store(demo_raw)
    reg = SpecRegistry()
    settings = dict(DEFAULT_SETTINGS)
    models = attach_predictions(store, reg)
    events = detect_events(store, reg, settings)
    return store, reg, settings, models, events


@pytest.fixture()
def tmp_data_dir(tmp_path):
    return tmp_path
