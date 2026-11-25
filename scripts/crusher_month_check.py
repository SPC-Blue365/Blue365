"""월별 크러셔(C/R) 구성·광산 품위 ↔ 신설 야드 고품위 비율 대조 [Data-Analyst].

질문 (2026-11-25): "7~10월 고품위(암석) 비율이 50% 이상인데 H/C 위주로 작업했나? 다른 이유는?"
  · 광산 49Q `C/R(생산방법)` 별 이송 물량 비중·물량 가중 CaO (신설 라인)
  · 광산(49Q+47Q) 월 물량 가중 CaO
  · 신설 야드 완료 파일(완료 월 기준)의 고품위(>45.1) 원측정 비율 평균
실행: python scripts/crusher_month_check.py [--start 2026-06-01]
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import schema as S                                   # noqa: E402
from src.data import clean as C                                  # noqa: E402
from src.models.dataset import RAW_DIR, load_sources, load_yard_change  # noqa: E402
from src.visualization import swing_data as W                    # noqa: E402


def _wavg(g: pd.DataFrame) -> float:
    g = g.dropna(subset=["cao", "tonnage"])
    g = g[g["tonnage"] > 0]
    return float(np.average(g["cao"], weights=g["tonnage"])) if len(g) else np.nan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-01")
    a = ap.parse_args([] if argv is None else argv)
    warnings.simplefilter("ignore")
    mine, _, _ = load_sources(validate=False, verbose=False)
    m = mine[(mine["line"] == S.LINE_NEW) & (mine["datetime"] >= a.start)].copy()
    m["mon"] = m["datetime"].dt.to_period("M")
    q = m[m["source"] == "49Q"].copy()
    q["cr"] = q["crusher"].fillna("미기록").replace({"H/C+G/C": "G/C+H/C"})   # 순서만 다른 같은 방식
    ton = q.groupby(["mon", "cr"])["tonnage"].sum().unstack(fill_value=0)
    print("\n[1] 49Q 이송 물량 비중 % (C/R 생산방법별)")
    print((ton.div(ton.sum(axis=1), axis=0) * 100).round(0))
    print("\n[2] 49Q 물량 가중 CaO % (C/R별)")
    print(q.groupby(["mon", "cr"]).apply(_wavg).unstack().round(2))
    print("    기간 전체:", q.groupby("cr").apply(_wavg).round(2).to_dict())

    cna = C.clean_yard(pd.read_excel(RAW_DIR / S.DATA_FILE, S.YARD_PAIR[S.LINE_NEW][0]), load_col="적재물량(TPH)")
    yc = load_yard_change()
    yp = W.piles(yc[yc["line"] == S.LINE_NEW], cna, a.start, "2100-01-01", cna["datetime"].max())
    yp = yp[(yp["n_raw"] > 0) & yp["closed"]].copy()
    yp["mon"] = yp["end"].dt.to_period("M")
    hc = ton.get("H/C", 0) + ton.get("G/C+H/C", 0)
    df = pd.DataFrame({
        "야드 고품위 비율%": yp.groupby("mon")["hi_share"].mean() * 100,
        "광산 CaO(49Q+47Q)": m.groupby("mon").apply(_wavg),
        "광산 CaO(49Q)": q.groupby("mon").apply(_wavg),
        "H/C 포함 비중%": hc / ton.sum(axis=1) * 100,
    })
    print("\n[3] 월별 대조"); print(df.round(2))
    print("\n[4] 상관 (월 단위, 표본 수 =", len(df.dropna()), ")"); print(df.corr().round(2))


if __name__ == "__main__":
    main(sys.argv[1:])
