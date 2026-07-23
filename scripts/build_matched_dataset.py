"""통합 데이터셋 생성 (라인 분리 · 시간인지 매칭) [Matching-Agent].

실행:
    python scripts/build_matched_dataset.py

도메인 확정 사항 반영:
  - 기존/신설은 서로 다른 야드(4-5K / 6-7K 킬른) → 라인별로 분리 모델링.
  - P/W1~4호 = 인출 지점(위치). 품위는 '인출시각 이전 최근 적재 광산품위'로 시간인지 매칭.
  - 야드 페어링(데이터 상관 근거): 기존↔CNA, 신설↔45Q 감마 (사용자 최종확인 권장).

산출(로컬 전용): data/processed/matched_기존.csv, matched_신설.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import schema as S
from config.paths import RAW_DIR, PROCESSED_DIR, ensure_dirs
from src.data import clean as C
from src.matching import pipeline as P

# 라인 → (야드 시트, 별칭) 페어링. 상관 근거로 설정, 사용자 확인 대상.
LINE_YARD = {
    S.LINE_OLD: (S.SHEET_YARD_CNA, "CNA(4-5K)"),
    S.LINE_NEW: (S.SHEET_MINE_45Q, "45Q감마(6-7K)"),
}


def main() -> None:
    ensure_dirs()
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)

    # ① 광산 정제 (지점별 적재 품위)
    mine = pd.concat(
        [
            C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q)),
            C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q)),
        ],
        ignore_index=True,
    )

    # ② OSP 인출 → 시간인지 예상 CaO
    osp = pd.concat(
        [
            C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
            C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW),
        ],
        ignore_index=True,
    )
    osp_exp = P.assign_expected_cao_timeaware(osp, mine)

    # ③ 라인별 야드 정제 + Time-Lag 추정 + 통합
    for line, (sheet, alias) in LINE_YARD.items():
        yard = C.clean_yard(pd.read_excel(xls, sheet))
        osp_h = P.aggregate_osp_hourly(osp_exp[osp_exp["line"] == line])
        yard_h = P.aggregate_yard_hourly(yard)
        lag = P.estimate_time_lag(osp_h, yard_h, max_lag_hours=24)
        matched = P.build_line_dataset(osp_exp, yard, line, lag.best_lag_hours)
        out = PROCESSED_DIR / f"matched_{line}.csv"
        matched.to_csv(out, index=False)
        print(
            f"[OK] {line}→{alias}: lag={lag.best_lag_hours}h corr={lag.best_corr:+.3f} "
            f"→ {out.name} (n={len(matched)})"
        )


if __name__ == "__main__":
    main()
