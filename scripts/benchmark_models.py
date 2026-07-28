"""10개 모델 벤치마크 실행 (라인별 최적 모델 추천) [ML-Engineer].

실행: python scripts/benchmark_models.py
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
from src.models.benchmark import benchmark, recommend
from src.models.forecast import InsufficientDataError

PAIR = {S.LINE_OLD: (S.SHEET_MINE_45Q, "45Q·4-5K"), S.LINE_NEW: (S.SHEET_YARD_CNA, "CNA·6-7K")}


def build_features_for(xls, osp_exp, line, sheet):
    y = C.clean_yard(pd.read_excel(xls, sheet)).dropna(subset=["datetime"]).copy()
    y["h"] = y["datetime"].dt.floor("1h")
    ys = y.groupby("h")["cao"].mean().asfreq("1h")
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["datetime"]).copy()
    o["h"] = o["datetime"].dt.floor("1h")
    oh = o.groupby("h").agg(impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))
    lag = P.estimate_time_lag(
        oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
        ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}), 24
    ).best_lag_hours
    return F.build_features(ys, oh, lag)


def main():
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)
    mine = pd.concat([C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q)),
                      C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q))], ignore_index=True)
    osp = pd.concat([C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
                     C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW)], ignore_index=True)
    osp_exp = P.assign_expected_cao_timeaware(osp, mine)

    for line, (sheet, alias) in PAIR.items():
        feats = build_features_for(xls, osp_exp, line, sheet)
        print("=" * 66)
        print(f"[{line} 라인 → 야드 {alias}]  (목표 MAE<0.5)")
        try:
            bench = benchmark(feats, use_upstream=False, n_splits=5)
        except InsufficientDataError as e:
            # 가동 중지 라인 등 — 지어내지 않고 건너뛴다 (CLAUDE.md §2-1)
            print(f"→ 벤치마크 생략: {e}\n")
            continue
        print(bench[["rank", "model", "MAE", "RMSE", "R2"]].to_string(
            index=False, float_format=lambda x: f"{x:.3f}"))
        print(f"→ 추천 모델: {recommend(bench)}")
        print()


if __name__ == "__main__":
    main()
