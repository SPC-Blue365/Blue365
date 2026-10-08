import pandas as pd
import pytest

from qms import chromium as crm
from qms.diagnosis import diagnose


def test_reducer_stoichiometry():
    assert crm.stoich("FeSO4·7H2O") == pytest.approx(16.04, abs=0.01)
    assert crm.stoich("FeSO4·H2O") == pytest.approx(9.80, abs=0.01)
    assert crm.stoich("SnSO4") == pytest.approx(6.20, abs=0.01)
    assert crm.CR2O3_TO_CR == pytest.approx(0.684, abs=0.001)


def test_mass_balance_arithmetic():
    kiln = pd.DataFrame([{"use": True, "name": "A", "group": "원료", "amount": 1000.0, "cr": 50.0, "retention": 100.0,
                          "note": ""}])
    mill = pd.DataFrame([{"use": True, "name": "석고", "pct": 10.0, "cr": 0.0, "crvi": 1.0, "note": ""}])
    p = crm.CrParams(conv_kiln=10.0, refr_wear=0.0, media_wear=0.0, dose=0.0)
    b = crm.cr_balance(kiln, mill, p)
    assert b.total_clk == pytest.approx(50.0)               # 1000 kg/t × 50 mg/kg / 1000
    assert b.crvi_clk == pytest.approx(5.0)
    assert b.clinker_fraction == pytest.approx(0.9)
    assert b.crvi_cement0 == pytest.approx(0.9 * 5.0 + 0.1 * 1.0)
    assert b.contrib["비율(%)"].sum() == pytest.approx(100.0)
    p2 = crm.CrParams(conv_kiln=10.0, refr_wear=0.2, refr_cr2o3=10.0, media_wear=0.0, dose=0.0)
    assert crm.cr_balance(kiln, mill, p2).total_clk == pytest.approx(50.0 + 0.2 * 10.0 * 10000 * crm.CR2O3_TO_CR / 1000)


def test_required_dose_roundtrip_and_degradation():
    p = crm.CrParams(months=2.0, mill_temp=110.0)
    d = crm.required_dose(15.0, 10.0, p)
    assert crm.after_reducer(15.0, d, p) == pytest.approx(10.0)
    assert crm.required_dose(5.0, 10.0, p) == 0.0
    fresh = crm.CrParams(months=0.0, after_mill=True)
    assert crm.reducer_retention(fresh) == pytest.approx(1.0)
    assert crm.reducer_retention(p) < crm.reducer_retention(crm.CrParams(months=2.0, after_mill=True))
    sn = crm.CrParams().with_reducer("SnSO4")
    assert crm.heat_factor(120, False, False) == 1.0
    assert crm.required_dose(15.0, 2.0, sn) < crm.required_dose(15.0, 2.0, crm.CrParams()) / 5


def test_tornado_and_solution_text():
    k, m = crm.default_kiln_inputs(), crm.default_mill_inputs()
    p = crm.CrParams()
    tor = crm.tornado(k, m, p)
    assert tor.iloc[-1]["입력"].startswith("킬른 전환율")    # 전환율 민감도가 가장 큼
    md = crm.cr_solution_markdown(crm.cr_balance(k, m, p))
    assert "단기 조치" in md and "근본 대책" in md


def test_calibration_and_reducer_effect_on_demo(demo):
    store = demo[0]
    pairs = crm.pairs_from_store(store)
    cal = crm.calibrate_conversion(pairs)
    assert cal.n > 100
    assert cal.median == pytest.approx(12.0, abs=1.0)        # 데모 전환율 12%
    assert cal.coef is not None and cal.coef["o2"] > 0       # 산소↑ → 전환율↑
    eff = crm.reducer_effect_series(store)
    assert eff["실효 제거량"].mean() == pytest.approx(3.0, abs=0.5)


def test_demo_s7_crvi_event_is_diagnosed_as_raw_material(demo):
    store, reg, settings, _, events = demo
    ev = [e for e in events if e.item_key == "phy_crvi" and e.severity == "위험"]
    assert ev and "자율기준" in ev[0].rule_desc
    dx = diagnose(ev[0], store, reg, settings)
    assert dx.results[0].hyp.title.startswith("원·부원료·연료 크롬")
    assert dx.results[0].verdict == "데이터 지지"
