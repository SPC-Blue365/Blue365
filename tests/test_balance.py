"""품위 수지 검증(balance.py) 단위 테스트.

검증 대상 규칙(docs/data_schema.md §6-0-12):
  - 물량 결손은 **양방향**으로 보정한 뒤 품위를 판정한다 (한쪽만 보정하면 반대 부호에서 오판)
  - 기말 함의 품위 검사의 민감도(지렛대 = 처리량/기말재고)를 함께 보고한다
  - 합산 물량 결손은 라인 귀속(교차인출)과 무관한 검사다
  - CaO~MgO 상관 기준선은 '구역-일별 평균' 단위여야 한다 (원본 행 단위 아님)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config import schema as S
from src.matching.balance import (
    PLAUSIBLE_GRADE,
    combined_mass_gap,
    component_coherence,
    grade_balance,
)


def _stock(line, pairs):
    return pd.DataFrame([{"datetime": pd.Timestamp(d), "line": line, "stock_ton": t}
                         for d, t in pairs])


def _mine(line, rows):
    """rows = [(날짜, zone, cao, mgo, ton)]"""
    return pd.DataFrame([{"datetime": pd.Timestamp(d), "date": pd.Timestamp(d).floor("D"),
                          "line": line, "zone": z, "cao": c, "mgo": g, "tonnage": t,
                          "source": "49Q"} for d, z, c, g, t in rows])


def _osp(line, rows):
    """rows = [(시각, zone, ton, expected_cao, expected_mgo)]"""
    return pd.DataFrame([{"datetime": pd.Timestamp(d), "line": line, "zone": z,
                          "withdrawn_ton": t, "expected_cao": c, "expected_mgo": g}
                         for d, z, t, c, g in rows])


def _closed_case(line=S.LINE_NEW, cao=46.0, mgo=3.0):
    """물량이 정확히 닫히는 이상적 케이스: 기초 1000 + 적재 2000 − 인출 2000 = 기말 1000.

    ⚠️ 검사 구간은 세 소스가 겹치는 (lo, hi] 이고 lo 는 mine·osp 의 첫 기록이 정한다.
    따라서 06-02 행은 구간 경계라 집계에서 빠진다 — 구간 내 적재/인출은 각각 2,000톤.
    """
    stock = _stock(line, [("2026-06-01", 1000.0), ("2026-06-02", 1000.0),
                          ("2026-06-06", 1000.0), ("2026-06-10", 1000.0)])
    mine = _mine(line, [("2026-06-02", 50.0, cao, mgo, 500.0),      # 경계 — 제외됨
                        ("2026-06-04", 50.0, cao, mgo, 1000.0),
                        ("2026-06-06", 50.0, cao, mgo, 1000.0)])
    osp = _osp(line, [("2026-06-02", 50.0, 500.0, cao, mgo),        # 경계 — 제외됨
                      ("2026-06-04", 50.0, 1000.0, cao, mgo),
                      ("2026-06-06", 50.0, 1000.0, cao, mgo)])
    return stock, mine, osp


def test_closed_balance_reproduces_loading_grade():
    """물량이 닫히고 적재=인출 품위면, 기말 함의 품위는 적재 품위와 같아야 한다."""
    stock, mine, osp = _closed_case()
    r = grade_balance(stock, mine, osp, S.LINE_NEW)
    assert r is not None
    assert abs(r["mass_gap"]) < 1e-6
    assert abs(r["grades"]["cao"]["end_grade"] - 46.0) < 1e-6
    assert abs(r["grades"]["mgo"]["end_grade"] - 3.0) < 1e-6
    assert r["grades"]["cao"]["ok"] and r["grades"]["mgo"]["ok"]


def test_mass_gap_corrected_in_both_directions():
    """적재 초과(gap>0)와 인출 초과(gap<0) 모두 보정돼 함의 품위가 정상 범위에 남는다."""
    for extra_load, extra_draw in ((400.0, 0.0), (0.0, 400.0)):
        stock, mine, osp = _closed_case()
        if extra_load:
            mine = pd.concat([mine, _mine(S.LINE_NEW,
                              [("2026-06-05", 50.0, 46.0, 3.0, extra_load)])], ignore_index=True)
        if extra_draw:
            osp = pd.concat([osp, _osp(S.LINE_NEW,
                             [("2026-06-05", 50.0, extra_draw, 46.0, 3.0)])],
                            ignore_index=True)
        r = grade_balance(stock, mine, osp, S.LINE_NEW)
        assert abs(r["mass_gap"]) == pytest.approx(400.0)
        # 보정 후에는 양쪽 모두 적재 품위로 복원돼야 한다
        assert r["grades"]["cao"]["end_grade"] == pytest.approx(46.0, abs=1e-6)
        assert r["grades"]["cao"]["ok"]


def test_one_directional_correction_would_have_failed():
    """보정을 한쪽만 했다면 gap<0 쪽에서 물리적으로 불가능한 값이 나왔음을 보인다.

    (이 테스트가 양방향 보정의 존재 이유다 — 회귀 방지용)
    """
    stock, mine, osp = _closed_case()
    osp = pd.concat([osp, _osp(S.LINE_NEW,
                     [("2026-06-05", 50.0, 400.0, 46.0, 3.0)])], ignore_index=True)
    r = grade_balance(stock, mine, osp, S.LINE_NEW)
    s0, s1, In, Out = r["s0"], r["s1"], r["loaded"], r["withdrawn"]
    in_g = out_g = 46.0
    naive = (s0 * in_g + In * in_g - Out * out_g) / s1     # 부족분만 보정 = 미보정
    assert not (PLAUSIBLE_GRADE["cao"][0] <= naive <= PLAUSIBLE_GRADE["cao"][1])
    assert r["grades"]["cao"]["ok"]                         # 양방향 보정은 통과


def test_leverage_flags_insensitive_check():
    """기말재고가 처리량보다 훨씬 작으면 지렛대가 크다고 알려야 한다."""
    stock, mine, osp = _closed_case()
    mine.loc[mine["datetime"] > pd.Timestamp("2026-06-02"), "tonnage"] = 25_000.0
    osp.loc[osp["datetime"] > pd.Timestamp("2026-06-02"), "withdrawn_ton"] = 25_000.0
    r = grade_balance(stock, mine, osp, S.LINE_NEW)
    assert r["loaded"] == pytest.approx(50_000.0)
    assert r["s1"] == pytest.approx(1000.0)
    assert r["leverage"] == pytest.approx(50.0)     # 처리량 50,000 ÷ 기말재고 1,000


def test_combined_gap_survives_line_reattribution():
    """인출을 두 라인 사이에서 옮겨도 합산 결손은 변하지 않는다 (교차인출과 무관)."""
    so, mo, bo = _closed_case(S.LINE_OLD)
    sn, mn, bn = _closed_case(S.LINE_NEW)
    stock = pd.concat([so, sn], ignore_index=True)
    mine = pd.concat([mo, mn], ignore_index=True)
    base = pd.concat([bo, bn], ignore_index=True)
    # 신설 인출 400톤을 기존으로 재귀속 — 합산 총량은 그대로다
    inside = base["datetime"] == pd.Timestamp("2026-06-06")
    moved = base.copy()
    moved.loc[inside & (moved["line"] == S.LINE_NEW), "withdrawn_ton"] = 600.0
    moved.loc[inside & (moved["line"] == S.LINE_OLD), "withdrawn_ton"] = 1400.0
    a, b = combined_mass_gap(stock, mine, base), combined_mass_gap(stock, mine, moved)
    assert a["gap"] == pytest.approx(b["gap"])
    assert a["beta"] == pytest.approx(b["beta"])


def test_coherence_baseline_is_zone_daily_not_raw_rows():
    """상관 기준선은 구역-일별 평균이어야 한다 — 원본 행 단위와 다른 값이 나온다."""
    rows = [("2026-06-01", 50.0, 44.0, 4.0, 100.0), ("2026-06-01", 50.0, 48.0, 2.0, 100.0),
            ("2026-06-02", 60.0, 45.0, 1.0, 100.0), ("2026-06-02", 60.0, 47.0, 5.0, 100.0),
            ("2026-06-03", 70.0, 43.0, 2.0, 100.0)]
    mine = _mine(S.LINE_NEW, rows)
    osp = _osp(S.LINE_NEW, [("2026-06-05 09:00", 50.0, 100.0, 46.0, 3.0),
                            ("2026-06-06 09:00", 60.0, 100.0, 46.0, 3.0),
                            ("2026-06-07 09:00", 70.0, 100.0, 43.0, 2.0)])
    r = component_coherence(mine, osp, S.LINE_NEW)
    assert r is not None
    assert not np.isclose(r["raw"], r["ref"])          # 집계 단위가 다르면 값도 다르다
    assert r["drift"] == pytest.approx(r["assigned"] - r["ref"])


def test_returns_none_without_overlapping_window():
    """세 소스가 겹치는 기간이 없으면 억지 수치를 만들지 않는다 (§2-1)."""
    stock = _stock(S.LINE_NEW, [("2026-06-01", 1000.0), ("2026-06-10", 1000.0)])
    mine = _mine(S.LINE_NEW, [("2026-09-03", 50.0, 46.0, 3.0, 1000.0)])
    osp = _osp(S.LINE_NEW, [("2026-09-04 09:00", 50.0, 1000.0, 46.0, 3.0)])
    assert grade_balance(stock, mine, osp, S.LINE_NEW) is None
