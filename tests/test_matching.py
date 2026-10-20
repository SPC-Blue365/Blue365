"""매칭 로직(pipeline.py) 단위 테스트 — 추적 알고리즘 회귀 방지.

검증 대상 규칙(docs/data_schema.md §3~§4):
  - 시간인지 매칭: 인출시각 '이전'의 최근 적재 품위를 부여 (미래 품위 누출 금지)
  - 라인+지점이 모두 일치해야 매칭 (라인 교차 금지)
  - Time-Lag 추정: 지연시킨 상류가 야드와 가장 잘 맞는 지연을 찾음

⚠️ **해상도** — 2026-10-20 부터 기본은 `S.GRADE_RESOLUTION="line"`(라인 더미 혼합)이다(§6-0-28).
   아래 '구역 단위' 테스트들은 **보관용 경로**를 검증하므로 해상도를 명시적으로 바꿔 돌린다.
   기본 경로(라인)는 파일 끝에서 따로 검증한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config import schema as S
from src.matching.pipeline import (
    GRADE_SOURCE,
    SRC_LINE_PILE,
    aggregate_osp_hourly,
    aggregate_yard_hourly,
    assign_expected_cao_timeaware,
    estimate_time_lag,
)


@pytest.fixture
def zone_mode(monkeypatch):
    """구역 단위(보관용) 경로를 검증할 때 쓴다."""
    monkeypatch.setattr(S, "GRADE_RESOLUTION", "zone", raising=False)


def _mine(rows):
    return pd.DataFrame(rows, columns=["date", "line", "zone", "cao", "mgo", "tonnage", "source", "shift"])


def _osp(rows):
    return pd.DataFrame(rows, columns=["datetime", "line", "zone", "withdrawn_ton"])


# --- 시간인지 매칭 ---
def test_timeaware_uses_most_recent_prior_grade(zone_mode):
    """인출 이전의 '가장 최근' 적재 품위를 써야 한다."""
    mine = _mine([
        [pd.Timestamp("2026-06-01"), S.LINE_NEW, 50.0, 44.0, 3.0, 100, "49Q", None],
        [pd.Timestamp("2026-06-05"), S.LINE_NEW, 50.0, 46.0, 3.0, 100, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-06 09:00"), S.LINE_NEW, 50.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["expected_cao"].iloc[0] == 46.0     # 6/1(44.0)이 아니라 6/5(46.0)


def test_timeaware_does_not_leak_future_grade(zone_mode):
    """인출 이후에만 적재 기록이 있으면 그 값을 쓰면 안 된다(미래 누출 금지)."""
    mine = _mine([
        [pd.Timestamp("2026-06-01"), S.LINE_NEW, 50.0, 44.0, 3.0, 100, "49Q", None],
        [pd.Timestamp("2026-06-20"), S.LINE_NEW, 50.0, 48.0, 3.0, 100, "49Q", None],
    ])
    osp = _osp([[pd.Timestamp("2026-06-05 09:00"), S.LINE_NEW, 50.0, 500.0]])
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["expected_cao"].iloc[0] == 44.0     # 미래(6/20, 48.0) 사용 금지


def test_timeaware_does_not_cross_lines(zone_mode):
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
def test_timeaware_assigns_mgo_from_same_source_row(zone_mode):
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


def test_grade_source_marks_substituted_values(zone_mode):
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


# ── 라인 단위 해상도 (기본, §6-0-28) ─────────────────────────────────────────
def test_line_mode_mixes_the_whole_pile_not_the_zone(monkeypatch):
    """기본 해상도는 **라인 더미 전체 혼합**이다 — 인출 구역 번호를 보지 않는다.

    구역 단위를 포기한 결정의 핵심 동작이다(사용자 확정 2026-10-20). 현장이 구역별 재고를
    측정하지 않으므로 그 해상도는 가질 수 없고, 가진 척하면 숫자만 그럴듯해진다.
    """
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_OLD, 0.0)
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_NEW, 0.0)
    mine = _mine([
        ("2026-06-01", S.LINE_OLD, 50.0, 44.0, 2.0, 3000.0, "49Q", "1차"),
        ("2026-06-01", S.LINE_OLD, 90.0, 48.0, 3.0, 1000.0, "49Q", "1차"),
    ])
    mine["datetime"] = pd.to_datetime(mine["date"])
    # 90번에서 뽑았다고 적혀 있지만, 더미 전체(3:1)가 섞여 나온다고 본다
    osp = _osp([("2026-06-05 08:00", S.LINE_OLD, 90.0, 400.0)])
    osp["datetime"] = pd.to_datetime(osp["datetime"])
    out = assign_expected_cao_timeaware(osp, mine)
    got = float(out["expected_cao"].iloc[0])
    assert got == pytest.approx(44.0 * 0.75 + 48.0 * 0.25), \
        "90번 품위(48.0)가 아니라 더미 평균이어야 한다"
    assert out[GRADE_SOURCE].iloc[0] == SRC_LINE_PILE


def test_line_mode_still_never_crosses_lines(monkeypatch):
    """라인 단위로 바꿔도 **다른 라인 더미에서 가져오지 않는다**."""
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_OLD, 0.0)
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_NEW, 0.0)
    mine = _mine([
        ("2026-06-01", S.LINE_OLD, 50.0, 40.0, 2.0, 5000.0, "49Q", "1차"),
        ("2026-06-01", S.LINE_NEW, 50.0, 50.0, 2.0, 5000.0, "49Q", "1차"),
    ])
    mine["datetime"] = pd.to_datetime(mine["date"])
    osp = _osp([("2026-06-05 08:00", S.LINE_OLD, 50.0, 1000.0),
                ("2026-06-05 09:00", S.LINE_NEW, 50.0, 1000.0)])
    osp["datetime"] = pd.to_datetime(osp["datetime"])
    out = assign_expected_cao_timeaware(osp, mine).sort_values("datetime")
    assert float(out["expected_cao"].iloc[0]) == pytest.approx(40.0)
    assert float(out["expected_cao"].iloc[1]) == pytest.approx(50.0)


def test_line_mode_does_not_leak_future_grade(monkeypatch):
    """미래 적재는 쓰지 않는다 — 뽑는 시점에 더미에 **있던 것만** 섞인다.

    ⚠️ 기초 재고를 0 으로 두고 본다. 실제로는 기초 재고(36,000톤)가 압도적이라 그 가정이
       결과를 지배하는데, 여기서 보려는 것은 **적재 순서**가 지켜지는지이기 때문이다.
    """
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_OLD, 0.0)
    monkeypatch.setitem(S.OSP_OPENING_STOCK, S.LINE_NEW, 0.0)
    mine = _mine([
        ("2026-06-01", S.LINE_OLD, 50.0, 44.0, 2.0, 1000.0, "49Q", "1차"),
        ("2026-06-10", S.LINE_OLD, 50.0, 48.0, 3.0, 1000.0, "49Q", "1차"),
    ])
    mine["datetime"] = pd.to_datetime(mine["date"])
    osp = _osp([("2026-06-05 08:00", S.LINE_OLD, 50.0, 500.0)])
    osp["datetime"] = pd.to_datetime(osp["datetime"])
    out = assign_expected_cao_timeaware(osp, mine)
    assert float(out["expected_cao"].iloc[0]) == pytest.approx(44.0), \
        "6/10 적재분(48.0)이 6/5 인출에 섞이면 안 된다"


def test_line_mode_keeps_tonnage_when_pile_runs_dry():
    """더미가 바닥나면 품위는 **미상**으로 두되 물량은 버리지 않는다(§2-1)."""
    from src.matching.pipeline import SRC_NO_ZONE

    mine = _mine([("2026-06-01", S.LINE_OLD, 50.0, 44.0, 2.0, 100.0, "49Q", "1차")])
    mine["datetime"] = pd.to_datetime(mine["date"])
    osp = _osp([("2026-06-05 08:00", S.LINE_OLD, 50.0, 50_000.0)])
    osp["datetime"] = pd.to_datetime(osp["datetime"])
    out = assign_expected_cao_timeaware(osp, mine)
    assert float(out["withdrawn_ton"].sum()) == 50_000.0, "물량은 그대로 남아야 한다"
    assert out[GRADE_SOURCE].iloc[0] in (SRC_LINE_PILE, SRC_NO_ZONE)
    assert out["expected_cao"].notna().all(), "라인 평균으로라도 채워 비우지 않는다"
