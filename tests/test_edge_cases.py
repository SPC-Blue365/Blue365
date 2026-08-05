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


def test_wavg_excludes_blank_grades_from_both_numerator_and_denominator():
    """빈칸 품위는 평균에서 완전히 빠져야 한다 (0으로 계산되면 평균이 끌려 내려감)."""
    from src.visualization.figures import _wavg
    v = pd.Series([45.0, np.nan, 45.0])
    w = pd.Series([100.0, 900.0, 100.0])   # 빈칸 행이 물량의 82%
    assert _wavg(v, w) == pytest.approx(45.0)      # 빈칸=0 이면 8.2 로 폭락
    assert np.isnan(_wavg(pd.Series([np.nan]), pd.Series([10.0])))


def test_sankey_aggregates_ignore_blank_grades():
    """일별 집계의 '성분 유효물량'이 빈칸 행의 물량을 포함하면 안 된다."""
    from src.visualization import figures as V
    mine = pd.DataFrame({
        "date": pd.to_datetime(["2026-07-01"] * 3),
        "datetime": pd.to_datetime(["2026-07-01 12:00"] * 3),
        "source": ["47Q"] * 3, "line": ["기존"] * 3,
        "tonnage": [100.0, 900.0, 100.0],
        "cao": [45.0, np.nan, 45.0],       # 가운데 행이 빈칸
        "mgo": [4.0, 4.0, np.nan],         # MgO 는 빈칸 위치가 다름
    })
    agg = V.sankey_daily_aggregates(mine, None, None, None)
    (day, ton, wc, wtc, wm, wtm), = agg["flow"]["47Q|기존"]
    assert ton == pytest.approx(1100.0)     # 물량은 전부 포함
    assert wtc == pytest.approx(200.0)      # CaO 유효물량은 빈칸 행 제외
    assert wc / wtc == pytest.approx(45.0)
    assert wtm == pytest.approx(1000.0)     # MgO 는 별도 집계 (위치가 다름)
    assert wm / wtm == pytest.approx(4.0)


def test_yard_daily_counts_cao_and_mgo_separately():
    """야드 집계는 성분별 건수를 따로 세야 한다 (45Q는 MgO만 결측)."""
    from src.visualization import figures as V
    yards = {"기존": pd.DataFrame({          # 같은 시각대(01시)에 두 건
        "datetime": pd.to_datetime(["2026-07-01 01:00", "2026-07-01 01:30"]),
        "cao": [45.0, 45.0], "mgo": [3.4, np.nan],
    })}
    (key, nc, sc, nm, sm), = V.sankey_daily_aggregates(None, None, yards, None)["yard_daily"]["기존"]
    assert (nc, sc) == (2, pytest.approx(90.0))
    assert (nm, sm) == (1, pytest.approx(3.4))   # 공통 카운트(2)면 1.7 로 반토막
    assert sm / nm == pytest.approx(3.4)


def test_sankey_aggregate_keys_are_hourly():
    """집계 키는 시간 단위여야 한다 — 야드변경 구간이 42시간부터라 일 단위면 경계가 섞인다."""
    from src.visualization import figures as V
    yards = {"기존": pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-01 01:00", "2026-07-01 05:00"]),
        "cao": [44.0, 46.0], "mgo": [3.0, 3.0],
    })}
    rows = V.sankey_daily_aggregates(None, None, yards, None)["yard_daily"]["기존"]
    keys = [r[0] for r in rows]
    assert keys == ["2026-07-01T01", "2026-07-01T05"], "시간 단위로 분리되어야 한다"
    # 문자열 사전순 비교가 시간순과 일치해야 JS 범위 필터가 성립한다
    assert sorted(keys) == keys
    assert "2026-07-01T05" > "2026-07-01"          # 날짜만 넘어온 시작 경계보다 큼
    assert "2026-07-01T05" < "2026-07-01T99"       # JS 가 붙이는 종료 경계보다 작음


def test_yard_change_aggregate_uses_minute_keys():
    """야드변경은 분 단위 키여야 한다 — 변경 시각이 12:30·19:50 처럼 분 단위이기 때문."""
    from src.visualization import figures as V
    yc = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-24 12:30", "2026-07-26 19:50"]),
        "line": ["신설"] * 2, "yard": ["신설(Y1)", "신설(Y2)"],
        "cao": [45.35, 45.21], "mgo": [3.05, 3.1], "tonnage": [46000.0, 45880.0],
    })
    agg = V.sankey_daily_aggregates(None, None, None, yc)["yc"]
    assert agg["신설|신설(Y1)"][0][0] == "2026-07-24T12:30"
    assert agg["신설|신설(Y2)"][0][0] == "2026-07-26T19:50"


