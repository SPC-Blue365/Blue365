"""정제 로직(clean.py) 단위 테스트 — 시스템의 핵심 규칙 회귀 방지.

여기 DataFrame 은 로직 검증용 픽스처다(실데이터·분석수치 아님).
검증 대상 규칙(docs/data_schema.md):
  - 복합 구역코드 파싱: "50/55", "55-45", "100-0", "15~35"
  - 이송/인출 물량의 구역 수 균등 배분
  - 야드명 정규화: "신설(Y1)-내수" → "신설(Y1)"
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S
from src.data.clean import (
    clean_mine_49Q,
    clean_osp,
    clean_yard,
    clean_yard_change,
    parse_zone_codes,
)


# --- 복합 구역코드 파싱 ---
def test_parse_single_zone():
    assert parse_zone_codes("50") == [50.0]


def test_parse_multi_delimiters():
    assert parse_zone_codes("50/55") == [50.0, 55.0]
    assert parse_zone_codes("55-45") == [55.0, 45.0]
    assert parse_zone_codes("15~35") == [15.0, 35.0]
    assert parse_zone_codes("100-0") == [100.0, 0.0]


def test_parse_idle_and_nan_return_empty():
    assert parse_zone_codes(S.LINE_IDLE) == []
    assert parse_zone_codes(np.nan) == []
    assert parse_zone_codes("") == []


def test_parse_ignores_non_numeric_tokens():
    # 숫자로 못 바꾸는 토큰은 건너뛴다(값을 지어내지 않음)
    assert parse_zone_codes("50/기타") == [50.0]


# --- 광산 정제: 구역 전개 + 물량 균등 배분 ---
def test_mine_splits_tonnage_equally_across_zones():
    raw = pd.DataFrame({
        "채굴일자": [pd.Timestamp("2026-06-10")],
        "채굴시간(교대)": ["2차"],
        "공정구분": [S.LINE_NEW],
        "OSP적재구역": ["50/60"],
        "CaO품위": [45.0],
        "MgO품위": [3.0],
        "이송물량(톤)": [1000],
    })
    out = clean_mine_49Q(raw)
    assert len(out) == 2                      # 두 구역으로 전개
    assert sorted(out["zone"]) == [50.0, 60.0]
    assert out["tonnage"].tolist() == [500.0, 500.0]   # 균등 배분
    assert out["tonnage"].sum() == 1000.0              # 총량 보존


def test_mine_idle_row_dropped():
    raw = pd.DataFrame({
        "채굴일자": [pd.Timestamp("2026-06-10")], "채굴시간(교대)": ["1차"],
        "공정구분": [S.LINE_IDLE], "OSP적재구역": [S.LINE_IDLE],
        "CaO품위": [np.nan], "MgO품위": [np.nan], "이송물량(톤)": ["-"],
    })
    assert len(clean_mine_49Q(raw)) == 0


def test_mine_handles_dash_tonnage_as_nan():
    raw = pd.DataFrame({
        "채굴일자": [pd.Timestamp("2026-06-10")], "채굴시간(교대)": ["1차"],
        "공정구분": [S.LINE_NEW], "OSP적재구역": ["50"],
        "CaO품위": [45.0], "MgO품위": [3.0], "이송물량(톤)": ["-"],
    })
    out = clean_mine_49Q(raw)
    assert len(out) == 1 and pd.isna(out["tonnage"].iloc[0])


# --- OSP 인출: 지점 균등 배분 ---
def test_osp_splits_withdrawal_equally_between_points():
    raw = pd.DataFrame({
        "일자": [pd.Timestamp("2026-06-10")], "인출시간": ["08:20"],
        "공정구분": [S.LINE_OLD], " P/W1호": [20.0], " P/W2호": [30.0],
        " P/W3호": [np.nan], " P/W4호": [np.nan], "인출량": [800.0], "비고": [np.nan],
    })
    out = clean_osp(raw, S.LINE_OLD, S.PW_COLS_OLD)
    assert len(out) == 2
    assert out["withdrawn_ton"].tolist() == [400.0, 400.0]   # 50%씩 균등
    assert out["datetime"].iloc[0] == pd.Timestamp("2026-06-10 08:20")


def test_osp_single_point_takes_full_amount():
    raw = pd.DataFrame({
        "일자": [pd.Timestamp("2026-06-10")], "인출시간": ["09:00"],
        "공정구분": [S.LINE_OLD], " P/W1호": [50.0], " P/W2호": [np.nan],
        " P/W3호": [np.nan], " P/W4호": [np.nan], "인출량": [600.0], "비고": [np.nan],
    })
    out = clean_osp(raw, S.LINE_OLD, S.PW_COLS_OLD)
    assert len(out) == 1 and out["withdrawn_ton"].iloc[0] == 600.0


# --- 야드 / 야드변경 ---
def test_clean_yard_combines_date_and_time():
    raw = pd.DataFrame({
        "일자": [pd.Timestamp("2026-06-10")], "시간": ["00:02"],
        "Yard": [np.nan], "적재물량(TPH)": [36.0], "CaO": [44.7], "MgO": [3.1],
    })
    out = clean_yard(raw)
    assert out["datetime"].iloc[0] == pd.Timestamp("2026-06-10 00:02")
    assert out["cao"].iloc[0] == 44.7 and out["load"].iloc[0] == 36.0


def test_yard_change_normalizes_yard_name():
    raw = pd.DataFrame({
        "변경일": ["2026-06-03"], "변경시간": ["08:20"], "Yard": ["신설(Y1)-내수"],
        "석회석CaO": [44.06], "석회석MgO": [3.01], "야드물량": [36660],
    })
    out = clean_yard_change(raw, S.LINE_NEW)
    assert out["yard"].iloc[0] == "신설(Y1)"      # '-내수' 제거
    assert out["line"].iloc[0] == S.LINE_NEW
    assert out["tonnage"].iloc[0] == 36660
