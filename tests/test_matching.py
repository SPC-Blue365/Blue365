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


# --- MgO 동시 부여 (2026-08-13 추가) ---
def test_timeaware_assigns_mgo_from_same_source_row():
    """MgO 도 CaO 와 **같은 광산 행**에서 부여돼야 한다 (성분 간 정합)."""
    mine = _mine([
        [pd.Timestamp("2026-06-01"), S.LINE_NEW, 50.0, 44.0, 1.0, 100, "49Q", None],
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 50.0, 46.0, 5.0, 100, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-06 09:00"), S.LINE_NEW, 50.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    # 6/5 행이 선택됐다면 CaO·MgO 가 짝을 이뤄야 한다 (44/1.0 조합이 섞이면 안 됨)
    assert out["expected_cao"].iloc[0] == 46.0
    assert out["expected_mgo"].iloc[0] == 5.0


def test_timeaware_mgo_fallback_leaves_no_gap():
    """이력 없는 지점도 MgO 가 결측으로 남지 않는다 (CaO 와 동일한 fallback)."""
    mine = _mine([[pd.Timestamp("2026-06-01"), S.LINE_NEW, 70.0, 45.0, 2.5, 100, "49Q", None]])
    osp = _osp([
        [pd.Timestamp("2026-06-05 09:00"), S.LINE_NEW, 99.0, 500.0],   # 이력 없는 지점
        [pd.Timestamp("2026-06-05 10:00"), S.LINE_NEW, np.nan, 300.0],  # 지점 결측
    ])
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["expected_mgo"].notna().all()
    assert (out["expected_mgo"] == 2.5).all()
    assert out["withdrawn_ton"].sum() == 800.0     # 물량은 한 톤도 버리지 않는다


def test_zone_daily_grade_is_tonnage_weighted():
    """한 구역·하루에 물량이 크게 다른 적재가 섞이면 **톤 비율대로** 평균해야 한다.

    인출 시 실제로 톤 비율대로 섞여 나오므로, 단순평균은 소량 기록에 과도한 무게를 준다.
    """
    mine = _mine([
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 90.0, 50.0, 3.0, 500, "49Q", None],
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 90.0, 45.0, 3.0, 9500, "47Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-06 09:00"), S.LINE_NEW, 90.0, 100.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    got = float(out["expected_cao"].iloc[0])
    assert abs(got - 45.25) < 1e-6, f"톤가중 45.25 이어야 하는데 {got}"
    assert abs(got - 47.5) > 1.0, "단순평균(47.5)이면 안 된다"


def test_weighted_daily_falls_back_without_tonnage():
    """물량이 0이거나 없으면 단순평균으로 물러서되, 결측을 만들지 않는다."""
    mine = _mine([
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 50.0, 44.0, 2.0, 0, "49Q", None],
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 50.0, 46.0, 4.0, 0, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-06 09:00"), S.LINE_NEW, 50.0, 100.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    assert abs(float(out["expected_cao"].iloc[0]) - 45.0) < 1e-6
    assert abs(float(out["expected_mgo"].iloc[0]) - 3.0) < 1e-6


def test_grade_source_marks_substituted_values():
    """대체값으로 채운 물량은 '실측 기반'과 구별돼야 한다 (가짜 정밀도 방지)."""
    from src.matching.pipeline import (
        GRADE_SOURCE, SRC_LINE_MEAN, SRC_NO_ZONE, SRC_ZONE,
    )
    mine = _mine([[pd.Timestamp("2026-06-05"), S.LINE_NEW, 50.0, 45.0, 2.5, 100, "49Q", None]])
    osp = _osp([
        [pd.Timestamp("2026-06-06 09:00"), S.LINE_NEW, 50.0, 100.0],   # 구역 이력 있음
        [pd.Timestamp("2026-06-06 10:00"), S.LINE_NEW, 99.0, 200.0],   # 이력 없는 구역
        [pd.Timestamp("2026-06-06 11:00"), S.LINE_NEW, np.nan, 300.0],  # 구역 미기재
        [pd.Timestamp("2026-06-01 09:00"), S.LINE_NEW, 50.0, 400.0],   # 적재 이전 인출
    ])
    out = assign_expected_cao_timeaware(osp, mine).set_index("withdrawn_ton")
    assert out.loc[100.0, GRADE_SOURCE] == SRC_ZONE
    assert out.loc[200.0, GRADE_SOURCE] == SRC_LINE_MEAN
    assert out.loc[300.0, GRADE_SOURCE] == SRC_NO_ZONE
    assert out.loc[400.0, GRADE_SOURCE] == SRC_LINE_MEAN    # 이력보다 앞선 인출도 대체값
    # 대체값이라도 품위는 채워져 물량은 보존된다
    assert out["expected_cao"].notna().all()
    assert out.index.to_series().sum() == 1000.0


def test_osp_hourly_carries_mgo():
    """시간창 집계가 MgO 도 톤가중으로 실어 나른다."""
    osp_exp = pd.DataFrame({
        "datetime": [pd.Timestamp("2026-06-01 09:10"), pd.Timestamp("2026-06-01 09:40")],
        "line": [S.LINE_NEW] * 2, "zone": [50.0, 60.0],
        "withdrawn_ton": [300.0, 100.0],
        "expected_cao": [44.0, 48.0], "expected_mgo": [2.0, 6.0],
    })
    out = aggregate_osp_hourly(osp_exp)
    assert abs(out["osp_expected_mgo"].iloc[0] - 3.0) < 1e-9   # (2*300+6*100)/400


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