def _yc_fixture():
    yc = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-24 12:30", "2026-07-26 19:50"]),
        "line": ["신설"] * 2, "yard": ["신설(Y1)", "신설(Y2)"],
        "cao": [45.35, 45.21], "mgo": [3.05, 3.1], "tonnage": [46000.0, 45880.0],
    })
    yards = {"신설": pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-27 00:00"]), "cao": [45.0], "mgo": [3.0]})}
    return yc, yards


def test_yc_segment_end_excludes_next_change_event():
    """구간 끝은 '다음 변경 1분 전'이어야 한다.

    끝을 다음 변경 시각으로 두면 그 이벤트의 물량(약 46,000톤)이 통째로 섞여
    구간 물량이 최대 2배로 보인다 — 실제로 발생했던 버그.
    """
    from src.matching.segments import yard_change_segments
    yc, yards = _yc_fixture()
    segs = yard_change_segments(yc, None, None, yards)
    first = segs[0]
    assert first["s"] == "2026-07-24T12"        # 시작은 '시' 내림 → 그 시각대 물류 포함
    assert first["e"] == "2026-07-26T19:49"     # 끝은 다음 변경(19:50) 1분 전 → 배제
    # 문자열 비교로 다음 이벤트가 실제로 빠지는지 확인 (JS 필터와 동일 규칙)
    assert not ("2026-07-26T19:50" >= first["s"] and "2026-07-26T19:50" <= first["e"])
    assert "2026-07-24T12:30" >= first["s"] and "2026-07-24T12:30" <= first["e"]
    # pandas 경계도 배타적이어야 한다 (대시보드는 start/end 로 자른다)
    assert first["end"] == pd.Timestamp("2026-07-26 19:50")
    assert first["start"] == pd.Timestamp("2026-07-24 12:00")


def test_segments_are_defined_per_line():
    """구간에는 항상 라인이 붙어야 한다 — 두 라인의 변경 시점이 다르기 때문."""
    from src.matching.segments import yard_change_segments
    yc, yards = _yc_fixture()
    yc2 = pd.concat([yc, pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-25 09:00"]), "line": ["기존"],
        "yard": ["기존(Y1)"], "cao": [45.0], "mgo": [3.0], "tonnage": [1000.0]})])
    segs = yard_change_segments(yc2, None, None, yards)
    assert {s["line"] for s in segs} == {"신설", "기존"}
    assert all(s["line"] in s["label"] and s["link"].startswith(s["line"]) for s in segs)


def test_flow_aggregate_keys_are_minute_precise():
    """OSP 인출은 분 단위 시각이라 키도 분 단위여야 한다.

    시간 단위로 묶으면 구간 끝에서 최대 59분치가 더 딸려 들어온다
    (신설 06/24 구간에서 9,000톤이 초과 집계됐던 버그).
    """
    from src.visualization import figures as V
    osp = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-06-27 16:10", "2026-06-27 16:40"]),
        "line": ["신설"] * 2, "withdrawn_ton": [1000.0, 9000.0],
    })
    rows = V.sankey_daily_aggregates(None, osp, None, None)["flow"]["__yard__신설"]
    keys = sorted(r[0] for r in rows)
    assert keys == ["2026-06-27T16:10", "2026-06-27T16:40"]
    # 구간 끝이 16:19 면 16:40 건은 빠져야 한다 (JS 사전순 비교와 동일)
    e = "2026-06-27T16:19"
    got = sum(r[1] for r in rows if r[0] <= e)
    assert got == pytest.approx(1000.0), "구간 끝을 넘는 인출이 섞이면 안 된다"


def test_mine_rows_get_real_timestamps_from_shift():
    """광산은 교대 시각으로 시간축에 놓인다 — 더 이상 일 단위가 아니다.

    이전에는 시각이 없어 구간 경계에서 그 날 채굴분이 통째로 사라지거나(최대 48%)
    하루 전체가 들어갔다. 교대 시간대(사용자 확정)로 대표 시각을 부여해 해소.
    """
    from src.data import clean as C
    from src.visualization import figures as V

    # 1차 08~16 → 12:00 · 2차 16~24 → 20:00 · 3차 00~08 → 04:00 (중점)
    assert C.shift_midpoint("2026-06-22", "1차") == pd.Timestamp("2026-06-22 12:00")
    assert C.shift_midpoint("2026-06-22", "2차") == pd.Timestamp("2026-06-22 20:00")
    assert C.shift_midpoint("2026-06-22", "3차") == pd.Timestamp("2026-06-22 04:00")
    assert pd.isna(C.shift_midpoint("2026-06-22", None))
    assert pd.isna(C.shift_midpoint(None, "1차"))

    mine = pd.DataFrame({
        "date": pd.to_datetime(["2026-06-22", "2026-06-22"]),
        "datetime": [C.shift_midpoint("2026-06-22", "1차"), C.shift_midpoint("2026-06-22", "2차")],
        "source": ["49Q"] * 2, "line": ["신설"] * 2,
        "tonnage": [22000.0, 23000.0], "cao": [45.0, 45.0], "mgo": [3.0, 3.0],
    })
    rows = V.sankey_daily_aggregates(mine, None, None, None)["flow"]["49Q|신설"]
    keys = sorted(r[0] for r in rows)
    assert keys == ["2026-06-22T12:00", "2026-06-22T20:00"], "교대별로 다른 시각에 놓여야 한다"
    # 구간이 06/22 16시에 시작하면 1차(12:00)는 빠지고 2차(20:00)만 남는다
    got = sum(r[1] for r in rows if r[0] >= "2026-06-22T16")
    assert got == pytest.approx(23000.0)


