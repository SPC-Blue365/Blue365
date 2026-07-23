"""공용 데이터셋 로더 (정제→매칭→라인별 피처) [ML-Engineer].

여러 스크립트(학습·모니터·리포트)가 동일한 피처를 재사용하도록 한 곳에 모은다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import schema as S
from config.paths import RAW_DIR
from src.data import clean as C
from src.matching import pipeline as P
from src.models import forecast as F


@dataclass
class LineData:
    line: str
    alias: str
    yard_series: pd.Series      # 시간별 야드 CaO (asfreq 1h)
    osp_hourly: pd.DataFrame    # index=시간, [impl, ton]
    lag_hours: int
    features: pd.DataFrame      # 예측 피처 프레임


def load_sources(raw_file: str | None = None):
    """원시 엑셀 → (mine, osp_exp, yards dict). 재사용 기본 로더."""
    xls = pd.ExcelFile(RAW_DIR / (raw_file or S.DATA_FILE))
    mine = pd.concat(
        [C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q)),
         C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q))],
        ignore_index=True,
    )
    osp = pd.concat(
        [C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
         C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW)],
        ignore_index=True,
    )
    osp_exp = P.assign_expected_cao_timeaware(osp, mine)
    yards = {ln: C.clean_yard(pd.read_excel(xls, sh)) for ln, (sh, _) in S.YARD_PAIR.items()}
    return mine, osp_exp, yards


def build_line_data(osp_exp, yards, line: str) -> LineData:
    """한 라인의 야드 시계열·OSP집계·Time-Lag·피처를 구성."""
    alias = S.YARD_PAIR[line][1]
    y = yards[line].dropna(subset=["datetime"]).copy()
    y["h"] = y["datetime"].dt.floor("1h")
    ys = y.groupby("h")["cao"].mean().asfreq("1h")
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["datetime"]).copy()
    o["h"] = o["datetime"].dt.floor("1h")
    oh = o.groupby("h").agg(impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))
    lag = P.estimate_time_lag(
        oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
        ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}), 24
    ).best_lag_hours
    feats = F.build_features(ys, oh, lag)
    return LineData(line, alias, ys, oh, lag, feats)


def all_lines(raw_file: str | None = None) -> dict[str, LineData]:
    """모든 라인의 LineData 를 반환."""
    _, osp_exp, yards = load_sources(raw_file)
    return {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}
