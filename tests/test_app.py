"""Streamlit 화면 스모크 테스트: 모든 화면이 예외 없이 렌더링되는지 확인."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
PAGES = ["overview", "monitor", "spc", "alerts", "diagnosis", "prediction", "rawmix", "chromium", "calculator", "reports",
         "data", "lims", "settings"]


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


def test_tilde_ranges_are_escaped_in_markdown(app):
    """'20~120, 10~40' 같은 범위 표기가 마크다운 취소선으로 바뀌지 않도록 자동 이스케이프되는지 확인."""
    app.switch_page("app_pages/chromium.py")
    app.run()
    texts = [c.value for c in app.caption]
    hit = [t for t in texts if "셰일 20" in t]
    assert hit and "20\\~120" in hit[0]


def test_access_password_gate(monkeypatch):
    """공유 실행용 접속 비밀번호: 설정 시 로그인 전에는 화면 내용이 보이지 않는다."""
    monkeypatch.setenv("QMS_ACCESS_PASSWORD", "blue365!")
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["접속 비밀번호"]
    at.text_input[0].input("wrong")
    at.button[0].click()
    at.run()
    assert at.error and "맞지 않습니다" in at.error[0].value
    at.text_input[0].input("blue365!")
    at.button[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["_qms_access_ok"] and "접속 비밀번호" not in [t.label for t in at.text_input]
    assert at.title and at.title[0].value != "🏭 Blue365 QMS"
