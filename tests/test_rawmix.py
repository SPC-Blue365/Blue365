import io

import numpy as np
import pandas as pd
import pytest

from qms import chemistry as chem
from qms import rawmix as rmx


@pytest.fixture()
def mats():
    return rmx.default_materials()


def test_lsq_mix_hits_clinker_targets_within_bounds(mats):
    res = rmx.solve_mix(mats, rmx.MixTargets(), rmx.KilnParams())
    assert res.feasible, res.messages
    assert abs(res.achieved["LSF"] - 95.0) <= 0.3
    assert abs(res.achieved["SM"] - 2.50) <= 0.02 and abs(res.achieved["IM"] - 1.60) <= 0.02
    assert res.x.sum() == pytest.approx(1.0, abs=1e-6)
    lo, hi = res.mats["min"].to_numpy() / 100, res.mats["max"].to_numpy() / 100
    assert np.all(res.x >= lo - 1e-9) and np.all(res.x <= hi + 1e-9)
    assert res.wet.sum() == pytest.approx(1.0)
    # 석탄회 흡수로 생료 LSF 가 클링커보다 높다(약 3~5)
    assert 2.0 < res.clinker["raw_lsf"] - res.clinker["LSF"] < 6.0


def test_predicted_clinker_moduli_match_chemistry(mats):
    res = rmx.solve_mix(mats, rmx.MixTargets(), rmx.KilnParams())
    c = res.clinker["clinker"]
    assert res.clinker["LSF"] == pytest.approx(float(chem.lsf(c["CaO"], c["SiO2"], c["Al2O3"], c["Fe2O3"])))
    ph = chem.bogue(c["CaO"], c["SiO2"], c["Al2O3"], c["Fe2O3"], c["SO3"], res.clinker["fcao"])
    assert res.clinker["C3S"] == pytest.approx(ph["C3S"])


def test_fixed_material_and_cost_mode(mats):
    m = mats.copy()
    m.loc[m["name"].str.startswith("석탄재"), "fixed"] = 5.0
    res = rmx.solve_mix(m, rmx.MixTargets(), rmx.KilnParams())
    i = res.names.index("석탄재(플라이애시)")
    assert res.x[i] == pytest.approx(0.05)
    assert res.feasible
    lsq = rmx.solve_mix(mats, rmx.MixTargets(), rmx.KilnParams())
    cost = rmx.solve_mix(mats, rmx.MixTargets(), rmx.KilnParams(), mode="cost")
    assert cost.mode == "원가 최소" and cost.feasible
    assert cost.cost_per_t_clk <= lsq.cost_per_t_clk + 1e-6


def test_c3s_target_instead_of_lsf_and_raw_basis(mats):
    t = rmx.MixTargets(enabled={"LSF": False, "SM": True, "IM": True, "C3S": True},
                       values={"LSF": 95, "SM": 2.5, "IM": 1.6, "C3S": 58.0})
    res = rmx.solve_mix(mats, t, rmx.KilnParams())
    assert res.feasible and abs(res.achieved["C3S"] - 58.0) <= 0.5
    raw = rmx.solve_mix(mats, rmx.MixTargets(basis="raw", values={"LSF": 99, "SM": 2.55, "IM": 1.58, "C3S": 57}),
                        rmx.KilnParams())
    assert raw.feasible and abs(raw.clinker["raw_lsf"] - 99.0) <= 0.3


def test_infeasible_target_is_reported(mats):
    res = rmx.solve_mix(mats, rmx.MixTargets(values={"LSF": 95, "SM": 2.5, "IM": 3.0, "C3S": 57}), rmx.KilnParams())
    assert not res.feasible
    assert any("목표 미달" in m for m in res.messages)


def test_input_validation(mats):
    with pytest.raises(ValueError):
        rmx.solve_mix(mats.assign(use=False), rmx.MixTargets(), rmx.KilnParams())
    with pytest.raises(ValueError):
        rmx.solve_mix(mats, rmx.MixTargets(enabled={k: False for k in rmx.TARGET_KEYS}), rmx.KilnParams())


def test_models_learn_demo_relationships(demo):
    store = demo[0]
    fm = rmx.fit_fcao_model(store)
    assert fm.source == "공장 데이터 학습"
    assert fm.coef["lsf"] == pytest.approx(0.32, abs=0.06)      # 데모 생성식 0.32
    assert fm.coef["bzt"] == pytest.approx(-0.028, abs=0.008)
    xm = rmx.fit_xrd_map(store)
    b0, b1 = xm.coef["alite"]
    assert b0 + b1 * 57.0 == pytest.approx(57.0 + 6.5, abs=1.0)  # 데모: XRD 알라이트 ≈ Bogue + 6.5
    chk, summ = rmx.conversion_check(store, rmx.KilnParams())
    assert len(chk) > 1000
    assert summ["a_eff"] == pytest.approx(0.015, abs=0.002)    # 데모 석탄회 흡수 1.5%
    assert summ["LSF"]["rmse"] < 0.8


def test_design_workbook_roundtrip(mats):
    t, kp = rmx.MixTargets(), rmx.KilnParams()
    res = rmx.solve_mix(mats, t, kp)
    data = rmx.design_workbook(mats, t, kp, res)
    sheet = pd.read_excel(io.BytesIO(data), sheet_name="원료성분")
    buf = io.BytesIO()
    sheet.to_excel(buf, index=False)
    back = rmx.parse_materials(buf.getvalue(), "m.xlsx")
    assert back["name"].tolist() == mats["name"].tolist()
    assert back["CaO"].tolist() == pytest.approx(mats["CaO"].tolist())


def test_add_candidate_respects_cap(mats):
    df = rmx.default_materials()
    assert rmx.category_counts(df)["실리카원"] == 1
    for i in range(10):
        df = rmx.add_candidate(df, "실리카원")
    assert rmx.category_counts(df)["실리카원"] == rmx.MAX_PER_CATEGORY      # 상한에서 멈춤
    assert not rmx.over_cap(df)
    names = df[df["category"] == "실리카원"]["name"].tolist()
    assert names[0] == "규석" and names[1] == "실리카원 후보2" and len(set(names)) == len(names)


def test_fill_candidates_makes_five_each():
    df = rmx.fill_candidates(rmx.default_materials())
    c = rmx.category_counts(df)
    assert all(c[cat] == 5 for cat in ("실리카원", "알루미나원", "철질원", "기타"))
    assert (~df[df["name"].str.contains("후보")]["use"]).all()      # 후보는 미사용 상태로 추가됨


def test_solve_with_multiple_candidates_per_category(mats):
    """실리카원 2종을 모두 '사용'으로 켜도 합계 1, 목표 LSF 달성."""
    df = rmx.add_candidate(mats, "실리카원")
    i = df.index[df["category"] == "실리카원"][-1]
    df.loc[i, ["use", "name", "SiO2", "Al2O3", "Fe2O3", "CaO", "LOI", "max"]] = [True, "규사2", 95.0, 2.0, 1.0, 0.5, 1.0, 15.0]
    res = rmx.solve_mix(df, rmx.MixTargets(), rmx.KilnParams())
    assert len(res.x) == 6 and res.x.sum() == pytest.approx(1.0, abs=1e-4)
    assert abs(res.deviation["LSF"]) <= rmx.TOL["LSF"] + 1e-9
    assert "규사2" in res.names
