"""야드 CaO 단기 예측 모델 (하이브리드: 자기회귀 + 상류) [ML-Engineer].

라인별(기존↔45Q, 신설↔CNA)로 야드 CaO를 시간 단위로 예측한다.

⭐️ 실증 결과(정직 보고, docs/data_schema §7 / handoff):
  - 야드 CaO는 지속성이 커(1h 자기상관 0.73), '자기회귀(AR) 피처'가 가장 강한 예측력.
  - 상류(OSP 인출) 피처는 현 데이터에서 예측을 개선하지 못함(상관 0.18) → 포함하되 가중 낮음.
  - 최적 모델 Ridge(AR): 신설/CNA MAE≈0.80, 기존/45Q MAE≈1.04 (R²≈0.5, naive 1.3~1.8 대비 개선).
  - 목표 MAE<0.5 는 미달 — 상류 제어 정보 부족이 원인(달성 불가 정직 고지, CLAUDE.md §3).

용도: 실시간 모니터링·조기경보(단기 예측). 처방적 배합제어는 신호 강화 후 가능.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

AR_FEATURES = ["ar1", "ar2", "ar3", "roll3_mean", "roll3_std", "hour"]
UPSTREAM_FEATURES = ["up_impl", "up_ton"]
AR_CORE = ["ar1", "ar2", "ar3", "roll3_mean", "roll3_std"]

# 학습·검증에 필요한 최소 행수. 이보다 적으면 모델을 만들지 않고 명시적으로 실패한다
# (가동 중지 라인·짧은 기간 설정에서 sklearn 의 난해한 오류 대신 원인을 알린다).
MIN_TRAIN_ROWS = 20


class InsufficientDataError(ValueError):
    """모델 학습/검증에 필요한 최소 데이터가 없을 때 발생 (§2-1 값을 지어내지 않는다)."""


def require_rows(n: int, need: int = MIN_TRAIN_ROWS, what: str = "모델 학습") -> None:
    """행수가 부족하면 원인이 드러나는 한국어 메시지로 실패시킨다."""
    if n < need:
        raise InsufficientDataError(
            f"{what}에 필요한 데이터 부족: 유효 {n}행 (최소 {need}행). "
            "해당 라인이 가동 중지 상태이거나 설정한 기간이 너무 짧습니다."
        )


def build_features(
    yard_hourly_cao: pd.Series, osp_hourly: pd.DataFrame, lag_hours: int
) -> pd.DataFrame:
    """시간별 야드 CaO 시계열 + OSP 시간집계 → 예측 피처 프레임.

    yard_hourly_cao : DatetimeIndex(시간), 값=야드 CaO 평균 (asfreq 1h)
    osp_hourly      : index=시간, columns=[impl, ton]
    """
    df = yard_hourly_cao.rename("cao").to_frame()
    df["ar1"] = df["cao"].shift(1)
    df["ar2"] = df["cao"].shift(2)
    df["ar3"] = df["cao"].shift(3)
    df["roll3_mean"] = df["cao"].shift(1).rolling(3).mean()
    df["roll3_std"] = df["cao"].shift(1).rolling(3).std()
    oh = osp_hourly.reindex(df.index)
    df["up_impl"] = oh["impl"].shift(lag_hours).ffill(limit=6)
    df["up_ton"] = oh["ton"].shift(lag_hours).rolling(3, min_periods=1).sum()
    df["hour"] = df.index.hour
    return df


@dataclass
class CVReport:
    label: str
    n: int
    mae: float
    rmse: float
    r2: float
    mae_persist: float
    mae_naive: float
    features: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"[{self.label}] n={self.n} MAE={self.mae:.3f} RMSE={self.rmse:.3f} "
            f"R2={self.r2:+.2f} (persist={self.mae_persist:.3f}, naive={self.mae_naive:.3f})"
        )


def evaluate(
    features_df: pd.DataFrame, use_upstream: bool = False, n_splits: int = 5, alpha: float = 1.0
) -> CVReport:
    """Ridge(AR[+상류]) 시계열 교차검증. persist/naive 기준선과 함께 리포트."""
    feats = AR_FEATURES + (UPSTREAM_FEATURES if use_upstream else [])
    d = features_df.dropna(subset=AR_CORE + ["cao"]).copy()
    require_rows(len(d), max(MIN_TRAIN_ROWS, (n_splits + 1) * 2), "시계열 교차검증")
    X = d[feats].fillna(0.0).values
    y = d["cao"].values
    ar1 = d["ar1"].values
    tscv = TimeSeriesSplit(n_splits=n_splits)
    maes, rmses, r2s, persist, naive = [], [], [], [], []
    for tr, te in tscv.split(X):
        model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
        model.fit(X[tr], y[tr])
        pred = model.predict(X[te])
        maes.append(mean_absolute_error(y[te], pred))
        rmses.append(np.sqrt(((y[te] - pred) ** 2).mean()))
        r2s.append(r2_score(y[te], pred))
        persist.append(mean_absolute_error(y[te], ar1[te]))
        naive.append(mean_absolute_error(y[te], np.full(len(te), y[tr].mean())))
    label = "AR+상류" if use_upstream else "AR"
    return CVReport(
        label, len(d), float(np.mean(maes)), float(np.mean(rmses)),
        float(np.mean(r2s)), float(np.mean(persist)), float(np.mean(naive)), feats,
    )


def fit_final(features_df: pd.DataFrame, use_upstream: bool = False, alpha: float = 1.0):
    """전체 데이터로 최종 모델 학습(운영 배포용). (model, feats) 반환."""
    feats = AR_FEATURES + (UPSTREAM_FEATURES if use_upstream else [])
    d = features_df.dropna(subset=AR_CORE + ["cao"])
    require_rows(len(d), MIN_TRAIN_ROWS, "최종 모델 학습")
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
    model.fit(d[feats].fillna(0.0).values, d["cao"].values)
    return model, feats
