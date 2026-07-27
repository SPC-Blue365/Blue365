"""매칭 로직(pipeline.py) 단위 테스트 — 추적 알고리즘 회귀 방지.

검증 대상 규칙(docs/data_schema.md §3~§4):
  - 시간인지 매칭: 인출시각 '이전'의 최근 적재 품위를 부여 (미래 품위 누출 금지)
  - 라인+지점이 모두 일치해야 매칭 (라인 교차 금지)
  - Time-Lag 추정: 지연시킨 상류가 야드와 가장 잘 맞는 지연을 찾음
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S
from src.matching.pipeline import (
    aggregate_osp_hourly,
    aggregate_yard_hourly,
    assign_expected_cao_timeaware,
    estimate_time_lag,
)


def _mine(rows):
    return pd.DataFrame(rows, columns=["date", "line", "zone", "cao", "mgo", "tonnage", "source", "shift"])


def _osp(rows):
    return pd.DataFrame(rows, columns=["datetime", "line", "zone", "withdrawn_ton"])


# --- 시간인지 매칭 ---
def test_timeaware_uses_most_recent_prior_grade():
    """인출 이전의 '가장 최근' 적재 품위를 써야 한다."""
    mine = _mine([
        [pd.Timestamp("2026-06-01"), S.LINE_NEW, 50.0, 44.0, 3.0, 100, "49Q", None],
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 50.0, 46.0, 3.0, 100, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-06 09:00"), S.LINE_NEW, 50.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["expected_cao"].iloc[0] == 46.0     # 6/1(44.0)이 아니라 6/5(46.0)


def test_timeaware_does_not_leak_future_grade():
    """인출 이후에만 적재 기록이 있으면 그 값을 쓰면 안 된다(미래 누출 금지)."""
    mine = _mine([
        [pd.Timestamp("2026-06-01"), S.LINE_NEW, 50.0, 44.0, 3.0, 100, "49Q", None],
        [pd.Timestamp("2026-06-20"), S.LINE_NEW, 50.0, 48.0, 3.0, 100, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-05 09:00"), S.LINE_NEW, 50.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["expected_cao"].iloc[0] == 44.0     # 미래(6/20, 48.0) 사용 금지


def test_timeaware_does_not_cross_lines():
    """다른 라인의 같은 지점 품위를 끌어오면 안 된다 → 라인 전역 평균으로 fallback."""
    mine = _mine([
        [pd.Timestamp("2026-06-01"), S.LINE_OLD, 50.0, 46.0, 3.0, 100, "49Q", None],
        [pd.Timestamp("2026-06-01"), S.LINE_NEW, 70.0, 44.0, 3.0, 100, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-05 09:00"), S.LINE_NEW, 50.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    # 신설 라인에 zone 50 이력이 없으므로 기존(46.0)이 아닌 신설 전역평균(44.0)
    assert out["expected_cao"].iloc[0] == 44.0


def test_timeaware_fallback_when_no_history():
    """이력이 전혀 없는 지점은 라인 평균으로 채우되 결측을 남기지 않는다."""
    mine = _mine([[pd.Timestamp("2026-06-01"), S.LINE_NEW, 70.0, 45.0, 3.0, 100, "49Q", None]])
    osp = _osp([[pd.Timestamp("2026-06-05 09:00"), S.LINE_NEW, 99.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["expected_cao"].notna().all()


# --- 시간창 집계 ---
def test_osp_hourly_is_tonnage_weighted():
    """예상 CaO는 인출톤 가중 평균이어야 한다."""
    df = pd.DataFrame({
        "datetime": [pd.Timestamp("2026-06-10 08:10"), pd.Timestamp("2026-06-10 08:50")],
        "line": [S.LINE_NEW, S.LINE_NEW], "zone": [50.0, 60.0],
        "withdrawn_ton": [300.0, 100.0], "expected_cao": [44.0, 48.0],
    })
    out = aggregate_osp_hourly(df, freq="1h")
    assert len(out) == 1
    # (44*300 + 48*100)/400 = 45.0  (단순평균 46.0 아님)
    assert abs(out["osp_expected_cao"].iloc[0] - 45.0) < 1e-9
    assert out["osp_total_ton"].iloc[0] == 400.0


def test_yard_hourly_aggregates_mean_and_std():
    df = pd.DataFrame({
        "datetime": pd.date_range("2026-06-10 08:00", periods=3, freq="10min"),
        "cao": [44.0, 45.0, 46.0], "mgo": [3.0, 3.0, 3.0], "load": [30.0, 30.0, 30.0],
    })
    out = aggregate_yard_hourly(df, freq="1h")
    assert len(out) == 1
    assert out["yard_cao"].iloc[0] == 45.0
    assert out["yard_n"].iloc[0] == 3


# --- Time-Lag 추정 ---
def test_estimate_time_lag_recovers_known_shift():
    """야드가 상류를 정확히 3시간 뒤따르면 lag=3을 찾아야 한다."""
    idx = pd.date_range("2026-06-10", periods=60, freq="1h")
    signal = np.sin(np.arange(60) / 3.0) + 45.0
    osp_h = pd.DataFrame({"datetime": idx, "osp_expected_cao": signal})
    yard_h = pd.DataFrame({"datetime": idx, "yard_cao": np.roll(signal, 3)})
    res = estimate_time_lag(osp_h, yard_h, max_lag_hours=12)
    assert res.best_lag_hours == 3
    assert res.best_corr > 0.9