def test_handover_only_shifts_midpoint_by_15min():
    """인수인계 30분은 대표 시각을 15분 움직일 뿐 — 제외해도 구간 귀속이 안 바뀐다."""
    from src.data import clean as C
    from config import schema as S

    base = C.shift_midpoint("2026-06-22", "1차", handover=False)
    ho = C.shift_midpoint("2026-06-22", "1차", handover=True)
    assert ho - base == pd.Timedelta(minutes=S.HANDOVER_MINUTES / 2)
    assert S.HANDOVER_APPLIED is False, "검증 결과 귀속 변화 0건이라 제외한다"
    # 기본값(HANDOVER_APPLIED=False)이 실제로 적용되는지
    assert C.shift_midpoint("2026-06-22", "1차") == base


def test_mine_47Q_uses_actual_start_end_times():
    """47Q 는 실측 시작·종료 시각이 있으므로 그 중점을 쓴다."""
    from src.data import clean as C
    assert C._time_midpoint("2026-06-22", __import__("datetime").time(8, 30),
                            __import__("datetime").time(9, 30)) == pd.Timestamp("2026-06-22 09:00")
    # 자정을 넘기면 하루를 더해 계산
    assert C._time_midpoint("2026-06-22", __import__("datetime").time(23, 0),
                            __import__("datetime").time(1, 0)) == pd.Timestamp("2026-06-23 00:00")


def _inv_fixture():
    mine = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-01 12:00", "2026-07-02 12:00", "2026-07-03 12:00"]),
        "line": ["신설"] * 3, "tonnage": [100.0, 200.0, 300.0],
    })
    osp = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-07-01 08:00", "2026-07-02 08:00", "2026-07-03 08:00"]),
        "line": ["신설"] * 3, "withdrawn_ton": [50.0, 400.0, 100.0],
    })
    return mine, osp


def test_inventory_series_is_cumulative_net():
    """재고 = 누적(적재 − 인출). 마지막 값은 전체 적재 − 전체 인출과 같아야 한다."""
    from src.visualization import figures as V
    mine, osp = _inv_fixture()
    idx, cum, inflow, outflow = V.inventory_series(mine, osp, "신설")
    assert list(cum.values) == pytest.approx([50.0, -150.0, 50.0])   # +50, -200, +200
    assert cum.iloc[-1] == pytest.approx(600.0 - 550.0)
    assert inflow.sum() == pytest.approx(600.0)
    assert outflow.sum() == pytest.approx(550.0)


def test_inventory_series_filters_by_line():
    """다른 라인의 물량이 섞이면 안 된다 (OSP 는 라인별로 별개다)."""
    from src.visualization import figures as V
    mine, osp = _inv_fixture()
    mine2 = pd.concat([mine, mine.assign(line="기존", tonnage=9999.0)])
    idx, cum, inflow, _ = V.inventory_series(mine2, osp, "신설")
    assert inflow.sum() == pytest.approx(600.0), "기존 라인 물량이 섞였다"


def test_inventory_series_missing_tonnage_is_not_counted():
    """결측 물량은 0 으로 더해질 뿐, 총량을 부풀리면 안 된다."""
    from src.visualization import figures as V
    mine, osp = _inv_fixture()
    mine.loc[0, "tonnage"] = np.nan
    _, _, inflow, _ = V.inventory_series(mine, osp, "신설")
    assert inflow.sum() == pytest.approx(500.0)


@pytest.mark.parametrize("m,o", [(None, None), ("empty", "empty"), (None, "keep")])
def test_inventory_trend_survives_missing_data(m, o):
    """데이터가 없거나 한쪽만 있어도 예외 없이 그려져야 한다 (가동 중지 라인)."""
    from src.visualization import figures as V
    mine, osp = _inv_fixture()
    mm = None if m is None else (mine.iloc[0:0] if m == "empty" else mine)
    oo = None if o is None else (osp.iloc[0:0] if o == "empty" else osp)
    fig = V.inventory_trend(mm, oo)
    assert fig is not None


def test_inventory_trend_labels_are_not_color_only():
    """계열이 2개이므로 범례 + 직접 라벨이 있어야 한다 (색만으로 구분 금지)."""
    from src.visualization import figures as V
    mine, osp = _inv_fixture()
    mine2 = pd.concat([mine, mine.assign(line="기존")])
    osp2 = pd.concat([osp, osp.assign(line="기존")])
    fig = V.inventory_trend(mine2, osp2)
    assert len(fig.data) == 2
    assert all(t.name for t in fig.data), "범례 이름이 있어야 한다"
    ann = [a.text for a in fig.layout.annotations]
    assert any("기존" in t for t in ann) and any("신설" in t for t in ann)


def test_monitor_series_is_only_a_recent_window():
    """모니터 series 는 경보용 '최근 감시창'이다 — 관리도가 이걸 쓰면 x축이 잘린다.

    실제로 신설 관리도가 전체 49일 중 최근 8일(16%)만 보이던 버그의 원인.
    관리도·KPI 는 LineData.yard_series(기간 전체)를 써야 한다.
    """
    ld = _line(200)
    st = monitor_line(ld)
    assert len(st.series) < len(ld.yard_series.dropna()), "series 는 일부 구간만 담는다"
    # 관리도가 써야 할 전체 시계열은 훨씬 길다
    assert len(ld.yard_series) >= 200


