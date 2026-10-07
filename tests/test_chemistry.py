import numpy as np
import pandas as pd
import pytest

from qms import chemistry as chem

CLK = dict(cao=65.8, sio2=21.9, al2o3=5.45, fe2o3=3.35)


def test_moduli_known_values():
    assert chem.lsf(**CLK) == pytest.approx(100 * 65.8 / (2.8 * 21.9 + 1.18 * 5.45 + 0.65 * 3.35))
    assert chem.lsf(**CLK) == pytest.approx(94.096, abs=1e-3)
    assert chem.silica_modulus(21.9, 5.45, 3.35) == pytest.approx(2.48864, abs=1e-5)
    assert chem.iron_modulus(5.45, 3.35) == pytest.approx(1.62687, abs=1e-5)


def test_lsf_gypsum_correction_lowers_value():
    base = chem.lsf(63.0, 20.5, 5.0, 3.2)
    corr = chem.lsf(63.0, 20.5, 5.0, 3.2, so3=2.6, gypsum_correction=True)
    assert corr < base
    assert corr == pytest.approx(100 * (63.0 - 0.7 * 2.6) / (2.8 * 20.5 + 1.18 * 5.0 + 0.65 * 3.2))


def test_bogue_astm_c150_normal_branch():
    ph = chem.bogue(65.8, 21.9, 5.45, 3.35, so3=0.7, fcao=1.0)
    c3s = 4.071 * 64.8 - 7.600 * 21.9 - 6.718 * 5.45 - 1.430 * 3.35 - 2.852 * 0.7
    assert ph["C3S"] == pytest.approx(c3s)
    assert ph["C2S"] == pytest.approx(2.867 * 21.9 - 0.7544 * c3s)
    assert ph["C3A"] == pytest.approx(2.650 * 5.45 - 1.692 * 3.35)
    assert ph["C4AF"] == pytest.approx(3.043 * 3.35)


def test_bogue_low_af_branch_has_no_c3a():
    ph = chem.bogue(64.0, 21.0, 2.0, 4.0)
    assert ph["C3A"] == 0
    assert ph["C4AF"] == pytest.approx(2.100 * 2.0 + 1.702 * 4.0)


def test_bogue_series_input_returns_series():
    df = pd.DataFrame({"c": [65.8, 66.2], "s": [21.9, 21.5], "a": [5.45, 5.3], "f": [3.35, 3.3]})
    ph = chem.bogue(df["c"], df["s"], df["a"], df["f"])
    assert isinstance(ph["C3S"], pd.Series)
    assert len(ph["C3S"]) == 2 and ph["C3S"].iloc[1] > ph["C3S"].iloc[0]


def test_liquid_phase_caps_mgo_at_2():
    l1 = chem.liquid_phase_1450(5.45, 3.35, mgo=2.0, k2o=0.8, na2o=0.18)
    l2 = chem.liquid_phase_1450(5.45, 3.35, mgo=4.0, k2o=0.8, na2o=0.18)
    assert l1 == pytest.approx(3.0 * 5.45 + 2.25 * 3.35 + 2.0 + 0.98)
    assert l1 == pytest.approx(l2)


def test_na2o_eq():
    assert chem.na2o_eq(0.2, 0.8) == pytest.approx(0.2 + 0.658 * 0.8)


def test_add_clinker_derived_columns():
    df = pd.DataFrame({"clk_cao": [65.8], "clk_sio2": [21.9], "clk_al2o3": [5.45], "clk_fe2o3": [3.35], "clk_mgo": [2.6],
                       "clk_so3": [0.7], "clk_k2o": [0.8], "clk_na2o": [0.18], "clk_fcao": [1.0]})
    out = chem.add_clinker_derived(df)
    for col in ("clk_lsf", "clk_sm", "clk_im", "clk_c3s", "clk_c2s", "clk_c3a", "clk_c4af", "clk_liquid", "clk_na2oeq"):
        assert col in out and np.isfinite(out[col].iloc[0])
    assert "clk_lsf" not in df  # 입력 불변


def test_raw_mix_3_hits_targets():
    mats = [{"CaO": 52.0, "SiO2": 4.0, "Al2O3": 1.0, "Fe2O3": 0.5},
            {"CaO": 3.0, "SiO2": 60.0, "Al2O3": 15.0, "Fe2O3": 6.0},
            {"CaO": 2.0, "SiO2": 12.0, "Al2O3": 3.0, "Fe2O3": 75.0}]
    r = chem.raw_mix_3(mats, 99.0, 2.5)
    assert r["feasible"]
    assert sum(r["ratios"]) == pytest.approx(100.0)
    assert r["lsf"] == pytest.approx(99.0)
    assert r["sm"] == pytest.approx(2.5)


def test_raw_mix_3_infeasible_flags_negative_ratio():
    mats = [{"CaO": 52.0, "SiO2": 4.0, "Al2O3": 1.0, "Fe2O3": 0.5},
            {"CaO": 3.0, "SiO2": 60.0, "Al2O3": 15.0, "Fe2O3": 6.0},
            {"CaO": 2.0, "SiO2": 12.0, "Al2O3": 3.0, "Fe2O3": 75.0}]
    r = chem.raw_mix_3(mats, 99.0, 8.0)  # 달성 불가능한 SM
    assert not r["feasible"]
