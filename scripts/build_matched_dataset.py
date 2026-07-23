"""통합 데이터셋 생성 스크립트 (재현용) [Matching-Agent].

실행:
    python scripts/build_matched_dataset.py

원시 data/raw/data_v1.xlsx → 정제 → 매칭 → Time-Lag 추정 → data/processed/matched_hourly.csv
(로컬 전용: 산출 CSV 는 .gitignore 로 원격 커밋되지 않음)
"""

from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (어디서 실행하든 동작)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import schema as S
from config.paths import RAW_DIR, PROCESSED_DIR, ensure_dirs
from src.data import clean as C
from src.matching import pipeline as P


def main() -> None:
    ensure_dirs()
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)

    # ① 광산 정제 + 구역-품위 테이블
    mine = pd.concat(
        [
            C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q)),
            C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q)),
        ],
        ignore_index=True,
    )
    by_line, by_zone = C.build_zone_grade_table(mine)

    # ② OSP 인출 정제 (균등 배분)
    osp = pd.concat(
        [
            C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
            C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW),
        ],
        ignore_index=True,
    )

    # ③ 야드 CNA 정제 (목표)
    yard = C.clean_yard_cna(pd.read_excel(xls, S.SHEET_YARD_CNA))

    # ④ 매칭 + Time-Lag + 통합
    matched, lag, osp_exp = P.run_full_pipeline(
        mine, osp, yard, by_line, by_zone, freq="1h", max_lag_hours=24
    )

    out = PROCESSED_DIR / "matched_hourly.csv"
    matched.to_csv(out, index=False)
    by_line.to_csv(PROCESSED_DIR / "zone_grade_by_line.csv", index=False)

    print(f"[OK] 통합 데이터셋 저장: {out}  shape={matched.shape}")
    print(f"[OK] Time-Lag 추정: {lag.best_lag_hours}시간 (corr={lag.best_corr:.3f})")
    print(f"[OK] OSP 예상CaO 매칭 커버리지: {osp_exp['cao_source'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
