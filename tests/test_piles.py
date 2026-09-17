"""적치장 더미 시뮬레이션 회귀 테스트 (합성 데이터) [Matching-Agent].

구역 귀속 붕괴(§6-0-22)를 다루는 로직은 **물량 수지**가 생명이다. 실데이터 없이도
"없는 재고는 나오지 않는다 / 총량은 보존된다 / 결측이 더미를 비우지 않는다" 를 고정한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config import schema as S
from src.matching import piles


def _mine(rows):
    """rows = [(일시, 라인, 구역, 톤, CaO, MgO)]"""
    return pd.DataFrame([
        dict(datetime=pd.Timestamp(d), line=ln, zone=float(z), tonnage=float(t),
             cao=c, mgo=m) for d, ln, z, t, c, m in rows])


def _osp(rows):
    """rows = [(일시, 라인, 구역, 톤)]"""
    return pd.DataFrame([
        dict(datetime=pd.Timestamp(d), line=ln, zone=(float(z) if z is not None else np.nan),
             withdrawn_ton=t, expected_cao=np.nan) for d, ln, z, t in rows])


LN = S.LINE_OLD


@pytest.fixture(autouse=True)
def _no_opening(monkeypatch):
    """기초 재고를 0 으로 둬 시뮬레이션을 순수 적재/인출만으로 검사한다."""
    monkeypatch.setitem(S.OSP_OPENING_STOCK, LN, 0.0)
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_NEW, 0.0)


def test_label_order_cannot_draw_from_an_empty_zone():
    """`label` 가정 — 그 구역에 쌓지 않았으면 뽑히지 않는다 (현행 해석의 한계)."""
    m = _mine([("2026-06-20 08:00", LN, 95.0, 1000.0, 46.0, 3.0)])
    o = _osp([("2026-06-21 08:00", LN, 90.0, 400.0)])
    sim = piles.simulate(m, o, LN, "label")
    assert sim["sim_ton"].iloc[0] == 0.0, "90번에는 쌓은 적이 없다"
    assert sim.attrs["short_ton"] == 400.0


def test_near_order_borrows_from_the_closest_zone_with_stock():
    """`near` 가정 — 라벨 구역이 비면 **번호가 가까운** 구역에서 채운다."""
    m = _mine([("2026-06-20 08:00", LN, 95.0, 1000.0, 48.0, 3.0),
               ("2026-06-20 09:00", LN, 40.0, 1000.0, 42.0, 3.0)])
    o = _osp([("2026-06-21 08:00", LN, 90.0, 400.0)])
    sim = piles.simulate(m, o, LN, "near")
    assert sim["sim_ton"].iloc[0] == 400.0
    assert sim["sim_cao"].iloc[0] == pytest.approx(48.0), "40번(42.0)이 아니라 95번에서 와야 한다"
    assert sim["same_zone"].iloc[0] == 0.0
    assert sim.attrs["short_ton"] == 0.0


def test_mix_order_takes_stock_proportionally():
    """`mix` 가정 — 라인 전체에서 재고 비례로 뽑는다(완전혼합)."""
    m = _mine([("2026-06-20 08:00", LN, 50.0, 3000.0, 44.0, 3.0),
               ("2026-06-20 09:00", LN, 90.0, 1000.0, 48.0, 3.0)])
    o = _osp([("2026-06-21 08:00", LN, 90.0, 400.0)])
    sim = piles.simulate(m, o, LN, "mix")
    assert sim["sim_cao"].iloc[0] == pytest.approx(44.0 * 0.75 + 48.0 * 0.25)


def test_fifo_and_lifo_pick_opposite_ends():
    """`fifo` 는 먼저 쌓은 것, `lifo` 는 나중에 쌓은 것부터."""
    m = _mine([("2026-06-20 08:00", LN, 50.0, 1000.0, 42.0, 3.0),
               ("2026-06-25 08:00", LN, 50.0, 1000.0, 48.0, 3.0)])
    o = _osp([("2026-06-26 08:00", LN, 50.0, 500.0)])
    assert piles.simulate(m, o, LN, "fifo")["sim_cao"].iloc[0] == pytest.approx(42.0)
    assert piles.simulate(m, o, LN, "lifo")["sim_cao"].iloc[0] == pytest.approx(48.0)


def test_total_drawn_never_exceeds_what_was_asked():
    """총량 보존 — 뽑힌 합이 요구한 합을 넘으면 안 된다."""
    m = _mine([(f"2026-06-2{i} 08:00", LN, 50.0 + 10 * (i % 3), 900.0, 44.0 + i, 3.0)
               for i in range(1, 9)])
    o = _osp([(f"2026-06-2{i} 20:00", LN, 60.0, 500.0) for i in range(1, 9)])
    for order in piles.DRAW_ORDERS:
        sim = piles.simulate(m, o, LN, order)
        assert sim["sim_ton"].sum() <= sim["ask"].sum() + 1e-6, order


def test_missing_tonnage_does_not_drain_the_pile():
    """🐞 결측 물량 — `min(x, nan)` 이 x 를 돌려주어 더미를 통째로 비우던 버그."""
    m = _mine([("2026-06-20 08:00", LN, 50.0, 5000.0, 45.0, 3.0)])
    o = _osp([("2026-06-21 08:00", LN, 50.0, np.nan),
              ("2026-06-22 08:00", LN, 50.0, 1000.0)])
    for order in piles.DRAW_ORDERS:
        sim = piles.simulate(m, o, LN, order)
        assert sim["sim_ton"].sum() == pytest.approx(1000.0), order
        assert sim.attrs["short_ton"] == 0.0, order


def test_simulate_keeps_the_original_index():
    """반환 프레임은 원본 osp 인덱스를 유지해야 그대로 붙여 쓸 수 있다."""
    m = _mine([("2026-06-20 08:00", LN, 50.0, 5000.0, 45.0, 3.0)])
    o = _osp([("2026-06-21 08:00", S.LINE_NEW, 50.0, 100.0),
              ("2026-06-21 09:00", LN, 50.0, 100.0)])
    sim = piles.simulate(m, o, LN, "near")
    assert list(sim.index) == [1], "그 라인 인출 행의 원본 인덱스만 나와야 한다"


def test_label_feasibility_reports_the_shortfall_share():
    """현행 해석이 물리적으로 몇 % 불가능한지 — 순수 물량 수지."""
    m = _mine([("2026-06-20 08:00", LN, 95.0, 1000.0, 46.0, 3.0)])
    o = _osp([("2026-06-21 08:00", LN, 90.0, 600.0),
              ("2026-06-21 09:00", LN, 95.0, 400.0)])
    f = piles.label_feasibility(m, o, LN)
    assert f["asked_ton"] == 1000.0 and f["short_ton"] == 600.0
    assert f["short_share"] == pytest.approx(60.0)


def test_attribution_sd_is_zero_when_labels_are_truthful():
    """라벨이 진짜 적재 위치를 가리키면 귀속 오차는 0 이어야 한다."""
    m = _mine([("2026-06-20 08:00", LN, 50.0, 6000.0, 45.0, 3.0)])
    o = _osp([(f"2026-06-2{i} 08:00", LN, 50.0, 500.0) for i in range(1, 9)])
    o["expected_cao"] = 45.0                       # 현행이 쓰는 값 = 실제와 동일
    a = piles.attribution_sd(m, o, LN)
    assert a["overall_sd"] == pytest.approx(0.0, abs=1e-6)
    assert a["same_zone_pct"] == pytest.approx(100.0)


def test_attribution_sd_grows_when_material_comes_from_elsewhere():
    """다른 구역에서 온 물량이 섞이면 귀속 오차가 커진다."""
    m = _mine([("2026-06-20 08:00", LN, 95.0, 4000.0, 49.0, 3.0),
               ("2026-06-20 09:00", LN, 90.0, 500.0, 43.0, 3.0)])
    o = _osp([(f"2026-06-2{i} 08:00", LN, 90.0, 500.0) for i in range(1, 8)])
    o["expected_cao"] = 43.0                       # 현행은 '90번 = 43.0' 이라고 본다
    a = piles.attribution_sd(m, o, LN)
    assert a["overall_sd"] > 0.5, "실제로는 49.0 짜리 95번 물량이 대부분이다"
    assert a["same_zone_pct"] < 100.0


def test_empty_input_returns_empty_not_crash():
    """빈 입력에서 터지지 않는다 (가동 중지 라인·부분 데이터)."""
    empty = _mine([]).assign(datetime=pd.Series(dtype="datetime64[ns]"))
    assert piles.simulate(empty, _osp([]), LN, "near").empty
    assert piles.label_feasibility(empty, _osp([]), LN) == {}
    assert piles.attribution_sd(empty, _osp([]), LN) == {}
