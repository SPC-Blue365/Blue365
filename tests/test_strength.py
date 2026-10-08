import numpy as np
import pytest

from qms import strength as stg
from qms.rawmix import fit_xrd_map


@pytest.fixture(scope="module")
def models(demo):
    store, reg = demo[0], demo[1]
    xm = fit_xrd_map(store)
    return {p: stg.fit_strength_models(store, reg, p, xm) for p in ("1종", "3종")}, reg


def test_models_fit_with_plausible_accuracy_and_signs(models):
    sms, _ = models
    sm = sms["1종"]
    assert set(sm.models) >= {"phy_s3", "phy_s7", "phy_s28", "phy_ist", "phy_fst"}
    assert "phy_s1" not in sm.models                     # 1종은 1일 강도 시험 없음
    assert sm.models["phy_s3"].rmse < 1.5 and sm.models["phy_s28"].rmse < 2.0
    m28 = sm.models["phy_s28"]
    coef = dict(zip(m28.features, m28.beta))
    assert coef["alite"] > 0 and coef["blaine"] > 0 and coef["ls"] < 0 and coef["fcao"] < 0
    assert m28.n_excluded >= 1                            # S5 양생수 온도 이탈 로트 제외
    assert sm.train["phase_src"].eq("XRD").mean() > 0.9   # XRD 실측 우선 사용
    assert "phy_s1" in sms["3종"].models


def test_prior_ridge_keeps_prior_with_little_data_and_fixes_wrong_sign():
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (8, 2))
    y = rng.normal(0, 1, 8)
    beta0 = np.array([0.5, -0.3])
    *_, beta, lam, rmse, r2, fixed = stg._fit_prior_ridge(X, y, beta0, np.ones(2))
    assert np.allclose(beta, beta0, atol=0.4)            # 정보가 없으면 경험칙 근처
    # 강한 반대 부호 데이터 → 부호 제약으로 경험칙 고정
    X2 = rng.normal(0, 1, (200, 1))
    y2 = -2.0 * X2[:, 0] + rng.normal(0, 0.1, 200)
    *_, beta2, lam2, _, _, fixed2 = stg._fit_prior_ridge(X2, y2, np.array([1.0]), np.ones(1), signs=np.array([1]))
    assert fixed2[0] and beta2[0] == pytest.approx(1.0)


def test_prediction_table_and_contributions(models):
    sms, _ = models
    sm = sms["1종"]
    base, ts = sm.latest_inputs()
    assert ts is not None
    pred = sm.predict(base)
    assert {"예측", "하한(95%)", "상한(95%)", "판정"} <= set(pred.columns)
    p28 = pred.loc[pred["target"] == "phy_s28", "예측"].iloc[0]
    assert 45 < p28 < 60
    higher = dict(base, blaine=base["blaine"] + 200)
    assert sm.predict_values(higher)["phy_s3"] > sm.predict_values(base)["phy_s3"]
    contrib = sm.models["phy_s28"].contributions(stg.features_from_inputs(base, sm.so3_opt))
    assert set(contrib) == set(sm.models["phy_s28"].features)


def test_optimizer_finds_minimal_lever_change(models):
    sms, reg = models
    sm = sms["1종"]
    base, _ = sm.latest_inputs()
    p0 = sm.predict_values(base)
    goals = {"phy_s28": (p0["phy_s28"] + 1.5, None)}
    plan = stg.optimize_controls(sm, base, goals)
    assert not plan.unmet
    assert plan.pred_after["phy_s28"] >= p0["phy_s28"] + 1.5 - 0.05
    assert 1 <= len(plan.lever_table()) <= 3                # 최소 변경 조합(희소)
    # 초결 연장 → SO3(석고) 증량이 선택되어야 함
    plan2 = stg.optimize_controls(sm, base, {"phy_ist": (p0["phy_ist"] + 20, None)})
    assert "so3" in plan2.deltas and plan2.after["so3"] > base["so3"]
    # 불가능한 목표 → 미충족 보고
    plan3 = stg.optimize_controls(sm, base, {"phy_s28": (75.0, None)})
    assert plan3.unmet == ["phy_s28"] and plan3.messages
    md = stg.solution_markdown(sm, plan3, "1종")
    assert "장기강도" in md


def test_default_goals_follow_plant_spec(models):
    sms, reg = models
    goals = stg.default_goals(reg, "1종", sms["1종"].models)
    assert goals["phy_s28"] == (48.0, None) and goals["phy_ist"] == (150.0, 300.0)
    tgt = stg.default_goals(reg, "1종", sms["1종"].models, basis="target")
    assert tgt["phy_s28"] == (53.0, None) and tgt["phy_ist"] == (150.0, 300.0)
