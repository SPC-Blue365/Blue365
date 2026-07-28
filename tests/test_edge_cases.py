"""엣지 케이스 회귀 테스트 (합성 데이터).

기간 설정·가동 중지 라인 때문에 실제로 터졌던 버그들이 다시 나지 않도록 고정한다.
실데이터에 의존하지 않으므로 데이터 없이도 실행 가능하다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import forecast as F
from src.models.benchmark import benchmark
from src.models.dataset import LineData, filter_period
from src.monitoring.monitor import MIN_ROWS, monitor_line


def _features(n: int) -> pd.DataFrame:
    """AR 피처가 채워진 합성 야드 시계열."""
    idx = pd.date_range("2026-07-01", periods=n + 3, freq="1h")
    rng = np.random.default_rng(0)
    ys = pd.Series(44.6 + rng.normal(0, 0.3, len(idx)), index=idx)
    oh = pd.DataFrame({"impl": 44.5, "ton": 100.0}, index=idx)
    return F.build_features(ys, oh, lag_hours=1)


def _line(n: int) -> LineData:
    f = _features(n)
    return LineData("기존", "45Q", f["cao"], pd.DataFrame(), 1, f)


# ── filter_period: 종료일은 '그 날 끝까지' 포함 ──────────────────────────────

def test_filter_period_end_includes_whole_day():
    """end='2026-07-28' 은 07/28 23:00 데이터도 포함해야 한다 (리포트 JS 필터와 동일 규칙)."""
    df = pd.DataFrame({"datetime": pd.date_range("2026-07-27", periods=48, freq="1h")})
    out = filter_period(df, "2026-07-28", "2026-07-28")
    assert len(out) == 24, "종료일 하루치가 모두 포함되어야 한다"
    assert out["datetime"].max().hour == 23


def test_filter_period_end_with_time_is_exact():
    """시각을 명시하면 그 시각까지만 포함한다."""
    df = pd.DataFrame({"datetime": pd.date_range("2026-07-28", periods=24, freq="1h")})
    out = filter_period(df, None, "2026-07-28 05:00")
    assert len(out) == 6


def test_filter_period_empty_result_is_empty_frame():
    df = pd.DataFrame({"datetime": pd.date_range("2026-07-01", periods=5, freq="1h")})
    assert len(filter_period(df, "2026-08-01", "2026-08-05")) == 0


# ── 데이터 부족: 지어내지 않고 명시적으로 거부 (CLAUDE.md §2-1) ──────────────

@pytest.mark.parametrize("n", [0, 5, 15])
def test_fit_final_rejects_insufficient_data(n):
    with pytest.raises(F.InsufficientDataError):
        F.fit_final(_features(n))


@pytest.mark.parametrize("n", [0, 9])
def test_benchmark_rejects_insufficient_data(n):
    with pytest.raises(F.InsufficientDataError):
        benchmark(_features(n))


def test_evaluate_rejects_insufficient_data():
    with pytest.raises(F.InsufficientDataError):
        F.evaluate(_features(8))


def test_insufficient_data_error_is_valueerror():
    """기존 except ValueError 경로와 호환되어야 한다."""
    assert issubclass(F.InsufficientDataError, ValueError)


def test_benchmark_runs_on_small_but_sufficient_data():
    """표본이 작아도 최소 행수를 넘으면 KNN 이웃 수를 낮춰 끝까지 돌아야 한다."""
    out = benchmark(_features(60))
    assert len(out) > 0 and out["MAE"].notna().all()


# ── 모니터: 데이터 부족 라인도 스키마를 지킨다 ────────────────────────────────

def test_monitor_line_insufficient_keeps_series_schema():
    """가동 중지 라인에서도 series['actual'] 접근이 KeyError 를 내면 안 된다."""
    st = monitor_line(_line(3))
    assert list(st.series.columns) == ["datetime", "actual", "pred"]
    assert len(st.series) == 0
    assert st.series["actual"].tolist() == []      # 호출부가 실제로 하는 접근
    assert st.n_monitored == 0
    assert any(a.kind == "data" for a in st.alerts)


def test_monitor_line_insufficient_badge_and_age_text():
    st = monitor_line(_line(3))
    assert st.as_of == "-"
    assert st.age_text == "판정 불가"
    assert st.badge[0] in ("🟢", "🟡", "🔴", "⏸️")


def test_monitor_min_rows_covers_fit_final_requirement():
    """모니터 최소 행수는 학습 분할(80%)이 학습 최소 행수를 넘도록 잡혀야 한다."""
    assert int(MIN_ROWS * 0.8) >= F.MIN_TRAIN_ROWS


def test_monitor_line_works_with_enough_data():
    st = monitor_line(_line(200))
    assert len(st.series) > 0
    assert np.isfinite(st.recent_mae)


# ── 야드 페어링: 정본은 config/schema.YARD_PAIR 하나뿐 ─────────────────────

def test_yard_pairing_matches_user_confirmed_domain_truth():
    """사용자 확정: 기존↔45Q(4-5K 킬른), 신설↔CNA(6-7K 킬른). 뒤바뀌면 안 된다."""
    import config.schema as S
    assert S.YARD_PAIR[S.LINE_OLD][0] == S.SHEET_MINE_45Q
    assert S.YARD_PAIR[S.LINE_NEW][0] == S.SHEET_YARD_CNA


def test_scripts_do_not_redefine_yard_pairing():
    """스크립트가 페어링을 자체 하드코딩하면 정본과 어긋난다(실제로 발생했던 버그)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in (root / "scripts").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "SHEET_YARD_CNA" not in src and "SHEET_MINE_45Q" not in src, (
            f"{path.name} 이 야드 시트를 직접 지정합니다 — S.YARD_PAIR 를 사용하세요."
        )
