"""조회 전용 HTML 현황판: 데이터만으로(Streamlit 없이) 단일 파일 생성·오프라인 그래프 포함·기록본 보관."""


import pandas as pd

from qms import shipment as S
from qms import snapshot as SN


def test_snapshot_builds_offline_html(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SHIP_DB_PATH", tmp_path / "ship.db")
    html = SN.build_snapshot()                      # 데모 데이터(conftest 의 데이터 폴더) 기준
    assert html.startswith("<!doctype html>") and 'translate="no"' in html
    assert "품질 현황판" in html and "기준 시각" in html and "핵심 공정 지표" in html
    assert "Plotly" in html and "cdn.plot.ly" not in html.split("<script")[0]   # 그래프 라이브러리 내장
    assert html.count("plotly.js v") <= 2                                        # 라이브러리는 한 번만 내장
    assert "fitPlots" in html
    paths = SN.write_snapshot(tmp_path / "out", keep=2)
    assert paths[0].name == SN.LATEST_NAME and paths[0].exists() and paths[1].parent.name == SN.ARCHIVE_DIR
    for d in ("20200101", "20200102", "20200103"):                               # 오래된 기록본은 keep 개만
        (tmp_path / "out" / SN.ARCHIVE_DIR / f"Blue365_현황_{d}.html").write_text("x", encoding="utf-8")
    SN.write_snapshot(tmp_path / "out", keep=2)
    assert len(list((tmp_path / "out" / SN.ARCHIVE_DIR).glob("*.html"))) == 2


def test_shipment_ks_limits_are_per_product(tmp_path, monkeypatch):
    """출하시멘트 KS 참고값: 3종은 SO₃ 4.5%·28일 47.5MPa, 고로슬래그 2종은 KS 미설정(1종 값으로 오판정 금지)."""
    assert S.ks_default("so3", "1종") == {"ks_min": None, "ks_max": 3.5}
    assert S.ks_default("so3", "3종") == {"ks_min": None, "ks_max": 4.5}
    assert S.ks_default("s28", "3종")["ks_min"] == 47.5 and S.ks_default("mgo", "3종")["ks_max"] == 5.0
    assert S.ks_default("so3", S.SLAG2) == {"ks_min": None, "ks_max": None}
    monkeypatch.setattr(S, "SHIP_STANDARDS_PATH", tmp_path / "std.json")
    std = {"years": {"2026": {"so3": {"ks_max": 3.5, "usl": 3.0}}}}                # 예전 저장본 = 1종
    assert S.effective_limits(std, "so3", 2026, "1종")["usl"] == 3.0
    assert S.effective_limits(std, "so3", 2026, "3종")["usl"] is None             # 1종 사내기준이 3종에 적용되지 않음
    df = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-02"]), "product": ["1종", "3종"],
                       "so3": [3.6, 3.6]})
    lim = S.limits_frame(std, df, "so3")
    assert list(lim["ks_max"]) == [3.5, 4.5]
    S.save_year(std, 2026, S.year_table(std, 2026, "3종").assign(**{"사내 상한": 4.0}), "3종")
    assert std["years@3종"]["2026"]["so3"]["usl"] == 4.0 and std["years"]["2026"]["so3"]["usl"] == 3.0


def test_monitor_snapshot_option(tmp_path):
    import contextlib
    import io

    import qms_monitor
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        qms_monitor.main(["--snapshot", str(tmp_path / "snap"), "--dry-run"])
    assert (tmp_path / "snap" / SN.LATEST_NAME).exists() and "[현황판] 저장" in buf.getvalue()
