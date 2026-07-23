"""야드 CaO 예측 베이스라인 모델 [ML-Engineer].

통합 데이터셋(data/processed/matched_hourly.csv)으로 야드 CaO를 예측한다.
CLAUDE.md §3 ML-Engineer 성공기준: 시계열 CV, MAE·RMSE·R² 리포트, 목표 MAE<0.5.

⚠️ 값을 지어내지 않는다 — 실제 CV 성능만 보고한다. 현 단계는 '베이스라인'으로,
   매칭 신호가 약하면(§data_schema §7) 성능도 제한적임을 정직히 드러낸다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit

FEATURES = [
    "osp_expected_cao",
    "osp_total_ton",
    "osp_old_ton",
    "osp_new_ton",
    "osp_n_events",
    "osp_n_zones",
    "osp_cao_spread",
    "yard_tph",
    "hour",
]
TARGET = "yard_cao"


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["hour"] = df["datetime"].dt.hour
    df = df.sort_values("datetime").reset_index(drop=True)
    for c in FEATURES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df[FEATURES] = df[FEATURES].fillna(0.0)
    return df.dropna(subset=[TARGET])


def evaluate(df: pd.DataFrame, n_splits: int = 5) -> pd.DataFrame:
    """여러 모델을 시계열 CV로 평가하고 지표 표를 반환."""
    df = _prep(df)
    X, y = df[FEATURES].values, df[TARGET].values
    tscv = TimeSeriesSplit(n_splits=n_splits)

    models = {
        "naive_mean": None,  # 학습구간 평균 예측 (기준선)
        "ridge": Ridge(alpha=1.0),
        "gbr": GradientBoostingRegressor(random_state=0, n_estimators=200, max_depth=2),
    }
    rows = []
    for name, model in models.items():
        maes, rmses, r2s = [], [], []
        for tr, te in tscv.split(X):
            if name == "naive_mean":
                pred = np.full(len(te), y[tr].mean())
            else:
                model.fit(X[tr], y[tr])
                pred = model.predict(X[te])
            maes.append(mean_absolute_error(y[te], pred))
            rmses.append(np.sqrt(mean_squared_error(y[te], pred)))
            r2s.append(r2_score(y[te], pred))
        rows.append(
            dict(model=name, MAE=np.mean(maes), RMSE=np.mean(rmses), R2=np.mean(r2s))
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import PROCESSED_DIR

    data = pd.read_csv(PROCESSED_DIR / "matched_hourly.csv")
    result = evaluate(data)
    print(f"[통합 데이터셋] {len(data)}행, 목표=야드 CaO")
    print(result.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\n목표: MAE < 0.5 (CLAUDE.md). 야드 CaO 자체 표준편차 ≈", round(data['yard_cao'].std(), 2))