def test_control_chart_source_covers_full_period():
    """관리도에 넘기는 시계열은 야드 데이터 전 구간을 덮어야 한다."""
    ld = _line(200)
    ys = ld.yard_series
    st = monitor_line(ld)
    assert ys.index.min() <= st.series["datetime"].min()
    assert ys.index.max() >= st.series["datetime"].max()
    # 관리도가 실제로 그 시계열로 그려지는지 (예외 없이)
    from src.visualization import figures as V
    fig = V.control_chart(ys.index, ys.values, 44.1, 45.1, "t")
    xs = fig.data[0].x
    assert pd.Timestamp(xs[0]) == ys.index.min() and pd.Timestamp(xs[-1]) == ys.index.max()


# ── 물량 보존: 구역코드가 없어도 물량을 버리지 않는다 ────────────────────────

def test_mine_rows_without_zone_keep_their_tonnage():
    """구역코드가 비어도 물량이 있으면 살려야 한다 (실제로 10,337톤이 사라졌던 버그)."""
    from src.data.clean import clean_mine_49Q
    df = pd.DataFrame({
        "채굴일자": pd.to_datetime(["2026-07-21", "2026-07-21"]),
        "채굴시간(교대)": ["3차", "1차"],
        "공정구분": ["신설", "운휴"],
        "OSP적재구역": [None, "운휴"],          # 둘 다 구역코드 없음
        "CaO품위": [41.30, 43.0], "MgO품위": [1.38, 2.0],
        "이송물량(톤)": [3294, "-"],            # 앞은 실물량, 뒤는 운휴(물량 없음)
    })
    out = clean_mine_49Q(df)
    assert len(out) == 1, "물량 있는 행은 살고, 운휴 행만 빠져야 한다"
    assert out["tonnage"].sum() == pytest.approx(3294.0)
    assert pd.isna(out["zone"].iloc[0])          # 구역은 모르는 채로 둔다
    assert out["cao"].iloc[0] == pytest.approx(41.30)


def test_osp_rows_without_withdrawal_point_keep_tonnage():
    """인출지점(P/W)이 비어도 인출량이 있으면 살려야 한다 (2,000톤이 사라졌던 버그)."""
    from src.data.clean import clean_osp
    df = pd.DataFrame({
        "일자": pd.to_datetime(["2026-06-11", "2026-06-11"]),
        "인출시간": ["13:00:00", "16:00:00"],
        " P/W3호": [None, 55.0], " P/W4호": [None, 50.0],
        "인출량": [2000.0, 4800.0],
        "비고": ["Yard 변경 1Y 잔량:2,000", None],
    })
    out = clean_osp(df, "신설", [" P/W3호", " P/W4호"])
    assert out["withdrawn_ton"].sum() == pytest.approx(6800.0)
    assert pd.isna(out.loc[out["zone"].isna(), "withdrawn_ton"]).sum() == 0


def test_matching_keeps_zone_less_withdrawals():
    """지점 없는 인출도 매칭 단계에서 사라지면 안 된다(품위만 라인평균으로 대체)."""
    from src.matching.pipeline import assign_expected_cao_timeaware
    osp = pd.DataFrame({
        "datetime": pd.to_datetime(["2026-06-11 13:00", "2026-06-11 16:00"]),
        "line": ["신설"] * 2, "zone": [np.nan, 55.0], "withdrawn_ton": [2000.0, 4800.0],
    })
    mine = pd.DataFrame({
        "date": pd.to_datetime(["2026-06-10"]), "line": ["신설"],
        "zone": [55.0], "cao": [45.0],
    })
    out = assign_expected_cao_timeaware(osp, mine)
    assert out["withdrawn_ton"].sum() == pytest.approx(6800.0), "인출 물량이 보존돼야 한다"
    assert out["expected_cao"].notna().all(), "지점 없는 행도 라인평균으로 채워진다"


# ── OSP 실사 재고 ────────────────────────────────────────────────────────────

def _stock_raw():
    """'OSP 재고' 시트 원시 배치 재현 — 좌우 2블록, 헤더 3번째 행, 가운데 빈 열."""
    rows = [
        [None] * 9,
        ["OSP1", None, None, None, None, "OSP2", None, None, None],
        ["날짜", "차수", "OSP 구분", "재고량", None, "날짜", "차수", "OSP 구분", "재고량"],
        ["2026-07-01", 3, "OSP1", 30000, None, "2026-07-01", 3, "OSP2", 25000],
        ["2026-07-01", 1, "OSP1", 31000, None, "2026-07-01", 1, "OSP2", 26000],
        ["2026-07-01", 2, "OSP1", 32000, None, "2026-07-01", 2, "OSP2", 27000],
        ["2026-07-02", 3, "OSP1", 33000, None, None, None, None, None],
        ["2026-07-02", 3, "OSP1", 34000, None, None, None, None, None],   # 중복(같은 날짜·차수)
    ]
    return pd.DataFrame(rows)


