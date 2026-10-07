
from qms.diagnosis import diagnose, diagnosis_markdown
from qms.knowledge import AXES, KB, lookup


def _find(events, key, month, rule=None):
    return next(e for e in events if e.item_key == key and e.start.month == month and (rule is None or e.rule == rule))


def test_kb_entries_are_well_formed():
    for (key, direction), ph in KB.items():
        assert direction in ("high", "low")
        assert ph.hypotheses, key
        for h in ph.hypotheses:
            assert h.axis in AXES
            assert h.verify and h.short_term and h.root_cause, (key, h.title)


def test_unregistered_item_falls_back_to_five_axes():
    ph, registered = lookup("unknown_item", "high", "미등록 항목")
    assert not registered
    assert {h.axis for h in ph.hypotheses} == set(AXES)


def test_s1_underburning_is_top_cause_of_fcao(demo):
    store, reg, settings, _, events = demo
    dx = diagnose(_find(events, "clk_fcao", 7, "SPEC"), store, reg, settings)
    top = dx.results[0]
    assert top.hyp.axis == "공정" and "소성 부족" in top.hyp.title and top.verdict == "데이터 지지"
    assert all(ev.check.item != "clk_fcao" for r in dx.results for ev in r.evidences)  # 순환 증거 제외


def test_s2_raw_meal_lsf_is_top_cause_of_fcao(demo):
    store, reg, settings, _, events = demo
    dx = diagnose(_find(events, "clk_fcao", 8, "SPEC"), store, reg, settings)
    assert "생료 LSF" in dx.results[0].hyp.title


def test_s5_test_error_identified(demo):
    store, reg, settings, _, events = demo
    ev = next(e for e in events if e.item_key == "phy_s28" and e.rule == "SPEC" and e.start.month == 8)
    dx = diagnose(ev, store, reg, settings)
    assert dx.results[0].hyp.axis == "시험오차" and dx.results[0].supported
    assert "재시험" in dx.summary


def test_s3_fineness_explains_early_strength(demo):
    store, reg, settings, _, events = demo
    dx = diagnose(_find(events, "phy_s3", 9, "SPEC"), store, reg, settings)
    assert "분말도" in dx.results[0].hyp.title
    assert any("미도래" in r["KS 판정"] for r in dx.ks_eval)  # 28일 결과 미도래 → 예측 표시


def test_s4_so3_ks_evaluation_flags_nonconformity(demo):
    store, reg, settings, _, events = demo
    dx = diagnose(_find(events, "cem_so3", 9, "KS"), store, reg, settings)
    assert any("부적합" in r["KS 판정"] for r in dx.ks_eval)
    assert dx.results[0].verdict == "데이터 없음(추정)"  # 공급기 이상: 측정 데이터 없음 → 추정
    md = diagnosis_markdown(dx)
    for sec in ("①", "②", "③", "④", "⑤"):
        assert sec in md


def test_s6_autoclave_explained_by_mgo(demo):
    store, reg, settings, _, events = demo
    dx = diagnose(_find(events, "phy_autoclave", 8, "SPEC"), store, reg, settings)
    assert "MgO" in dx.results[0].hyp.title


def test_verification_plan_columns(demo):
    store, reg, settings, _, events = demo
    dx = diagnose(_find(events, "clk_fcao", 7, "SPEC"), store, reg, settings)
    plan = dx.verification_plan()
    assert list(plan.columns) == ["순위", "축", "원인 가설", "판정", "근거 점수", "확인 방법(데이터·시험)", "담당(제안)", "기한"]
    assert plan.iloc[0]["기한"].startswith("즉시")
