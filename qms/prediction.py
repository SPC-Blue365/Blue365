"""28일 압축강도 조기 예측.

28일 강도 결과는 생산 후 28일이 지나야 나오므로, 그 전에 조기강도·화학·분말도로
28일 강도를 회귀 예측해 이상을 조기에 경보한다.

모델(품종별 다중선형회귀, 최소자승법)
  M7   28일 ~ 7일 강도 + 3일 강도
  M3   28일 ~ 3일 강도 + 분말도 + SO3 + 클링커 C3S
  M1   28일 ~ 1일 강도 + 분말도 + 클링커 C3S            (3종)
  MC   28일 ~ 분말도 + SO3 + 강열감량 + 클링커 C3S + f-CaO (조기강도 없음 — 신뢰도 낮음)
각 로트는 사용 가능한 입력 중 가장 정확한(우선순위 높은) 모델로 예측한다.
예측구간은 ±1.96·RMSE(정규 근사)로 표시한다. 잔차는 LOO(Leave-One-Out)로 계산해
과적합에 의한 과소평가를 줄였다.

※ 회귀계수는 공장 데이터로 학습되는 값이며, 데이터가 쌓일수록 정확도가 개선된다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .standards import SpecRegistry
from .store import DataStore

MODELS: dict[str, dict] = {
    "M7": {"label": "7일 강도 기반", "features": ["phy_s7", "phy_s3"]},
    "M3": {"label": "3일 강도 기반", "features": ["phy_s3", "f_blaine", "f_so3", "f_c3s"]},
    "M1": {"label": "1일 강도 기반", "features": ["phy_s1", "f_blaine", "f_c3s"]},
    "MC": {"label": "화학·분말도 기반", "features": ["f_blaine", "f_so3", "f_loi", "f_c3s", "f_fcao"]},
}
PRIORITY = ["M7", "M3", "M1", "MC"]
FEATURE_LABELS = {
    "phy_s7": "7일 강도", "phy_s3": "3일 강도", "phy_s1": "1일 강도", "f_blaine": "분말도(일평균)",
    "f_so3": "SO₃(일평균)", "f_loi": "강열감량(일평균)", "f_c3s": "클링커 C₃S(1~2일 전)",
    "f_fcao": "클링커 f-CaO(1~2일 전)",
}


@dataclass
class FittedModel:
    code: str
    features: list[str]
    coef: np.ndarray        # [절편, 계수...]
    r2: float
    rmse: float             # LOO 기준
    n: int

    @property
    def label(self) -> str:
        return MODELS[self.code]["label"]

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.coef[0] + X @ self.coef[1:]

    def equation(self, decimals: int = 3) -> str:
        terms = [f"{self.coef[0]:.{decimals}f}"]
        for f, c in zip(self.features, self.coef[1:]):
            terms.append(f"{'+' if c >= 0 else '−'} {abs(c):.{decimals}f}×{FEATURE_LABELS.get(f, f)}")
        return "28일 = " + " ".join(terms)


def feature_frame(store: DataStore, product: str) -> pd.DataFrame:
    """로트(일)별 예측 입력 데이터. 클링커는 생산 1~2일 전 평균(사일로 체류 가정)."""
    phy = store.tables.get("physical", pd.DataFrame())
    if len(phy) == 0 or "product" not in phy:
        return pd.DataFrame()
    lots = phy[phy["product"] == product].copy()
    if len(lots) == 0:
        return pd.DataFrame()
    lots["day"] = lots["timestamp"].dt.normalize()

    cem = store.tables.get("cement", pd.DataFrame())
    if len(cem):
        c = cem[cem["product"] == product].copy()
        c["day"] = c["timestamp"].dt.normalize()
        daily = c.groupby("day")[["cem_blaine", "cem_so3", "cem_loi"]].mean()
        daily.columns = ["f_blaine", "f_so3", "f_loi"]
        lots = lots.merge(daily, left_on="day", right_index=True, how="left")

    clk = store.tables.get("clinker", pd.DataFrame())
    if len(clk) and "clk_c3s" in clk:
        cd = clk.set_index("timestamp")[["clk_c3s", "clk_fcao"]].resample("1D").mean()
        used = cd.shift(1).rolling(2, min_periods=1).mean()
        used.columns = ["f_c3s", "f_fcao"]
        lots = lots.merge(used, left_on="day", right_index=True, how="left")
    for f in ("f_blaine", "f_so3", "f_loi", "f_c3s", "f_fcao"):
        if f not in lots:
            lots[f] = np.nan
    return lots.drop(columns=["day"]).reset_index(drop=True)


def _fit(df: pd.DataFrame, code: str, min_extra: int = 6) -> FittedModel | None:
    feats = MODELS[code]["features"]
    if any(f not in df for f in feats) or "phy_s28" not in df:
        return None
    d = df.dropna(subset=feats + ["phy_s28"])
    if len(d) < len(feats) + min_extra:
        return None
    X = d[feats].to_numpy(float)
    y = d["phy_s28"].to_numpy(float)
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-9
    try:
        hat = np.einsum("ij,jk,ik->i", A, np.linalg.pinv(A.T @ A), A)
        loo = (y - yhat) / np.clip(1 - hat, 1e-6, None)
        rmse = float(np.sqrt(np.mean(loo ** 2)))
    except np.linalg.LinAlgError:
        rmse = float(np.sqrt(ss_res / max(len(y) - len(coef), 1)))
    return FittedModel(code, feats, coef, 1 - ss_res / ss_tot, rmse, len(d))


def fit_models(store: DataStore, product: str) -> dict[str, FittedModel]:
    df = feature_frame(store, product)
    out = {}
    for code in PRIORITY:
        m = _fit(df, code) if len(df) else None
        if m is not None:
            out[code] = m
    return out


def predict(store: DataStore, product: str, models: dict[str, FittedModel] | None = None) -> pd.DataFrame:
    """로트별 28일 강도 예측. 실측이 있는 로트는 M7 기반 LOO 잔차(z)도 계산."""
    df = feature_frame(store, product)
    if len(df) == 0:
        return pd.DataFrame()
    models = models if models is not None else fit_models(store, product)
    pred = np.full(len(df), np.nan)
    used = np.array([""] * len(df), dtype=object)
    rmse = np.full(len(df), np.nan)
    for code in PRIORITY:
        m = models.get(code)
        if m is None:
            continue
        ok = df[m.features].notna().all(axis=1).to_numpy() & np.isnan(pred)
        if ok.any():
            pred[ok] = m.predict(df.loc[ok, m.features].to_numpy(float))
            used[ok] = m.label
            rmse[ok] = m.rmse
    out = pd.DataFrame({
        "timestamp": df["timestamp"], "product": product, "s28_actual": df.get("phy_s28"),
        "s28_pred": pred, "model": used, "rmse": rmse,
        "pred_lo": pred - 1.96 * rmse, "pred_hi": pred + 1.96 * rmse,
    })
    # 실측 대비 잔차(조기강도로 설명되지 않는 28일 편차 → 시험오차·후기강도 요인 판단용)
    m7 = models.get("M7")
    out["resid_z"] = np.nan
    if m7 is not None:
        ok = df[m7.features].notna().all(axis=1) & df["phy_s28"].notna()
        if ok.any():
            p7 = m7.predict(df.loc[ok, m7.features].to_numpy(float))
            out.loc[ok, "resid_z"] = (df.loc[ok, "phy_s28"].to_numpy(float) - p7) / m7.rmse
    return out


def attach_predictions(store: DataStore, registry: SpecRegistry) -> dict[str, dict[str, FittedModel]]:
    """physical 테이블에 pred_s28(실측 전 로트만), pred_model, resid_z 열을 추가한다."""
    phy = store.tables.get("physical")
    all_models: dict[str, dict[str, FittedModel]] = {}
    if phy is None or len(phy) == 0:
        return all_models
    phy = phy.copy()
    phy["pred_s28"] = np.nan
    phy["pred_model"] = ""
    phy["resid_z"] = np.nan
    for product in registry.products_for("phy_s28"):
        models = fit_models(store, product)
        all_models[product] = models
        p = predict(store, product, models)
        if len(p) == 0:
            continue
        mask = phy["product"] == product
        key = phy.loc[mask, "timestamp"]
        p = p.set_index("timestamp")
        future = p["s28_actual"].isna()
        pred_vals = p["s28_pred"].where(future)
        phy.loc[mask, "pred_s28"] = key.map(pred_vals).to_numpy()
        phy.loc[mask, "pred_model"] = key.map(p["model"].where(future, "")).fillna("").to_numpy()
        phy.loc[mask, "resid_z"] = key.map(p["resid_z"]).to_numpy()
    store.tables["physical"] = phy
    return all_models
