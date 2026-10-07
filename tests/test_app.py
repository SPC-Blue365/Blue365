"""Streamlit 화면 스모크 테스트: 모든 화면이 예외 없이 렌더링되는지 확인."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
PAGES = ["overview", "monitor", "spc", "alerts", "diagnosis", "prediction", "calculator", "reports", "data", "settings"]


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()  # 첫 실행 시 임시 데이터 폴더에 데모 데이터 자동 생성
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(app, page):
    app.switch_page(f"app_pages/{page}.py")
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.title, "페이지 제목이 없습니다"