def test_osp_stock_parses_both_blocks_and_maps_lines():
    """OSP1→기존, OSP2→신설 로 매핑되고 좌우 블록이 모두 읽혀야 한다."""
    from src.data.clean import clean_osp_stock
    d = clean_osp_stock(_stock_raw())
    assert set(d["line"]) == {"기존", "신설"}
    assert (d[d["line"] == "신설"]["stock_ton"].tolist()) == [25000.0, 26000.0, 27000.0]


def test_osp_stock_uses_stocktake_times_not_shift_midpoints():
    """실사 시각은 교대 중간 파악시간(1차 12:30·2차 20:30·3차 04:30)이다.

    채굴 교대 중점(12:00/20:00/04:00)과 혼동하면 안 된다.
    """
    from src.data.clean import clean_osp_stock
    d = clean_osp_stock(_stock_raw())
    g = d[(d["line"] == "기존") & (d["date"] == pd.Timestamp("2026-07-01"))]
    times = dict(zip(g["shift"], g["datetime"].dt.strftime("%H:%M")))
    assert times == {3: "04:30", 1: "12:30", 2: "20:30"}


def test_osp_stock_keeps_last_of_duplicate_and_reports_count():
    """같은 (라인·날짜·차수) 중복은 마지막 값을 채택하고 몇 건인지 남긴다."""
    from src.data.clean import clean_osp_stock
    d = clean_osp_stock(_stock_raw())
    dup = d[(d["line"] == "기존") & (d["date"] == pd.Timestamp("2026-07-02"))]
    assert len(dup) == 1 and dup["stock_ton"].iloc[0] == 34000.0   # 마지막 기록
    assert d.attrs["dup_dropped"] == 1


def test_osp_stock_shifts_are_chronological_within_a_day():
    """하루 안에서 3차(04:30) → 1차(12:30) → 2차(20:30) 순서여야 한다."""
    from src.data.clean import clean_osp_stock
    d = clean_osp_stock(_stock_raw())
    g = d[(d["line"] == "기존") & (d["date"] == pd.Timestamp("2026-07-01"))].sort_values("datetime")
    assert g["shift"].tolist() == [3, 1, 2]


def test_stock_vs_flow_reports_gap_without_picking_a_side():
    """실사와 흐름계산을 둘 다 돌려주고 격차를 계산한다 (한쪽으로 단정하지 않음)."""
    from src.data.clean import clean_osp_stock
    from src.models.dataset import stock_vs_flow
    stock = clean_osp_stock(_stock_raw())
    # 흐름 데이터가 실사 구간을 덮어야 대조가 성립한다
    span = ["2026-07-01 00:00", "2026-07-01 12:00", "2026-07-02 23:00"]
    mine = pd.DataFrame({"datetime": pd.to_datetime(span),
                         "line": ["기존"] * 3, "tonnage": [0.0, 1000.0, 0.0]})
    osp = pd.DataFrame({"datetime": pd.to_datetime(["2026-07-01 00:00", "2026-07-01 13:00",
                                                    "2026-07-02 23:00"]),
                        "line": ["기존"] * 3, "withdrawn_ton": [0.0, 500.0, 0.0]})
    r = stock_vs_flow(stock, mine, osp, "기존")
    assert r["calc"] == pytest.approx(500.0)          # 적재 1000 − 인출 500
    assert r["actual"] == pytest.approx(r["s1"] - r["s0"])
    assert r["gap"] == pytest.approx(r["actual"] - r["calc"])
    assert r["s0"] == 30000.0 and r["s1"] == 34000.0  # 첫·마지막 실사값


def test_stock_vs_flow_returns_empty_when_no_overlap():
    """흐름 데이터가 실사 구간과 안 겹치면 억지로 값을 만들지 않는다."""
    from src.data.clean import clean_osp_stock
    from src.models.dataset import stock_vs_flow
    stock = clean_osp_stock(_stock_raw())
    far = pd.DataFrame({"datetime": pd.to_datetime(["2026-09-01 12:00"]),
                        "line": ["기존"], "tonnage": [100.0], "withdrawn_ton": [50.0]})
    assert stock_vs_flow(stock, far, far, "기존") == {}
    assert stock_vs_flow(pd.DataFrame(), far, far, "기존") == {}


def test_calibration_rejects_implausible_coefficients():
    """육안 노이즈 때문에 나오는 비현실적 배율(α=0.28 등)은 채택하지 않는다.

    '기록의 1/4만 실제'라는 뜻이 되어 현장 지식과 배치되므로 ±30% 밖은 거른다.
    """
    from src.models.dataset import calibrate_flow
    # 재고가 흐름과 무관하게 요동 → 회귀가 계수를 0 쪽으로 끌어내린다
    idx = pd.date_range("2026-07-01 04:30", periods=12, freq="8h")
    stock = pd.DataFrame({"datetime": idx, "line": ["신설"] * 12,
                          "stock_ton": [30000, 31000, 29000, 30000, 31000, 29000,
                                        30000, 31000, 29000, 30000, 31000, 29000]})
    mine = pd.DataFrame({"datetime": idx, "line": ["신설"] * 12, "tonnage": [5000.0] * 12})
    osp = pd.DataFrame({"datetime": idx, "line": ["신설"] * 12, "withdrawn_ton": [5000.0] * 12})
    cal = calibrate_flow(stock, mine, osp, "신설")
    if cal:
        assert 0.7 <= cal["coef"] <= 1.3 or cal["method"] == "하루당 가산", \
            f"비현실적 배율이 채택됐다: {cal}"


