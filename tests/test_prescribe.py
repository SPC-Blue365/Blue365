"""배합 처방(prescribe.py)·구역 재고 복원(inventory.py) 단위 테스트.

검증 대상 규칙:
  - 처방은 **확률 없이 나가지 않는다** — 규격 적중 확률을 늘 함께 낸다(§2-1)
  - 목표 달성 불가 시 억지 답 대신 **근접 배합 + 경고 + 병목** (CLAUDE.md §3)
  - 구역 재고 복원은 **라인 실사 합계에 맞춰 재정규화**하고, 음수 절단을 숨기지 않는다
  - 품위를 모르는 구역은 처방 후보에서 제외한다 (라인 평균으로 때우면 가짜 정밀도)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config import schema as S
from src.matching.inventory import withdrawal_rate, zone_inventory
from src.optimization.prescribe import prescribe, zone_balance_health

LN = S.LINE_NEW


def _mine(rows):
    """rows = [(날짜, zone, cao, mgo, ton)]"""
    return pd.DataFrame([{"datetime": pd.Timestamp(d), "date": pd.Timestamp(d).floor("D"),
                          "line": LN, "zone": z, "cao": c, "mgo": g, "tonnage": t,
                          "source": "49Q"} for d, z, c, g, t in rows])


def _osp(rows):
    """rows = [(시각, zone, ton)]"""
    return pd.DataFrame([{"datetime": pd.Timestamp(d), "line": LN, "zone": z,
                          "withdrawn_ton": t, "expected_cao": np.nan, "expected_mgo": np.nan}
                         for d, z, t in rows])


def _stock(pairs):
    return pd.DataFrame([{"datetime": pd.Timestamp(d), "line": LN, "stock_ton": t}
                         for d, t in pairs])


def _case():
    """고품위(48)·저품위(42) 구역이 각각 넉넉히 있는 단순한 적치장."""
    mine = _mine([("2026-06-11", 50.0, 48.0, 2.0, 20_000.0),
                  ("2026-06-11", 60.0, 42.0, 4.0, 20_000.0),
                  ("2026-06-20", 50.0, 48.0, 2.0, 5_000.0),
                  ("2026-06-20", 60.0, 42.0, 4.0, 5_000.0)])
    osp = _osp([("2026-06-25 08:00", 50.0, 1_000.0), ("2026-06-25 16:00", 60.0, 1_000.0),
                ("2026-06-26 08:00", 50.0, 1_000.0), ("2026-06-26 16:00", 60.0, 1_000.0)])
    stock = _stock([("2026-06-11", 30_000.0), ("2026-06-20", 40_000.0), ("2026-06-26", 40_000.0)])
    return mine, osp, stock


def test_prescription_always_reports_probability():
    """처방에는 규격 적중 확률이 반드시 붙는다."""
    mine, osp, stock = _case()
    p = prescribe(mine, osp, stock, LN, hours=8, rate_tph=100.0)
    assert p is not None
    assert np.isfinite(p.p_in_spec) and 0.0 <= p.p_in_spec <= 1.0
    assert np.isfinite(p.blend_se) and p.blend_se >= 0


def test_blend_hits_target_between_two_grades():
    """48%와 42% 구역이 있으면 44.6% 는 두 구역을 섞어 맞출 수 있어야 한다."""
    mine, osp, stock = _case()
    p = prescribe(mine, osp, stock, LN, hours=8, rate_tph=100.0)
    assert p.feasible
    assert abs(p.achieved_cao - S.TARGET.cao_mean) <= S.TARGET.tol
    assert set(p.allocation["zone"]) == {50.0, 60.0}
    assert abs(p.allocation["ton"].sum() - p.demand_ton) < 1.0


def test_infeasible_reports_bottleneck_not_a_made_up_answer():
    """목표보다 높은 품위만 있으면 억지로 맞추지 않고 병목을 보고한다 (§2-1)."""
    mine = _mine([("2026-06-11", 50.0, 49.0, 2.0, 20_000.0),
                  ("2026-06-20", 50.0, 49.0, 2.0, 5_000.0)])
    osp = _osp([("2026-06-25 08:00", 50.0, 1_000.0), ("2026-06-26 08:00", 50.0, 1_000.0)])
    stock = _stock([("2026-06-11", 30_000.0), ("2026-06-26", 40_000.0)])
    p = prescribe(mine, osp, stock, LN, hours=8, rate_tph=100.0)
    assert not p.feasible
    assert p.message and p.bottleneck          # 무엇이 막았는지 반드시 말한다
    assert p.achieved_cao > S.TARGET.cao_mean  # 근접 배합은 여전히 낸다
    assert not p.allocation.empty


def test_mgo_is_reported_alongside_cao():
    """사용자 의도는 CaO·MgO 둘 다이므로 MgO 도 함께 나와야 한다."""
    mine, osp, stock = _case()
    p = prescribe(mine, osp, stock, LN, hours=8, rate_tph=100.0)
    assert np.isfinite(p.achieved_mgo)
    w = p.allocation["ton"] / p.demand_ton
    assert abs(float((w * p.allocation["mgo"]).sum()) - p.achieved_mgo) < 1e-6


def test_sentence_is_the_requested_format():
    """산출 문장이 '몇 번에서 몇 톤 · 몇 시간' 형식이어야 한다."""
    mine, osp, stock = _case()
    p = prescribe(mine, osp, stock, LN, hours=6, rate_tph=100.0)
    s = p.sentence()
    assert "6시간" in s and "번에서" in s and "톤" in s
    assert "톤 을" not in s                     # 조사 앞 공백 회귀 방지


def test_zone_inventory_anchors_to_line_stock():
    """복원한 구역 재고의 합은 실사 라인 재고와 같아야 한다."""
    mine, osp, stock = _case()
    inv = zone_inventory(mine, osp, stock, LN)
    assert inv is not None and inv.anchored
    assert abs(float(inv.zones["ton"].sum()) - inv.line_total) < 1.0
    assert (inv.zones["ton"] >= 0).all()        # 음수 재고는 남기지 않는다


def test_zone_inventory_excludes_unknown_grade_zones():
    """품위를 모르는 구역은 처방 후보에서 빠지고, 그 사실이 기록된다."""
    mine, osp, stock = _case()
    osp2 = pd.concat([osp, _osp([("2026-06-26 20:00", 99.0, 500.0)])], ignore_index=True)
    inv = zone_inventory(mine, osp2, stock, LN)
    assert 99.0 not in set(inv.usable()["zone"])


def test_zone_balance_health_flags_mismatch():
    """적재 없이 인출만 있는 구역은 '수지 이상' 으로 잡혀야 한다."""
    mine, osp, _ = _case()
    osp2 = pd.concat([osp, _osp([("2026-06-27 08:00", 80.0, 9_000.0)])], ignore_index=True)
    h = zone_balance_health(mine, osp2, LN)
    assert h["n_bad"] >= 1
    assert h["bad_ton"] >= 9_000.0


def test_withdrawal_rate_is_positive():
    _, osp, _ = _case()
    r = withdrawal_rate(osp, LN, days=60)
    assert np.isfinite(r) and r > 0


def test_returns_none_without_data():
    """데이터가 없으면 억지 처방을 만들지 않는다."""
    empty = _mine([]).iloc[0:0]
    assert prescribe(empty, _osp([]).iloc[0:0], _stock([]).iloc[0:0], LN) is None


@pytest.mark.parametrize("hours", [1.0, 8.0, 24.0])
def test_demand_scales_with_hours(hours):
    """수요 톤은 시간 × 인출속도 여야 한다."""
    mine, osp, stock = _case()
    p = prescribe(mine, osp, stock, LN, hours=hours, rate_tph=100.0)
    assert abs(p.demand_ton - hours * 100.0) < 1e-6
