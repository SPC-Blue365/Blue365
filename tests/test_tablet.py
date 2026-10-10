"""태블릿·휴대폰 열람: 공유 주소·QR 코드, 태블릿 보기(그래프 끌어서 확대 끔), 접속 안내 패널."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from qms import share

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def test_share_address_rules():
    assert not share.is_shared("127.0.0.1") and not share.is_shared("localhost")      # 2_RUN.bat: 이 PC 전용
    assert share.is_shared("0.0.0.0") and share.is_shared("") and share.is_shared(None)
    assert share.share_urls(8501, "127.0.0.1", ips=["10.1.2.3"]) == []
    assert share.share_urls(8501, "0.0.0.0", ips=["10.1.2.3"], hostname="QC-PC") == ["http://10.1.2.3:8501",
                                                                                     "http://QC-PC:8501"]
    assert share.share_urls(8600, "10.9.9.9", ips=["10.1.2.3"]) == ["http://10.9.9.9:8600"]      # 특정 IP로 실행
    assert all(not ip.startswith(("127.", "169.254.")) for ip in share.lan_ipv4())


def test_qr_png_encodes_tablet_url():
    pytest.importorskip("segno")
    png = share.qr_png("http://10.1.2.3:8501" + share.TABLET_QUERY)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 200


def _charts(at):
    return [(json.loads(c.proto.spec).get("layout", {}), json.loads(c.proto.config or "{}")) for c in at.get("plotly_chart")]


def test_tablet_view_from_qr_url_disables_chart_drag(monkeypatch):
    monkeypatch.setattr(share, "lan_ipv4", lambda: ["10.1.2.3"])
    at = AppTest.from_file(APP, default_timeout=240)
    at.query_params["view"] = "tablet"                   # QR 코드 주소로 접속한 경우
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["qms_tablet"] is True
    charts = _charts(at)
    assert charts and all(lay.get("dragmode") is False and cfg.get("displayModeBar") is False for lay, cfg in charts)
    assert [(t.label, t.value) for t in at.sidebar.toggle] == [("📱 태블릿 보기", True)]
    assert "http://10.1.2.3:8501/?view=tablet" in [c.value for c in at.code]       # 접속 안내 패널의 주소


def test_pc_view_keeps_chart_zoom_and_toggle_switches_mode():
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    assert not at.exception and at.session_state["qms_tablet"] is False
    assert all(lay.get("dragmode") is not False for lay, _ in _charts(at))         # PC: 끌어서 확대 유지
    at.sidebar.toggle[0].set_value(True).run()
    assert all(lay.get("dragmode") is False for lay, _ in _charts(at))
