"""야드 CaO 단기 예측 모델 학습·평가 (라인별) [ML-Engineer].

실행:
    python scripts/train_forecast.py

라인별(기존↔45Q, 신설↔CNA) AR / AR+상류 모델을 시계열 CV로 평가한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from config import schema as S
from config.paths import RAW_DIR
from src.data import clean as C
from src.matching import pipeline as P
from src.models import forecast as F

# 사용자 확정 페어링: 기존↔45Q, 신설↔CNA
PAIR = {
    S.LINE_OLD: (S.SHEET_MINE_45Q, "45Q(4-5K)"),
    S.LINE_NEW: (S.SHEET_YARD_CNA, "CNA(6-7K)"),
}


def _yard_series(xls, sheet):
    y = C.clean_yard(pd.read_excel(xls, sheet)).dropna(subset=["datetime"]).copy()
    y["h"] = y["datetime"].dt.floor("1h")
    return y.groupby("h")["cao"].mean().asfreq("1h")


def _osp_hourly(osp_exp, line):
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["datetime"]).copy()
    o["h"] = o["datetime"].dt.floor("1h")
    return o.groupby("h").agg(impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))


def main() -> None:
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)
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

    print(f"목표: 평균 {S.TARGET.cao_mean}±{S.TARGET.tol}, 예측 MAE<0.5")
    print("=" * 78)
    for line, (sheet, alias) in PAIR.items():
        ys = _yard_series(xls, sheet)
        oh = _osp_hourly(osp_exp, line)
        # Time-Lag: 상류 vs 야드 상관 최대
        lag = P.estimate_time_lag(
            oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
            ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}),
            max_lag_hours=24,
        ).best_lag_hours
        feats = F.build_features(ys, oh, lag)
        print(f"[{line} → 야드 {alias}]  (Time-Lag {lag}h)")
        print("  ", F.evaluate(feats, use_upstream=False))
        print("  ", F.evaluate(feats, use_upstream=True))
        print()


if __name__ == "__main__":
    main()