def test_calibration_reports_eyeball_noise_floor():
    """보정으로 줄일 수 없는 하한(육안 실사 흔들림)을 함께 보고해야 한다."""
    from src.models.dataset import calibrate_flow
    idx = pd.date_range("2026-07-01 04:30", periods=20, freq="8h")
    stock = pd.DataFrame({"datetime": idx, "line": ["신설"] * 20,
                          "stock_ton": 30000 + np.tile([0, 2000, -2000, 1000], 5)})
    mine = pd.DataFrame({"datetime": idx, "line": ["신설"] * 20, "tonnage": [5000.0] * 20})
    osp = pd.DataFrame({"datetime": idx, "line": ["신설"] * 20, "withdrawn_ton": [5000.0] * 20})
    cal = calibrate_flow(stock, mine, osp, "신설")
    assert cal and cal["noise_std"] > 0, "교대 간 흔들림을 노이즈 하한으로 보고해야 한다"


def test_calibration_needs_enough_stocktakes():
    """실사가 5회 미만이면 보정하지 않는다 (억지로 맞추지 않는다)."""
    from src.models.dataset import calibrate_flow
    idx = pd.date_range("2026-07-01 04:30", periods=3, freq="8h")
    stock = pd.DataFrame({"datetime": idx, "line": ["신설"] * 3, "stock_ton": [30000, 31000, 29000]})
    mine = pd.DataFrame({"datetime": idx, "line": ["신설"] * 3, "tonnage": [5000.0] * 3})
    osp = pd.DataFrame({"datetime": idx, "line": ["신설"] * 3, "withdrawn_ton": [5000.0] * 3})
    assert calibrate_flow(stock, mine, osp, "신설") == {}


def test_calibration_windows_detect_a_real_drift():
    """구간별 β 추정이 계량기 지시 변화를 잡아내야 한다 (벨트스케일 교정 판단용)."""
    from src.models.dataset import calibration_windows
    # 30일 · 8시간마다 실사. 인출은 매번 1,000t 지시, 적재 1,000t.
    # 앞 15일은 지시가 정확(β=1.0), 뒤 15일은 10% 과대 지시(β=0.9)로 만든다.
    idx = pd.date_range("2026-07-01 04:30", periods=90, freq="8h")
    inflow, shown = 1000.0, 1000.0
    stock, s = [], 30000.0
    for i in range(len(idx)):
        real_out = shown if i < 45 else shown * 0.9      # 실제 인출은 뒤에서 더 적음
        s += inflow - real_out
        stock.append(s)
    st = pd.DataFrame({"datetime": idx, "line": ["신설"] * len(idx), "stock_ton": stock})
    mine = pd.DataFrame({"datetime": idx, "line": ["신설"] * len(idx),
                         "tonnage": [inflow] * len(idx)})
    osp = pd.DataFrame({"datetime": idx, "line": ["신설"] * len(idx),
                        "withdrawn_ton": [shown] * len(idx)})
    ws = calibration_windows(st, mine, osp, "신설", window_days=10)
    assert len(ws) >= 3
    assert ws[0]["beta"] > ws[-1]["beta"], "뒤로 갈수록 β가 낮아져야 한다(과대 지시 시작)"
    assert all(w["se"] >= 0 for w in ws)


def test_calibration_drift_chart_handles_empty():
    from src.visualization import figures as V
    assert V.calibration_drift({}) is not None
    assert V.calibration_drift({"신설": []}) is not None


def test_stock_trend_survives_empty_inputs():
    from src.visualization import figures as V
    assert V.stock_trend(pd.DataFrame(), None, None) is not None
    assert V.stock_trend(None, None, None) is not None


def test_segment_logic_is_not_duplicated():
    """구간 정의는 src/matching/segments.py 하나뿐이어야 한다 (페어링 버그의 재발 방지)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in list((root / "scripts").glob("*.py")) + [root / "streamlit_app.py"]:
        src = path.read_text(encoding="utf-8")
        assert "def yard_change_segments" not in src and "def _yc_segments" not in src, (
            f"{path.name} 이 구간 정의를 자체 구현합니다 — src.matching.segments 를 쓰세요."
        )


def test_scripts_do_not_redefine_yard_pairing():
    """스크립트가 페어링을 자체 하드코딩하면 정본과 어긋난다(실제로 발생했던 버그)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in (root / "scripts").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "SHEET_YARD_CNA" not in src and "SHEET_MINE_45Q" not in src, (
            f"{path.name} 이 야드 시트를 직접 지정합니다 — S.YARD_PAIR 를 사용하세요."
        )


