import pandas as pd
import pytest

from qms.alerts import detect_events, detect_item_events, events_frame, latest_status
from qms.standards import DEFAULT_SETTINGS, ItemSpec, Limits, SpecRegistry

SET = dict(DEFAULT_SETTINGS)


def _series(values, freq="2h", start="2026-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def _item(**kw):
    base = dict(key="x", name="X", stage="클링커", table="clinker", unit="%", decimals=2,
                limits={"*": Limits(lsl=0.5, usl=1.5, ks_max=2.5)}, rules=())
    base.update(kw)
    return ItemSpec(**base)


def test_spec_and_ks_events_with_severity():
    vals = [1.0] * 30 + [1.7, 1.8, 1.9] + [1.0] * 30 + [2.7] + [1.0] * 10
    evs = detect_item_events(_series(vals), _item(), None, SET)
    assert [(e.rule, e.severity, e.n_points) for e in evs] == [("SPEC", "경고", 3), ("KS", "위험", 1)]
    assert evs[0].worst_value == pytest.approx(1.9) and evs[0].limit_value == 1.5


def test_points_close_in_time_merge_into_one_event():
    vals = [1.0] * 10 + [1.8, 1.0, 1.8, 1.0, 1.0, 1.8] + [1.0] * 10   # 2h 간격, 12h 이내
    evs = detect_item_events(_series(vals), _item(), None, SET)
    assert len(evs) == 1 and evs[0].n_points == 3


def test_far_apart_points_make_separate_events():
    vals = [1.0] * 10 + [1.8] + [1.0] * 20 + [1.8] + [1.0] * 5        # 42h 간격
    assert len(detect_item_events(_series(vals), _item(), None, SET)) == 2


def test_method_item_ks_violation_is_warning_and_prediction_capped():
    m = _item(ks_is_method=True, limits={"*": Limits(ks_min=19.0, ks_max=21.0)}, table="physical")
    evs = detect_item_events(_series([20.0] * 5 + [17.0] + [20.0] * 5, freq="1D"), m, None, SET)
    assert evs[0].severity == "경고"
    p = _item(prediction=True, limits={"*": Limits(lsl=48.0, ks_min=42.5)}, table="physical")
    evs = detect_item_events(_series([52.0] * 5 + [41.0] + [52.0] * 5, freq="1D"), p, None, SET)
    assert evs[0].severity == "경고" and "(예측)" in evs[0].rule_desc


def test_spc_pattern_overlapping_limit_event_is_attached_not_duplicated():
    vals = [1.0 + 0.02 * ((i % 5) - 2) for i in range(120)] + [1.9] * 6 + [1.0] * 30
    it = _item(rules=("R1", "R2"))
    evs = detect_item_events(_series(vals), it, None, SET)
    limit = [e for e in evs if e.rule == "SPEC"]
    assert len(limit) == 1 and "R1" in limit[0].patterns
    assert not any(e.rule == "R1" and e.start >= limit[0].start - pd.Timedelta(hours=8) and
                   e.end <= limit[0].end + pd.Timedelta(hours=8) for e in evs)


def test_demo_scenarios_are_detected(demo):
    store, reg, settings, models, events = demo
    def has(key, rule=None, month=None, sev=None):
        return any(e.item_key == key and (rule is None or e.rule == rule) and (month is None or e.start.month == month)
                   and (sev is None or e.severity == sev) for e in events)
    assert has("clk_fcao", "SPEC", 7)          # S1 소성 부족
    assert has("kiln_bzt", "SPEC", 7)
    assert has("rm_mgo", "SPEC", 7) or has("rm_mgo", "SPEC", 8)  # S6
    assert has("phy_autoclave", "SPEC", 8)
    assert has("rm_lsf", "SPEC", 8)            # S2
    assert has("lab_cure_temp", "KS", 8)       # S5
    assert has("phy_s28", "SPEC", 8)
    assert has("cem_so3", "KS", 9, "위험")      # S4
    assert has("cem_blaine", "SPEC", 9)        # S3
    assert has("pred_s28", "SPEC", 9)          # S3 예측 경보
    assert 40 < len(events) < 250              # 과도한 허위 경보가 없어야 함


def test_events_frame_and_latest_status(demo):
    store, reg, settings, models, events = demo
    df = events_frame(events)
    assert {"severity", "item_name", "status"} <= set(df.columns)
    assert (df["status"] == "신규").all()
    st = latest_status(store, reg, settings, events)
    assert len(st) >= len(reg.key_items())
    assert set(st["status"]) <= {"정상", "주의", "경고", "위험"}


def test_detect_events_respects_period_filter(demo):
    store, reg, settings, models, events = demo
    late = detect_events(store, reg, settings, start=pd.Timestamp("2026-09-15"))
    assert late and all(e.end >= pd.Timestamp("2026-09-15") for e in late)


def test_overrides_change_detection(demo):
    store, _, settings, _, _ = demo
    reg = SpecRegistry(overrides={"clk_fcao": {"*": {"usl": 3.5}}})
    evs = [e for e in detect_events(store, reg, settings) if e.item_key == "clk_fcao" and e.direction == "high"
           and e.rule == "SPEC"]
    assert not evs
    assert reg.overrides_vs_default() == {"clk_fcao": {"*": {"usl": 3.5}}}
