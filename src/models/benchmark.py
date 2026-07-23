"""10개 회귀 모델 벤치마크 (최적 모델 탐색) [ML-Engineer].

라인별 야드 CaO 예측을 10개 알고리즘으로 시계열 교차검증(TimeSeriesSplit)해 비교·추천한다.
스케일 민감 모델(선형·KNN·SVR)은 StandardScaler 파이프라인으로 공정 비교.
persist(직전값)·naive(평균) 기준선을 함께 표기.

⚠️ 값을 지어내지 않는다 — 실제 CV 성능만 리포트. 소표본(기존 n≈141)에서 복잡 모델의 과적합도 그대로 드러낸다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

from src.models.forecast import AR_FEATURES, AR_CORE, UPSTREAM_FEATURES


def get_models() -> dict:
    """비교할 10개 모델. (스케일 민감 모델은 스케일러 포함)"""
    sc = lambda m: make_pipeline(StandardScaler(), m)
    models = {
        "1.LinearRegression": sc(LinearRegression()),
        "2.Ridge": sc(Ridge(alpha=1.0)),
        "3.ElasticNet": sc(ElasticNet(alpha=0.05, l1_ratio=0.5, max_iter=5000)),
        "4.KNN": sc(KNeighborsRegressor(n_neighbors=7)),
        "5.SVR(RBF)": sc(SVR(C=10.0, gamma="scale")),
        "6.RandomForest": RandomForestRegressor(n_estimators=300, max_depth=6, random_state=0, n_jobs=-1),
        "7.ExtraTrees": ExtraTreesRegressor(n_estimators=300, max_depth=6, random_state=0, n_jobs=-1),
        "8.GradientBoosting": GradientBoostingRegressor(n_estimators=200, max_depth=2, random_state=0),
        "9.HistGBM": HistGradientBoostingRegressor(max_depth=3, random_state=0),
        "10.XGBoost": None,   # 지연 임포트 (아래)
    }
    return models


def _boosters():
    from lightgbm import LGBMRegressor
    from xgboost import XGBRegressor
    return {
        "10.XGBoost": XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                                   subsample=0.9, random_state=0, verbosity=0),
        "11.LightGBM": LGBMRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                                     subsample=0.9, random_state=0, verbose=-1),
    }


def benchmark(features_df: pd.DataFrame, use_upstream: bool = False, n_splits: int = 5) -> pd.DataFrame:
    """모델별 시계열 CV 성능표(MAE 오름차순). persist/naive 기준선 포함."""
    feats = AR_FEATURES + (UPSTREAM_FEATURES if use_upstream else [])
    d = features_df.dropna(subset=AR_CORE + ["cao"]).copy()
    X = d[feats].fillna(0.0).values
    y = d["cao"].values
    ar1 = d["ar1"].values
    tscv = TimeSeriesSplit(n_splits=n_splits)

    models = get_models()
    models.update(_boosters())  # XGBoost/LightGBM 포함 (10.XGBoost 교체 + 11.LightGBM 추가)

    rows = []
    # 기준선
    for name, predfn in [
        ("기준:naive(평균)", lambda tr, te: np.full(len(te), y[tr].mean())),
        ("기준:persist(직전값)", lambda tr, te: ar1[te]),
    ]:
        maes, r2s = [], []
        for tr, te in tscv.split(X):
            p = predfn(tr, te)
            maes.append(mean_absolute_error(y[te], p)); r2s.append(r2_score(y[te], p))
        rows.append(dict(model=name, MAE=np.mean(maes), RMSE=np.nan, R2=np.mean(r2s), is_baseline=True))

    for name, model in models.items():
        maes, rmses, r2s = [], [], []
        for tr, te in tscv.split(X):
            model.fit(X[tr], y[tr])
            p = model.predict(X[te])
            maes.append(mean_absolute_error(y[te], p))
            rmses.append(np.sqrt(((y[te] - p) ** 2).mean()))
            r2s.append(r2_score(y[te], p))
        rows.append(dict(model=name, MAE=np.mean(maes), RMSE=np.mean(rmses),
                         R2=np.mean(r2s), is_baseline=False))

    df = pd.DataFrame(rows).sort_values("MAE").reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df


def recommend(bench_df: pd.DataFrame) -> str:
    """벤치마크 표에서 최적(비기준) 모델 이름 반환."""
    cand = bench_df[~bench_df["is_baseline"]].sort_values("MAE")
    return cand.iloc[0]["model"] if len(cand) else ""