def test_calibration_window_rejects_unidentifiable_beta():
    """라인이 멈춰 인출이 거의 없는 구간은 β 를 식별할 수 없다 → ok=False 로 표시한다.

    2026-08-05 갱신본에서 기존 라인 마지막 창이 β=6.98 로 나온 실제 사례.
    이런 값을 계량 배율로 보고하면 안 된다(CLAUDE.md §2-1).
    """
    import numpy as np
    import pandas as pd

    from src.models.dataset import MIN_WINDOW_TON, PLAUSIBLE, calibration_windows

    t = pd.date_range("2026-06-01", periods=30, freq="8h")
    # 재고는 계속 줄지만 인출 기록은 거의 없다 → 분모가 0에 가까워 β 가 튄다
    st = pd.DataFrame({"datetime": t, "line": "신설",
                       "stock_ton": np.linspace(50_000, 20_000, len(t))})
    mine = pd.DataFrame({"datetime": t, "line": "신설", "tonnage": 0.0})
    osp = pd.DataFrame({"datetime": t, "line": "신설", "withdrawn_ton": 1.0})

    ws = calibration_windows(st, mine, osp, "신설", window_days=5)
    assert ws, "구간 자체는 생성되어야 한다 (조용히 사라지면 안 됨)"
    assert all(not w["ok"] for w in ws), "식별 불가 구간은 전부 ok=False 여야 한다"
    assert all(w["reason"] for w in ws), "제외 사유가 반드시 남아야 한다"
    assert all(w["beta"] > PLAUSIBLE[1] or w["reason"].startswith("인출") for w in ws)
    assert MIN_WINDOW_TON > 0


def test_zone_codes_split_on_comma():
    """2026-08-05 갱신본에서 처음 등장한 쉼표 표기가 구역을 잃지 않아야 한다."""
    from src.data.clean import parse_zone_codes

    assert parse_zone_codes("25~30, 65~40") == [25.0, 30.0, 65.0, 40.0]
    assert parse_zone_codes("35~60, 75~85") == [35.0, 60.0, 75.0, 85.0]
    # 기존 표기는 그대로 동작해야 한다 (회귀 방지)
    assert parse_zone_codes("50/55") == [50.0, 55.0]
    assert parse_zone_codes("100-0") == [100.0, 0.0]
    assert parse_zone_codes("운휴") == []


def _ovr_raw():
    """정정 규칙 대조용 최소 원본 프레임 (시각·라인만 다루므로 품위는 임의값 아님 — None)."""
    import pandas as pd
    return pd.DataFrame([
        # 규칙에 걸리는 행 / 걸리지 않는 행을 함께 둔다
        {"채굴일자": pd.Timestamp("2026-07-27"), "시작시간": "08:40:00", "종료시간": "16:00:00",
         "OSP적재구역": "100", "공정구분": "기존", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 6379.0},
        {"채굴일자": pd.Timestamp("2026-07-27"), "시작시간": "16:00:00", "종료시간": "18:00:00",
         "OSP적재구역": "100", "공정구분": "신설", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 1017.6},
    ])


def test_line_override_flips_only_the_listed_block():
    """사용자 확정 라인 귀속 정정은 해당 블록의 라인만 바꾸고 물량은 건드리지 않는다."""
    from config import schema as S
    from src.data.clean import clean_mine_47Q

    raw = _ovr_raw()
    out = clean_mine_47Q(raw)
    before = float(raw["이송물량(톤)"].sum())

    assert abs(float(out["tonnage"].sum()) - before) < 1e-6, "정정이 물량을 바꾸면 안 된다"
    got = out.groupby("line")["tonnage"].sum().to_dict()
    # 07/27 08:40~16:00 은 규칙에 따라 기존 → 신설 로 바뀐다
    assert got.get(S.LINE_OLD, 0.0) == 0.0
    assert abs(got[S.LINE_NEW] - before) < 1e-6
    assert out.attrs.get("line_overrides_applied") == 1


def test_line_override_warns_when_rule_matches_nothing():
    """원본이 바뀌어 규칙이 안 맞으면 조용히 넘어가지 않고 경고한다 (§2-1)."""
    import warnings as _w

    import pandas as pd

    from src.data.clean import clean_mine_47Q

    raw = pd.DataFrame([{  # 규칙 날짜와 무관한 행만 담는다
        "채굴일자": pd.Timestamp("2026-06-01"), "시작시간": "08:00:00", "종료시간": "16:00:00",
        "OSP적재구역": "50", "공정구분": "신설", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 100.0,
    }])
    with _w.catch_warnings(record=True) as rec:
        _w.simplefilter("always")
        out = clean_mine_47Q(raw)
    msgs = [str(x.message) for x in rec if "라인 귀속 정정" in str(x.message)]
    assert msgs, "규칙이 하나도 안 맞으면 반드시 경고해야 한다"
    assert out.attrs.get("line_overrides_applied", 0) == 0


def test_line_override_does_not_touch_49Q():
    """정정은 47Q 에만 적용된다 — 49Q 는 원본 라인을 그대로 유지."""
    import pandas as pd

    from config import schema as S
    from src.data.clean import clean_mine_49Q

    raw = pd.DataFrame([{
        "채굴일자": pd.Timestamp("2026-07-27"), "채굴시간(교대)": "1차",
        "OSP적재구역": "50", "공정구분": "기존", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 500.0,
    }])
    out = clean_mine_49Q(raw)
    assert out["line"].tolist() == [S.LINE_OLD]


