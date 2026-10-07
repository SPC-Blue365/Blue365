import numpy as np

from qms.prediction import fit_models, predict


def test_models_fit_reasonably(demo):
    store, reg, settings, models, events = demo
    m = models["1종"]
    assert {"M7", "M3", "MC"} <= set(m)
    assert m["M7"].r2 > 0.3 and m["M7"].rmse < 2.0
    assert "28일 =" in m["M7"].equation()


def test_predictions_only_for_pending_lots(demo):
    store, reg, settings, models, events = demo
    phy = store.tables["physical"]
    assert phy.loc[phy["phy_s28"].notna(), "pred_s28"].isna().all()
    pending = phy[phy["phy_s28"].isna()]
    assert pending["pred_s28"].notna().all()


def test_s3_pending_lots_predicted_low_and_s5_residual(demo):
    store, reg, settings, models, events = demo
    p = predict(store, "1종", models["1종"])
    s3 = p[(p["timestamp"] >= "2026-09-19") & (p["timestamp"] <= "2026-09-22 23:00")]
    assert (s3["s28_pred"] < 48.0).all()
    s5 = p[p["timestamp"].dt.strftime("%m-%d") == "08-19"]
    assert float(s5["resid_z"].iloc[0]) < -2.5
    assert np.isfinite(p["pred_lo"]).any()


def test_fit_models_handles_missing_product(demo):
    store, *_ = demo
    assert fit_models(store, "5종") == {}
