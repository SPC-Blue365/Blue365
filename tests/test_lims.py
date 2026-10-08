import math
from datetime import datetime

import pandas as pd
import pytest

from qms import lims
from qms.store import load_raw, save_raw

NOW = datetime(2026, 10, 8, 1, 0)


@pytest.fixture()
def demo_lims(demo_raw, tmp_path, monkeypatch):
    src = tmp_path / "src.db"
    save_raw(demo_raw, path=src, replace=True)
    path = tmp_path / "lims_demo.db"
    lims.create_demo_lims(load_raw(src), path)
    monkeypatch.setattr(lims, "LIMS_DEMO_DB", path)
    monkeypatch.setattr(lims, "LIMS_CONFIG_PATH", tmp_path / "lims.json")
    return tmp_path


def test_parse_value_variants():
    assert lims.parse_value("<0.1") == (0.1, True)
    assert lims.parse_value("1,234") == (1234.0, False)
    assert lims.parse_value("12,5") == (12.5, False)
    assert lims.parse_value(3) == (3.0, False)
    v, c = lims.parse_value("N.D.")
    assert math.isnan(v) and not c


def test_demo_sync_into_empty_db_reproduces_values(demo_lims, demo_raw):
    cfg = lims.LimsConfig(enabled=True, mode="demo")
    db = demo_lims / "qms.db"
    rep = lims.sync(cfg, db_path=db, now=NOW, log_path=demo_lims / "log.jsonl")
    assert not rep.errors, rep.errors
    assert rep.saved and rep.n_status_skipped > 0                       # 미승인(PENDING) 제외
    assert ("CEMENT_LOT", "WATER_DEMAND") in {(sp, tc) for sp, tc, _ in rep.unmapped}
    got = load_raw(db)
    a = got["clinker"].set_index("timestamp")["clk_fcao"]
    b = demo_raw["clinker"].set_index("timestamp")["clk_fcao"]
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    assert len(j) > 50 and (j.iloc[:, 0] - j.iloc[:, 1]).abs().max() < 1e-6
    assert set(got["physical"]["product"]) <= {"1종", "3종"}           # 품종 코드 변환(OPC/HES)
    assert cfg.watermark == rep.watermark_after                         # 워터마크 갱신·저장
    rep2 = lims.sync(cfg, db_path=db, now=NOW, log_path=demo_lims / "log.jsonl")
    assert rep2.n_fetched == 0                                          # 증분: 새 결과 없음


def test_late_results_fill_existing_rows(demo_lims, tmp_path):
    db = tmp_path / "late.db"
    base = pd.DataFrame({"timestamp": [pd.Timestamp("2026-10-01 12:00")], "product": ["1종"], "phy_s3": [29.0],
                         "sand_lot": ["ISO-1"]})
    save_raw({"physical": base}, path=db, replace=True)
    late = pd.DataFrame([{"sampled_at": "2026-10-01 12:00", "sample_point": "CEMENT_LOT", "test_code": "CS28",
                          "value": "52.4", "product": "OPC", "status": "APPROVED", "updated_at": "2026-10-29 13:00"}])
    path = tmp_path / "exp"
    path.mkdir()
    late.to_csv(path / "lims_export.csv", index=False)
    cfg = lims.LimsConfig(enabled=True, mode="file", file_dir=str(path), watermark="2026-10-20 00:00:00")
    rep = lims.sync(cfg, db_path=db, log_path=tmp_path / "log.jsonl", persist_watermark=False)
    assert rep.cells_new == 1 and rep.cells_changed == 0
    got = load_raw(db)["physical"].iloc[0]
    assert got["phy_s28"] == pytest.approx(52.4) and got["phy_s3"] == pytest.approx(29.0) and got["sand_lot"] == "ISO-1"


def test_rest_mode_with_column_map(tmp_path):
    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"items": [{"DT": "2026-10-07 10:00", "PT": "CLINKER", "ITEM": "FCAO", "RES": "1.25",
                                          "ST": "A"}]}}

    class Sess:
        def __init__(self):
            self.kw = None

        def get(self, url, **kw):
            self.kw = kw
            return Resp()

    sess = Sess()
    cfg = lims.LimsConfig(enabled=True, mode="rest", rest_url="https://lims.local/api", rest_records_path="result.items",
                          column_map={"DT": "sampled_at", "PT": "sample_point", "ITEM": "test_code", "RES": "value",
                                      "ST": "status"})
    rep = lims.sync(cfg, db_path=tmp_path / "r.db", session=sess, log_path=tmp_path / "log.jsonl",
                    persist_watermark=False)
    assert not rep.errors and rep.rows_by_table == {"clinker": 1}
    assert "updated_since" in sess.kw["params"]
    assert load_raw(tmp_path / "r.db")["clinker"]["clk_fcao"].iloc[0] == pytest.approx(1.25)


def test_password_never_saved_in_url(tmp_path):
    cfg = lims.LimsConfig(sql_url="mssql+pyodbc://user:secret@host/db")
    with pytest.raises(ValueError):
        lims.save_lims_config(cfg, tmp_path / "lims.json")
    cfg.sql_url = "mssql+pyodbc://user:{password}@host/db"
    lims.save_lims_config(cfg, tmp_path / "lims.json")
    assert "secret" not in (tmp_path / "lims.json").read_text(encoding="utf-8")