def test_composite_line_labels_are_split_not_dropped():
    """복합 `공정구분`("운휴/기존","기존/신설")이 라인별 집계에서 빠지면 안 된다.

    2026-08-05 실측: 이 결함으로 7행 21,065톤(광산 총량 1.7%)이 조용히 사라지고 있었다.
    """
    import pandas as pd

    from config import schema as S
    from src.data.clean import clean_mine_49Q, split_line_label

    assert split_line_label("기존") == [S.LINE_OLD]
    assert split_line_label("운휴/기존") == [S.LINE_OLD]      # 운휴는 실물량 없음 → 기존으로
    assert split_line_label("운휴/신설") == [S.LINE_NEW]
    assert split_line_label("기존/신설") == [S.LINE_OLD, S.LINE_NEW]   # 균등 배분 대상
    assert split_line_label("운휴") == []                      # 전부 운휴 → 행 제외
    assert split_line_label(None) == []

    raw = pd.DataFrame([
        {"채굴일자": pd.Timestamp("2026-07-02"), "채굴시간(교대)": "2차", "OSP적재구역": "45/70",
         "공정구분": "기존/신설", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 5762.0},
        {"채굴일자": pd.Timestamp("2026-06-25"), "채굴시간(교대)": "1차", "OSP적재구역": "55",
         "공정구분": "운휴/기존", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 1891.0},
    ])
    out = clean_mine_49Q(raw)
    assert set(out["line"]) <= {S.LINE_OLD, S.LINE_NEW}, "미상 라벨이 남으면 집계에서 빠진다"
    assert abs(float(out["tonnage"].sum()) - 7653.0) < 1e-6, "물량 총합이 보존돼야 한다"
    by = out.groupby("line")["tonnage"].sum()
    assert abs(by[S.LINE_OLD] - (5762.0 / 2 + 1891.0)) < 1e-6   # 균등배분 + 운휴/기존 전량
    assert abs(by[S.LINE_NEW] - 5762.0 / 2) < 1e-6


def test_validation_flags_unknown_line_label():
    """알 수 없는 라인 라벨은 물량과 함께 ERROR 로 보고된다 (조용히 빠지지 않게)."""
    import pandas as pd

    from src.data import validation as V

    mine = pd.DataFrame({
        "date": pd.to_datetime(["2026-07-01"]), "line": ["미상라인"], "zone": [50.0],
        "cao": [45.0], "tonnage": [1234.0],
    })
    rep = V.validate_pipeline(mine, None, {})["광산"]
    hits = [i for i in rep.issues if i.check == "line_unknown"]
    assert hits, "미상 라인 라벨을 반드시 보고해야 한다"
    assert "1,234" in hits[0].message


def test_active_ratio_reflects_half_idle_shift():
    """'운휴/기존' 은 교대의 절반만 가동 → 시간당 환산에 쓸 비율이 0.5 여야 한다.

    물량은 전량 실제 라인 것이고(운휴는 생산 없음), 바뀌는 것은 **가동 시간**뿐이다.
    (2026-08-05 사용자 확정. 생산능력 C/R 상한 감사에 쓰인다.)
    """
    import pandas as pd

    from config import schema as S
    from src.data.clean import active_ratio, clean_mine_49Q

    assert active_ratio("기존") == 1.0
    assert active_ratio("기존/신설") == 1.0          # 둘 다 가동 — 운휴 없음
    assert active_ratio("운휴/기존") == S.IDLE_ACTIVE_RATIO
    assert active_ratio("운휴/신설") == S.IDLE_ACTIVE_RATIO
    assert active_ratio(None) == 0.0

    raw = pd.DataFrame([{
        "채굴일자": pd.Timestamp("2026-06-25"), "채굴시간(교대)": "1차", "OSP적재구역": "55",
        "공정구분": "운휴/기존", "CaO품위": None, "MgO품위": None, "이송물량(톤)": 1891.0,
    }])
    out = clean_mine_49Q(raw)
    assert float(out["tonnage"].sum()) == 1891.0        # 물량은 그대로
    assert set(out["active_ratio"]) == {0.5}
    # 8시간 교대의 절반 가동 → 시간당 환산이 능력 상한(G/C 1,600 t/h) 안에 들어와야 한다
    tph = 1891.0 / (8 * 0.5)
    assert tph <= S.CRUSHER_CAPACITY_TPH["G/C"][1]


def test_crusher_capacity_spec_is_not_additive():
    """동시 가동(G/C+H/C)은 처리량이 가산되지 않는다 — 하류 병목 때문(사용자 확정)."""
    from config import schema as S

    gc = S.CRUSHER_CAPACITY_TPH["G/C"]
    hc = S.CRUSHER_CAPACITY_TPH["H/C"]
    both = S.CRUSHER_CAPACITY_TPH["G/C+H/C"]
    assert both == gc, "동시 가동 능력은 G/C 단독과 같다"
    assert both[1] < gc[1] + hc[1], "가산으로 모델링하면 안 된다"
    assert S.COL_CRUSHER == "C/R"
