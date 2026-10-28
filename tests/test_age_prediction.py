"""재령별 강도 예측·출하시멘트 강도의 물성 표 보강·원인 진단 분류 시험."""

import numpy as np
import pandas as pd

from qms import prediction as P
from qms.alerts import AlertEvent, event_category
from qms.store import DataStore, enrich


def _store(n=120, seed=3):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-01-01", periods=n, freq="D")
    blaine = rng.normal(3800, 80, n)
    s1 = 15 + 0.004 * (blaine - 3800) + rng.normal(0, 0.6, n)
    s3 = 18 + 1.0 * s1 + rng.normal(0, 0.8, n)
    s7 = 10 + 1.0 * s3 + rng.normal(0, 0.8, n)
    s28 = 12 + 0.9 * s7 + rng.normal(0, 0.8, n)
    phy = pd.DataFrame({"timestamp": days, "product": "1종", "phy_s1": s1, "phy_s3": s3, "phy_s7": s7, "phy_s28": s28,
                        "lot_blaine": blaine, "lot_so3": rng.normal(2.6, 0.05, n), "lot_loi": rng.normal(2.0, 0.2, n)})
    phy.loc[phy.index[-5:], "phy_s28"] = np.nan                 # 28일 결과 미도래
    phy.loc[phy.index[-2:], "phy_s7"] = np.nan                  # 7일 결과도 아직
    return DataStore(enrich({"physical": phy}))


def test_age_models_rank_by_error_and_use_latest_available_age():
    st = _store()
    ms = P.fit_age_models(st, "1종", 28)
    assert ms and [m.rmse for m in ms] == sorted(m.rmse for m in ms) and "7" in ms[0].label
    p = P.predict_age(st, "1종", 28, ms)
    assert p["pred"].iloc[-5:].notna().all()                   # 미도래 로트도 예측
    assert all("7" not in m for m in p["model"].iloc[-2:])     # 7일 결과 전 로트는 3일·1일·화학 모델로
    assert p["loo_pred"].notna().sum() > 100
    assert P.fit_age_models(st, "1종", 1)                       # 1일: 화학·분말도 기반
    assert P.products_with_strength(st) == ["1종"]


def test_shipment_strength_feeds_physical(monkeypatch):
    from qms import shipment as S
    from qms import store as M
    ship = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-01", "2026-10-02"]), "product": ["1종", "1종", "3종"],
                         "s1": [15.0, 16.0, 28.0], "s3": [35.0, 36.0, 44.0], "s7": [45.0, None, 50.0], "s28": [56.0, None, None],
                         "fst": [390.0, 380.0, 240.0], "blaine": [3800.0, 3810.0, 4700.0], "x:Autoclave": [0.1, 0.12, 0.2]})
    monkeypatch.setattr(S, "load_shipment", lambda: ship)
    phy = M.shipment_physical()
    assert len(phy) == 3 and phy["timestamp"].dt.minute.tolist() == [0, 1, 0]   # 같은 날·품종 로트는 1분 간격
    assert phy["phy_s28"].iloc[0] == 56.0 and phy["lot_blaine"].iloc[2] == 4700.0 and phy["phy_autoclave"].iloc[1] == 0.12


def test_event_category():
    def ev(key, stage):
        return AlertEvent("x", key, key, stage, None, "경고", "SPEC", "", "high", pd.Timestamp(0), pd.Timestamp(0), 1, 0.0,
                          None, "", 1, "")
    cases = (("phy_s28", "제품 물성"), ("pred_s28", "제품 물성"), ("cem_blaine", "시멘트(분쇄)"), ("clk_fcao", "클링커"),
             ("rm_lsf", "원료"), ("phy_fst", "제품 물성"))
    assert [event_category(ev(k, s)) for k, s in cases] == ["강도", "강도", "분말도", "소성·클링커", "원료", "응결·안정도"]
