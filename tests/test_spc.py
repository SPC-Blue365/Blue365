import numpy as np
import pandas as pd
import pytest

from qms.spc import ControlStats, baseline_stats, capability, capability_grade, rule_flags

ST = ControlStats(center=0.0, sigma=1.0, sigma_within=1.0, n=100)


def test_r1_flags_points_beyond_3_sigma():
    x = np.zeros(20)
    x[5] = 3.5
    x[12] = -3.2
    f = rule_flags(x, ST, ["R1"])["R1"]
    assert list(np.flatnonzero(f)) == [5, 12]


def test_r2_flags_whole_run_of_nine():
    x = np.r_[np.full(5, -0.5), np.full(9, 0.3), np.full(5, -0.2)]
    f = rule_flags(x, ST, ["R2"], run_length=9)["R2"]
    assert f[5:14].all() and not f[:5].any() and not f[14:].any()
    x2 = np.r_[np.full(8, 0.3), [-0.1]]
    assert not rule_flags(x2, ST, ["R2"], run_length=9)["R2"].any()


def test_r3_trend_six_points():
    x = np.r_[[0, 0.1, 0.2, 0.3, 0.4, 0.5], [0.1, 0.0]]
    f = rule_flags(x, ST, ["R3"], trend_length=6)["R3"]
    assert f[:6].all() and not f[6:].any()
    x5 = np.array([0, 0.1, 0.2, 0.3, 0.4, 0.2])  # 5점 상승은 미해당
    assert not rule_flags(x5, ST, ["R3"], trend_length=6)["R3"].any()


def test_r5_two_of_three_beyond_2sigma_same_side():
    x = np.array([0, 2.2, 0.1, 2.5, 0, 0, -2.1, 0.0, 2.3])
    f = rule_flags(x, ST, ["R5"])["R5"]
    assert f[1] and f[3] and not f[6] and not f[8]


def test_baseline_uses_first_days_and_trims_outliers():
    idx = pd.date_range("2026-01-01", periods=200, freq="12h")
    rng = np.random.default_rng(0)
    vals = rng.normal(10, 1, 200)
    vals[150:] += 5  # 기준기간 이후 이동
    vals[3] = 50     # 기준기간 내 이상점 → 제외되어야 함
    s = pd.Series(vals, index=idx)
    stats = baseline_stats(s, {"baseline_days": 30})
    assert stats.center == pytest.approx(10, abs=0.4)
    assert stats.sigma == pytest.approx(1, abs=0.3)
    assert stats.base_end < idx[0] + pd.Timedelta(days=30)


def test_capability_indices():
    rng = np.random.default_rng(1)
    s = pd.Series(rng.normal(100, 1, 5000))
    cap = capability(s, 96, 104)
    assert cap["Ppk"] == pytest.approx(4 / 3, abs=0.06)
    assert cap["Cpk"] == pytest.approx(4 / 3, abs=0.08)
    one_sided = capability(s, None, 103)
    assert one_sided["Ppk"] == pytest.approx(1.0, abs=0.05)
    assert np.isnan(one_sided["Cp"])


def test_capability_grade_labels():
    assert capability_grade(1.7) == "매우 우수"
    assert capability_grade(1.4) == "충분"
    assert capability_grade(0.5).startswith("매우 부족")
    assert capability_grade(float("nan")) == "-"
