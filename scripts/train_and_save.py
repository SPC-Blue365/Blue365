"""확정 모델(Ridge) 라인별 학습·저장 [ML-Engineer].

실행: python scripts/train_and_save.py
→ models/ridge_<line>.joblib (모델+메타). 로컬 전용(.gitignore).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings

import joblib
import numpy as np

warnings.filterwarnings("ignore")

from config import schema as S
from config.paths import MODELS_DIR, ensure_dirs
from src.models import forecast as F
from src.models.dataset import all_lines


def main() -> None:
    ensure_dirs()
    lines = all_lines()
    skipped = []
    for line, ld in lines.items():
        d = ld.features.dropna(subset=F.AR_CORE + ["cao"])
        try:
            model, feats = F.fit_final(d, use_upstream=False)
            cv = F.evaluate(ld.features, use_upstream=False)
        except F.InsufficientDataError as e:
            # 가동 중지 라인 등 — 지어내지 않고 건너뛴다 (CLAUDE.md §2-1)
            note = S.LINE_NOTES.get(line, "")
            skipped.append(f"[SKIP] {line}→{ld.alias}: {e}" + (f" ({note})" if note else ""))
            print(skipped[-1])
            continue
        # 관리한계(경보 참고용): 잔차 표준편차
        resid_std = float(np.std(d["cao"].values - model.predict(d[feats].fillna(0).values)))
        bundle = dict(model=model, features=feats, line=line, alias=ld.alias,
                      lag_hours=ld.lag_hours, cv_mae=cv.mae, cv_r2=cv.r2,
                      n_train=len(d), resid_std=resid_std)
        out = MODELS_DIR / f"ridge_{line}.joblib"
        joblib.dump(bundle, out)
        print(f"[OK] {line}→{ld.alias}: 저장 {out.name} (n={len(d)}, CV MAE={cv.mae:.3f}, 잔차std={resid_std:.3f})")

    if skipped:
        print(f"\n⚠️ 학습 생략 {len(skipped)}개 라인 — 위 [SKIP] 사유 참조")


if __name__ == "__main__":
    main()
