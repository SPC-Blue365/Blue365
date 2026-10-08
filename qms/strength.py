"""재령별 압축강도·응결시간 예측(클링커 광물·화학·분쇄 조건) + 제어 솔루션.

모델: 경험칙 계수를 출발점으로 하는 리지 회귀(prior-informed ridge)
    β̂ = argmin ‖(y − ȳ) − (X − x̄)·β‖² + λ·‖s ⊙ (β − β₀)‖²
  - β₀ : 경험칙 계수(PRIORS, 추정). s : 입력별 '통상 운전 변동폭'(SCALES) — 벌점은 그 폭에서의 효과 차이로 매긴다.
  - 데이터가 적거나 변동이 작아 정보가 약한 입력은 β ≈ β₀ 로 유지되고(외삽 시 과대 계수 방지),
    데이터가 충분하면 공장 데이터 계수로 수렴한다.
  - λ 는 LOO(Leave-One-Out) 오차가 최소가 되도록 자동 선택(닫힌 해 e_i / (1 − h_ii − 1/n)).
    단 유효 자유도 tr(H) ≤ n/3 (과적합 방지), 이론과 부호가 반대인 계수는 경험칙 값으로 고정(SIGNS).
  - KS L ISO 679 시험조건(양생수·시험실 온도·습도)을 벗어난 로트는 학습에서 제외한다.
  - 예측구간 = 예측값 ± 1.96 × LOO RMSE (정규 근사, 약 95%).

입력(로트 = 생산일 × 품종)
  광물  XRD 알라이트·벨라이트·C₃A·C₄AF·자유석회 — 생산 1~2일 전 클링커(사일로 체류 가정).
        XRD 결과가 없는 날은 XRF Bogue 값을 XRD 보정식(rawmix.XrdMap)으로 환산해 쓴다.
  화학  클링커 Na₂Oeq
  분쇄  분말도·SO₃·석회석 혼합률·밀 출구 온도(시멘트 일평균)

제어 솔루션
  레버(분말도·SO₃·석회석·알라이트(LSF/소성)·C₃A(IM)·자유석회(소성)·밀 온도)의 변경 비용을 최소화하면서
  목표 강도·응결을 만족하는 조합을 찾는다(scipy L-BFGS-B, 제약 위반 벌점). 레버 간 화학 결합:
    알라이트 +1%p ⇒ 벨라이트 −0.75%p (C₂S + CaO → C₃S 질량비 172.2/228.3)
    C₃A +1%p(IM↑, Al₂O₃+Fe₂O₃ 일정) ⇒ C₄AF −0.70%p (Bogue 계수 관계)

※ PRIORS·레버 비용·효과 수치는 업계 경험칙(추정)이다. 공장 데이터·실험으로 검증 후 수정할 것.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .rawmix import XrdMap, identity_xrd_map
from .standards import SpecRegistry
from .store import DataStore

FEATURE_INFO: dict[str, tuple[str, str]] = {
    "alite": ("알라이트(C₃S, XRD)", "%"), "belite": ("벨라이트(C₂S, XRD)", "%"), "c3a": ("C₃A(XRD)", "%"),
    "c4af": ("C₄AF(XRD)", "%"), "fcao": ("자유석회", "%"), "na2oeq": ("등가알칼리 Na₂Oeq", "%"),
    "blaine": ("분말도(Blaine)", "cm²/g"), "so3": ("SO₃", "%"), "so3dev2": ("(SO₃ − 최적)²", "%²"),
    "ls": ("석회석 혼합률", "%"), "mill_temp": ("밀 출구 온도", "℃"),
}
INPUT_KEYS = ["alite", "belite", "c3a", "c4af", "fcao", "na2oeq", "blaine", "so3", "ls", "mill_temp"]
STRENGTH_FEATURES = ["alite", "belite", "c3a", "c4af", "fcao", "na2oeq", "blaine", "so3dev2", "ls"]
SETTING_FEATURES = ["so3", "blaine", "c3a", "na2oeq", "mill_temp", "ls", "fcao"]
TARGETS: dict[str, dict] = {
    "phy_s1": {"label": "1일 강도", "unit": "MPa", "features": STRENGTH_FEATURES, "age": 1},
    "phy_s3": {"label": "3일 강도", "unit": "MPa", "features": STRENGTH_FEATURES, "age": 3},
    "phy_s7": {"label": "7일 강도", "unit": "MPa", "features": STRENGTH_FEATURES, "age": 7},
    "phy_s28": {"label": "28일 강도", "unit": "MPa", "features": STRENGTH_FEATURES, "age": 28},
    "phy_ist": {"label": "초결", "unit": "분", "features": SETTING_FEATURES, "age": None},
    "phy_fst": {"label": "종결", "unit": "분", "features": SETTING_FEATURES, "age": None},
}
# 경험칙 계수(입력 1단위당 변화, 추정). 문헌 경향: C₃S는 3~28일, C₂S는 28일 이후, C₃A·알칼리는 1일 강도에
# 기여하며 알칼리는 28일 강도를 낮춘다. 분말도는 조기강도에 더 민감. 석회석은 희석 효과.
PRIORS: dict[str, dict[str, float]] = {
    "phy_s1": {"alite": 0.20, "belite": 0.00, "c3a": 0.30, "c4af": 0.0, "fcao": -0.4, "na2oeq": 4.0,
               "blaine": 0.008, "so3dev2": -1.5, "ls": -0.25},
    "phy_s3": {"alite": 0.25, "belite": 0.00, "c3a": 0.15, "c4af": 0.0, "fcao": -0.6, "na2oeq": 2.0,
               "blaine": 0.012, "so3dev2": -1.5, "ls": -0.30},
    "phy_s7": {"alite": 0.28, "belite": 0.03, "c3a": 0.05, "c4af": 0.0, "fcao": -0.8, "na2oeq": 0.0,
               "blaine": 0.010, "so3dev2": -2.0, "ls": -0.35},
    "phy_s28": {"alite": 0.32, "belite": 0.08, "c3a": -0.10, "c4af": 0.0, "fcao": -1.0, "na2oeq": -5.0,
                "blaine": 0.008, "so3dev2": -2.5, "ls": -0.40},
    "phy_ist": {"so3": 45.0, "blaine": -0.05, "c3a": -6.0, "na2oeq": -40.0, "mill_temp": -0.5, "ls": -2.0,
                "fcao": -5.0},
    "phy_fst": {"so3": 45.0, "blaine": -0.06, "c3a": -8.0, "na2oeq": -50.0, "mill_temp": -0.5, "ls": -3.0,
                "fcao": -5.0},
}
# 통상 운전 변동폭(벌점 척도) — 이 폭만큼 바뀔 때의 효과 차이로 경험칙과의 괴리를 벌점화
SCALES = {"alite": 2.0, "belite": 2.0, "c3a": 1.0, "c4af": 1.0, "fcao": 0.3, "na2oeq": 0.1, "blaine": 150.0,
          "so3dev2": 0.09, "so3": 0.2, "ls": 1.0, "mill_temp": 5.0}
# 이론상 부호(+1: 증가 시 증가, −1: 증가 시 감소). 데이터 계수가 반대 부호이면 경험칙 값으로 고정한다.
_S_SIGNS = {"alite": 1, "blaine": 1, "fcao": -1, "ls": -1, "so3dev2": -1}
SIGNS = {"phy_s1": _S_SIGNS, "phy_s3": _S_SIGNS, "phy_s7": _S_SIGNS, "phy_s28": _S_SIGNS,
         "phy_ist": {"so3": 1, "blaine": -1, "c3a": -1}, "phy_fst": {"so3": 1, "blaine": -1, "c3a": -1}}
DEFAULT_RMSE = {"phy_s1": 1.5, "phy_s3": 1.8, "phy_s7": 2.0, "phy_s28": 2.5, "phy_ist": 25.0, "phy_fst": 30.0}
LAM_GRID = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0)
MIN_LOTS = 8


@dataclass
class RidgeModel:
    target: str
    product: str
    features: list[str]
    x_mean: np.ndarray
    x_std: np.ndarray
    y_mean: float
    beta: np.ndarray            # 입력 1단위당 계수
    beta0: np.ndarray           # 경험칙 계수
    lam: float                  # inf = 경험칙 계수 그대로
    rmse: float                 # LOO RMSE
    r2: float
    n: int
    source: str
    fixed: tuple[str, ...] = ()  # 부호 상충으로 경험칙 값에 고정된 입력
    n_excluded: int = 0          # 시험조건 이탈로 학습 제외한 로트 수

    @property
    def label(self) -> str:
        return TARGETS[self.target]["label"]

    def predict_row(self, feats: dict) -> float:
        x = np.array([feats.get(f, m) if np.isfinite(feats.get(f, np.nan)) else m
                      for f, m in zip(self.features, self.x_mean)], float)
        return float(self.y_mean + (x - self.x_mean) @ self.beta)

    def contributions(self, feats: dict) -> dict[str, float]:
        """평소(학습 평균) 대비 입력별 기여(β × (x − x̄))."""
        out = {}
        for f, m, b in zip(self.features, self.x_mean, self.beta):
            v = feats.get(f, np.nan)
            out[f] = float(b * ((v if np.isfinite(v) else m) - m))
        return out

    def coef_table(self) -> pd.DataFrame:
        rows = []
        for f, b, b0 in zip(self.features, self.beta, self.beta0):
            name, unit = FEATURE_INFO[f]
            rows.append({"입력": name, "단위": unit, "학습 계수": b, "경험칙 계수": b0,
                         "변동폭": SCALES[f], "변동폭당 영향": b * SCALES[f],
                         "평균": float(self.x_mean[self.features.index(f)]),
                         "비고": "부호 상충 → 경험칙 고정" if f in self.fixed else ""})
        return pd.DataFrame(rows)


def _ridge_path(Z: np.ndarray, r0: np.ndarray, free: np.ndarray, lam_grid, max_df: float):
    """free 열만 갱신하는 리지(경험칙 대비 편차 δ). 반환: (LOO RMSE, λ, δ) — λ=inf 는 경험칙 그대로."""
    n = len(r0)
    best = (float(np.sqrt(np.mean((r0 * n / max(n - 1, 1)) ** 2))), float("inf"), np.zeros(Z.shape[1]))
    Zf = Z[:, free]
    if Zf.shape[1] == 0:
        return best
    G = Zf.T @ Zf
    for lam in lam_grid:
        M = np.linalg.inv(G + lam * np.eye(Zf.shape[1]))
        h = np.einsum("ij,jk,ik->i", Zf, M, Zf)
        if float(h.sum()) > max_df:            # 유효 자유도 초과 → 과적합 위험
            continue
        d = np.zeros(Z.shape[1])
        d[free] = M @ (Zf.T @ r0)
        e = r0 - Z @ d
        loo = e / np.clip(1 - h - 1.0 / n, 1e-6, None)
        rmse = float(np.sqrt(np.mean(loo ** 2)))
        if rmse < best[0]:
            best = (rmse, lam, d)
    return best


def _fit_prior_ridge(X: np.ndarray, y: np.ndarray, beta0: np.ndarray, scales: np.ndarray,
                     signs: np.ndarray | None = None, lam_grid=LAM_GRID):
    """경험칙 사전정보 리지. 반환: (x̄, s, ȳ, β, λ, LOO RMSE, R², 고정된 열 마스크)."""
    n, p = X.shape
    xm = X.mean(axis=0)
    s = np.asarray(scales, float)
    Z = (X - xm) / s
    ym = float(y.mean())
    yc = y - ym
    b0z = beta0 * s
    r0 = yc - Z @ b0z
    free = np.ones(p, bool)
    max_df = max(1.0, n / 3.0)
    for _ in range(p + 1):
        rmse, lam, d = _ridge_path(Z, r0, free, lam_grid, max_df)
        bz = b0z + d
        if signs is None:
            break
        bad = free & (signs != 0) & (np.sign(bz) != signs) & (np.abs(bz) > 1e-12)
        if not bad.any():
            break
        free &= ~bad                           # 이론과 부호가 반대인 계수 → 경험칙 값 고정 후 재적합
    beta = bz / s
    e = yc - Z @ bz
    ss_tot = float(np.sum(yc ** 2)) or 1e-9
    return xm, s, ym, beta, lam, rmse, 1 - float(np.sum(e ** 2)) / ss_tot, ~free


# ── 학습 데이터(로트별 입력) ────────────────────────────────────────────
def _daily_used(df: pd.DataFrame, cols: list[str], days: pd.DatetimeIndex) -> pd.DataFrame:
    """생산일 D 에 사용된 클링커 = D−1·D−2 일 평균(사일로 체류 1~2일 가정)."""
    if len(df) == 0:
        return pd.DataFrame(index=days, columns=cols, dtype=float)
    have = [c for c in cols if c in df]
    daily = df.set_index("timestamp")[have].resample("1D").mean()
    full = pd.date_range(min(daily.index.min(), days.min()) - pd.Timedelta(days=3), max(daily.index.max(), days.max()),
                         freq="1D")
    daily = daily.reindex(full)
    used = daily.shift(1).rolling(2, min_periods=1).mean()
    out = used.reindex(days)
    for c in cols:
        if c not in out:
            out[c] = np.nan
    return out


def lot_features(store: DataStore, registry: SpecRegistry, product: str, xrd_map: XrdMap | None = None) -> pd.DataFrame:
    """로트별 강도·응결 모델 입력 + 실측값. phase_src = XRD | Bogue 환산."""
    phy = store.tables.get("physical", pd.DataFrame())
    if len(phy) == 0 or "product" not in phy:
        return pd.DataFrame()
    lots = phy[phy["product"] == product].copy().reset_index(drop=True)
    if len(lots) == 0:
        return pd.DataFrame()
    xm = xrd_map or identity_xrd_map()
    lots["day"] = lots["timestamp"].dt.normalize()
    days = pd.DatetimeIndex(lots["day"])

    cem = store.tables.get("cement", pd.DataFrame())
    cem_cols = {"cem_blaine": "blaine", "cem_so3": "so3", "cem_ls": "ls", "cem_mill_temp": "mill_temp"}
    if len(cem):
        c = cem[cem["product"] == product].copy()
        c["day"] = c["timestamp"].dt.normalize()
        have = [k for k in cem_cols if k in c]
        daily = c.groupby("day")[have].mean().rename(columns=cem_cols)
        lots = lots.merge(daily, left_on="day", right_index=True, how="left")
    for v in cem_cols.values():
        if v not in lots:
            lots[v] = np.nan

    clk = store.tables.get("clinker", pd.DataFrame())
    bc = _daily_used(clk, ["clk_c3s", "clk_c2s", "clk_c3a", "clk_c4af", "clk_fcao", "clk_na2oeq", "clk_mgo"], days)
    xrd = store.tables.get("xrd", pd.DataFrame())
    xc = _daily_used(xrd, ["xrd_alite", "xrd_belite", "xrd_c3a", "xrd_c4af", "xrd_fcao"], days)

    def mapped(ph: str, col: str) -> np.ndarray:
        b0, b1 = xm.coef.get(ph, (0.0, 1.0))
        return (b0 + b1 * bc[col]).to_numpy(float)

    src = np.where(xc["xrd_alite"].notna().to_numpy(), "XRD", "Bogue 환산")
    lots["alite"] = np.where(xc["xrd_alite"].notna(), xc["xrd_alite"], mapped("alite", "clk_c3s"))
    lots["belite"] = np.where(xc["xrd_belite"].notna(), xc["xrd_belite"], mapped("belite", "clk_c2s"))
    lots["c3a"] = np.where(xc["xrd_c3a"].notna(), xc["xrd_c3a"], mapped("c3a", "clk_c3a"))
    lots["c4af"] = np.where(xc["xrd_c4af"].notna(), xc["xrd_c4af"], mapped("c4af", "clk_c4af"))
    lots["fcao"] = np.where(xc["xrd_fcao"].notna(), xc["xrd_fcao"], mapped("fcao", "clk_fcao"))
    lots["na2oeq"] = bc["clk_na2oeq"].to_numpy(float)
    lots["phase_src"] = src
    # 시험조건(KS L ISO 679) 이탈 로트 표시 — 강도 학습에서 제외
    valid = pd.Series(True, index=lots.index)
    for it in registry.all():
        if it.ks_is_method and it.key in lots:
            lim = it.limits_for(product)
            v = lots[it.key]
            if lim.ks_min is not None:
                valid &= ~(v < lim.ks_min)
            if lim.ks_max is not None:
                valid &= ~(v > lim.ks_max)
    lots["test_valid"] = valid
    so3_opt = so3_optimum(registry, product)
    lots["so3dev2"] = (lots["so3"] - so3_opt) ** 2
    return lots.drop(columns=["day"])


def so3_optimum(registry: SpecRegistry, product: str) -> float:
    """강도 최적 SO₃ — 사내 관리기준 목표값을 최적치로 본다(최적 SO₃ 시험값으로 교체 권장)."""
    t = registry["cem_so3"].limits_for(product).target if "cem_so3" in registry else None
    return float(t) if t is not None else (3.2 if product == "3종" else 2.6)


def features_from_inputs(inputs: dict, so3_opt: float) -> dict:
    f = {k: float(inputs[k]) if inputs.get(k) is not None else np.nan for k in INPUT_KEYS}
    f["so3dev2"] = (f["so3"] - so3_opt) ** 2 if np.isfinite(f["so3"]) else np.nan
    return f


# ── 모델 묶음 ───────────────────────────────────────────────────────────
@dataclass
class StrengthModels:
    product: str
    models: dict[str, RidgeModel]
    so3_opt: float
    train: pd.DataFrame
    registry: SpecRegistry = field(repr=False, default=None)

    def predict(self, inputs: dict) -> pd.DataFrame:
        feats = features_from_inputs(inputs, self.so3_opt)
        rows = []
        for tgt, m in self.models.items():
            p = m.predict_row(feats)
            item = self.registry[tgt] if self.registry is not None and tgt in self.registry else None
            lim = item.limits_for(self.product) if item else None
            lo, hi = p - 1.96 * m.rmse, p + 1.96 * m.rmse
            rows.append({"target": tgt, "항목": m.label, "단위": TARGETS[tgt]["unit"], "예측": p, "하한(95%)": lo,
                         "상한(95%)": hi, "RMSE": m.rmse, "학습 로트": m.n, "모델": m.source,
                         "KS": _ks_text(lim), "사내": _spec_text(lim), "판정": judge(p, lo, hi, lim)})
        return pd.DataFrame(rows)

    def predict_values(self, inputs: dict) -> dict[str, float]:
        feats = features_from_inputs(inputs, self.so3_opt)
        return {t: m.predict_row(feats) for t, m in self.models.items()}

    def typical_inputs(self) -> dict:
        """학습 데이터 평균(평소 조건)."""
        d = self.train
        out = {}
        for k in INPUT_KEYS:
            v = d[k].mean() if k in d and d[k].notna().any() else np.nan
            out[k] = float(v) if np.isfinite(v) else DEFAULT_INPUTS.get(self.product, DEFAULT_INPUTS["1종"])[k]
        return out

    def latest_inputs(self) -> tuple[dict, pd.Timestamp | None]:
        """가장 최근 생산 로트의 입력(결측은 평소값)."""
        d = self.train
        if len(d) == 0:
            return self.typical_inputs(), None
        last = d.sort_values("timestamp").iloc[-1]
        base = self.typical_inputs()
        out = {k: float(last[k]) if k in last and pd.notna(last[k]) else base[k] for k in INPUT_KEYS}
        return out, last["timestamp"]


DEFAULT_INPUTS = {
    "1종": {"alite": 64.0, "belite": 14.0, "c3a": 7.5, "c4af": 11.0, "fcao": 1.0, "na2oeq": 0.75, "blaine": 3450.0,
            "so3": 2.60, "ls": 4.0, "mill_temp": 105.0},
    "3종": {"alite": 64.0, "belite": 14.0, "c3a": 7.5, "c4af": 11.0, "fcao": 1.0, "na2oeq": 0.75, "blaine": 4600.0,
            "so3": 3.20, "ls": 1.5, "mill_temp": 105.0},
}
DEFAULT_LEVEL = {  # 데이터가 전혀 없을 때 절편으로 쓰는 평소 수준(사내 목표값 근사, 추정)
    "1종": {"phy_s1": np.nan, "phy_s3": 29.5, "phy_s7": 40.0, "phy_s28": 53.0, "phy_ist": 220.0, "phy_fst": 300.0},
    "3종": {"phy_s1": 20.0, "phy_s3": 37.0, "phy_s7": 46.0, "phy_s28": 59.0, "phy_ist": 180.0, "phy_fst": 250.0},
}


def _ks_text(lim) -> str:
    if lim is None:
        return "-"
    if lim.ks_min is not None:
        return f"≥ {lim.ks_min:g}"
    if lim.ks_max is not None:
        return f"≤ {lim.ks_max:g}"
    return "-"


def _spec_text(lim) -> str:
    if lim is None:
        return "-"
    if lim.lsl is not None and lim.usl is not None:
        return f"{lim.lsl:g} ~ {lim.usl:g}"
    if lim.lsl is not None:
        return f"≥ {lim.lsl:g}"
    if lim.usl is not None:
        return f"≤ {lim.usl:g}"
    return "-"


def judge(p: float, lo: float, hi: float, lim) -> str:
    if lim is None:
        return "-"
    if (lim.ks_min is not None and p < lim.ks_min) or (lim.ks_max is not None and p > lim.ks_max):
        return "🔴 KS 미달 예측"
    if (lim.lsl is not None and p < lim.lsl) or (lim.usl is not None and p > lim.usl):
        return "🟠 사내기준 이탈 예측"
    if (lim.lsl is not None and lo < lim.lsl) or (lim.usl is not None and hi > lim.usl):
        return "🟡 기준 근접(구간 걸침)"
    return "🟢 양호"


def fit_strength_models(store: DataStore, registry: SpecRegistry, product: str,
                        xrd_map: XrdMap | None = None) -> StrengthModels:
    df = lot_features(store, registry, product, xrd_map)
    so3_opt = so3_optimum(registry, product)
    models: dict[str, RidgeModel] = {}
    for tgt, info in TARGETS.items():
        feats = info["features"]
        beta0 = np.array([PRIORS[tgt].get(f, 0.0) for f in feats], float)
        d = df.dropna(subset=feats + [tgt]) if len(df) and tgt in df and all(f in df for f in feats) else pd.DataFrame()
        n_ex = 0
        if len(d) and "test_valid" in d and tgt.startswith("phy_s"):
            n_ex = int((~d["test_valid"]).sum())
            d = d[d["test_valid"]]
        if len(d) >= MIN_LOTS:
            X = d[feats].to_numpy(float)
            y = d[tgt].to_numpy(float)
            scales = np.array([SCALES[f] for f in feats])
            signs = np.array([SIGNS.get(tgt, {}).get(f, 0) for f in feats])
            xm, xs, ym, beta, lam, rmse, r2, fixed = _fit_prior_ridge(X, y, beta0, scales, signs)
            src = "경험칙 계수 그대로(데이터 보정 효과 없음)" if not np.isfinite(lam) else "공장 데이터 + 경험칙 사전정보"
            models[tgt] = RidgeModel(tgt, product, feats, xm, xs, ym, beta, beta0, lam, rmse, r2, len(d), src,
                                     tuple(f for f, fx in zip(feats, fixed) if fx), n_ex)
            continue
        level = DEFAULT_LEVEL.get(product, {}).get(tgt, np.nan)
        if len(d) >= 3:
            level = float(d[tgt].mean())
        if not np.isfinite(level):
            continue                                   # 해당 재령 시험을 하지 않는 품종(예: 1종 1일 강도)
        base = DEFAULT_INPUTS.get(product, DEFAULT_INPUTS["1종"])
        xm = np.array([base["so3"] if f == "so3" else (0.0 if f == "so3dev2" else base[f]) for f in feats], float)
        if len(df):
            for i, f in enumerate(feats):
                if f in df and df[f].notna().sum() >= 3:
                    xm[i] = float(df[f].mean())
        models[tgt] = RidgeModel(tgt, product, feats, xm, np.ones(len(feats)), float(level), beta0, beta0,
                                 float("inf"), DEFAULT_RMSE[tgt], float("nan"), int(len(d)), "경험칙(데이터 부족 — 추정)")
    sm = StrengthModels(product, models, so3_opt, df if len(df) else pd.DataFrame(columns=INPUT_KEYS + ["timestamp"]))
    sm.registry = registry
    return sm


def backtest(sm: StrengthModels, target: str = "phy_s28") -> pd.DataFrame:
    """실측 로트별 예측 vs 실측(학습 계수 적용 — 적합도 확인용)."""
    m = sm.models.get(target)
    d = sm.train
    if m is None or len(d) == 0 or target not in d:
        return pd.DataFrame()
    rows = []
    for _, r in d.dropna(subset=[target]).iterrows():
        feats = {f: r.get(f, np.nan) for f in m.features}
        rows.append({"timestamp": r["timestamp"], "실측": r[target], "예측": m.predict_row(feats),
                     "광물 출처": r.get("phase_src", "")})
    return pd.DataFrame(rows)


# ── 제어 레버·최적화 ────────────────────────────────────────────────────
LEVERS: dict[str, dict] = {
    "blaine": {"label": "분말도", "unit": "cm²/g", "step": 100.0, "cost": 1.0, "range": (-500.0, 500.0),
               "how": "세퍼레이터 회전수↑·밀 투입량↓(분말도↑) / 반대(분말도↓)"},
    "so3": {"label": "SO₃(석고 투입)", "unit": "%", "step": 0.1, "cost": 0.4, "range": (-0.5, 0.5),
            "how": "석고 정량공급기 설정 변경(최적 SO₃ 시험으로 확인)"},
    "ls": {"label": "석회석 혼합률", "unit": "%p", "step": 1.0, "cost": 1.0, "abs": (0.0, 5.0),
           "how": "석회석 정량공급기 설정 변경(KS 소량 혼합성분 한도 이내)"},
    "alite": {"label": "알라이트(LSF·소성)", "unit": "%p", "step": 1.0, "cost": 1.5, "range": (-4.0, 4.0),
              "how": "생료 LSF 목표 조정(+1 LSF ≈ 알라이트 +2~3%p, 추정)과 소성 강화 병행"},
    "c3a": {"label": "C₃A(IM 조정)", "unit": "%p", "step": 0.5, "cost": 1.0, "range": (-1.5, 1.5),
            "how": "철질원 비율 조정으로 IM 변경(IM↑ → C₃A↑)"},
    "fcao": {"label": "자유석회(소성 조건)", "unit": "%p", "step": 0.1, "cost": 0.8, "range": (-0.6, 0.4),
             "how": "소성대 온도·연료·O₂ 조정(f-CaO 목표 관리)"},
    "mill_temp": {"label": "밀 출구 온도", "unit": "℃", "step": 5.0, "cost": 0.3, "range": (-20.0, 10.0),
                  "how": "밀 내 살수·냉각 공기량 조정(석고 탈수 방지)"},
}
COUPLING = {"alite": {"belite": -0.75}, "c3a": {"c4af": -0.70}}


def apply_levers(base: dict, deltas: dict) -> dict:
    out = dict(base)
    for k, d in deltas.items():
        lev = LEVERS[k]
        if "abs" in lev:
            out[k] = d
        else:
            out[k] = base[k] + d
        for other, ratio in COUPLING.get(k, {}).items():
            if "abs" not in lev:
                out[other] = base[other] + ratio * d
    return out


@dataclass
class ControlPlan:
    deltas: dict                    # 레버별 변경량(석회석은 절대값)
    before: dict
    after: dict
    pred_before: dict
    pred_after: dict
    goals: dict
    unmet: list[str]
    single_lever: pd.DataFrame
    messages: list[str]

    def lever_table(self) -> pd.DataFrame:
        rows = []
        for k, lev in LEVERS.items():
            if k not in self.deltas:
                continue
            b, a = self.before[k], self.after[k]
            if abs(a - b) < 1e-9:
                continue
            rows.append({"레버": lev["label"], "현재": b, "권장": a, "변경": a - b, "단위": lev["unit"], "실행 방법": lev["how"]})
        return pd.DataFrame(rows)

    def outcome_table(self) -> pd.DataFrame:
        rows = []
        for t, (lo, hi) in self.goals.items():
            rows.append({"항목": TARGETS[t]["label"], "목표": _goal_text(lo, hi), "현재 예측": self.pred_before.get(t),
                         "조정 후 예측": self.pred_after.get(t),
                         "판정": "✅ 충족" if t not in self.unmet else "⚠️ 미충족"})
        return pd.DataFrame(rows)


def _goal_text(lo, hi) -> str:
    if lo is not None and hi is not None:
        return f"{lo:g} ~ {hi:g}"
    return f"≥ {lo:g}" if lo is not None else (f"≤ {hi:g}" if hi is not None else "-")


def optimize_controls(sm: StrengthModels, base: dict, goals: dict[str, tuple[float | None, float | None]],
                      levers: list[str] | None = None, safety_z: float = 0.0,
                      ls_max: float = 5.0) -> ControlPlan:
    """목표(goals: target → (하한, 상한))를 최소 변경 비용으로 만족하는 레버 조합.

    safety_z > 0 이면 목표를 z × RMSE 만큼 안쪽으로 당겨(예측 불확실성 반영) 계산한다.
    """
    levers = [k for k in (levers or list(LEVERS)) if k in LEVERS]
    goals = {t: g for t, g in goals.items() if t in sm.models}
    msgs: list[str] = []
    pred0 = sm.predict_values(base)
    if not goals:
        return ControlPlan({}, base, base, pred0, pred0, {}, [], pd.DataFrame(), ["목표가 지정되지 않았습니다."])

    def bounds_for(k):
        lev = LEVERS[k]
        if "abs" in lev:
            return (lev["abs"][0], min(lev["abs"][1], ls_max))
        return lev["range"]

    x0 = np.array([base[k] if "abs" in LEVERS[k] else 0.0 for k in levers], float)
    bnds = [bounds_for(k) for k in levers]
    x0 = np.array([float(np.clip(v, lo, hi)) for v, (lo, hi) in zip(x0, bnds)])
    scale = np.array([LEVERS[k]["step"] for k in levers])
    cost = np.array([LEVERS[k]["cost"] for k in levers])
    ref = np.array([base[k] if "abs" in LEVERS[k] else 0.0 for k in levers])

    def unpack(v):
        return dict(zip(levers, v))

    def violations(v) -> dict[str, float]:
        p = sm.predict_values(apply_levers(base, unpack(v)))
        out = {}
        for t, (lo, hi) in goals.items():
            r = sm.models[t].rmse
            g = 0.0
            if lo is not None:
                g = max(g, (lo + safety_z * r) - p[t])
            if hi is not None:
                g = max(g, p[t] - (hi - safety_z * r))
            out[t] = g / r
        return out

    def solve(active: np.ndarray, start: np.ndarray) -> np.ndarray:
        def obj(v_act):
            v = ref.copy()
            v[active] = v_act
            z = (v - ref) / scale
            # 부드러운 L1(변경 레버 수 최소화) + 약한 L2(변경 폭 최소화)
            c = float(np.sum(cost * (np.sqrt(z ** 2 + 0.01) - 0.1 + 0.1 * z ** 2)))
            return c + 400.0 * sum(g ** 2 for g in violations(v).values())
        res = minimize(obj, start[active], method="L-BFGS-B", bounds=[bnds[i] for i in np.where(active)[0]])
        v = ref.copy()
        v[active] = res.x
        return v

    active = np.ones(len(levers), bool)
    v = solve(active, x0)
    # 운전상 의미 없는 작은 변경(0.25 단계 미만)은 빼고 남은 레버로 다시 계산
    for _ in range(3):
        small = active & (np.abs(v - ref) < 0.25 * scale)
        if not small.any():
            break
        active &= ~small
        v = solve(active, v) if active.any() else ref.copy()
    deltas = unpack(v)
    after = apply_levers(base, deltas)
    pred1 = sm.predict_values(after)
    unmet = [t for t, g in violations(v).items() if g > 0.05]
    if unmet:
        msgs.append("레버 조정 범위 안에서 충족할 수 없는 목표: " + ", ".join(TARGETS[t]["label"] for t in unmet)
                    + " — 범위를 넓히거나 원료·소성 조건(클링커 품질) 개선이 필요합니다.")
    single = single_lever_table(sm, base, goals, levers, ls_max)
    return ControlPlan(deltas, base, after, pred0, pred1, goals, unmet, single, msgs)


def lever_effect(sm: StrengthModels, base: dict, lever: str) -> dict[str, float]:
    """레버 1단계(step) 변경 시 목표별 예측 변화(결합·2차항 반영)."""
    lev = LEVERS[lever]
    step = lev["step"] if "abs" not in lev else -lev["step"]     # 석회석은 '감량'을 1단계로 본다
    d = {lever: (base[lever] + step) if "abs" in lev else step}
    p0 = sm.predict_values(base)
    p1 = sm.predict_values(apply_levers(base, d))
    return {t: p1[t] - p0[t] for t in p0}


def single_lever_table(sm: StrengthModels, base: dict, goals: dict, levers: list[str], ls_max: float = 5.0) -> pd.DataFrame:
    """목표 차이를 레버 하나만으로 메우려면 얼마나 바꿔야 하는가(선형 근사)."""
    pred = sm.predict_values(base)
    rows = []
    for t, (lo, hi) in goals.items():
        gap = 0.0
        if lo is not None and pred[t] < lo:
            gap = lo - pred[t]
        elif hi is not None and pred[t] > hi:
            gap = hi - pred[t]
        if gap == 0.0:
            continue
        for k in levers:
            eff = lever_effect(sm, base, k)[t]
            lev = LEVERS[k]
            if abs(eff) < 1e-9:
                continue
            steps = gap / eff
            change = steps * (lev["step"] if "abs" not in lev else -lev["step"])
            if "abs" in lev:
                lo_b, hi_b = lev["abs"][0] - base[k], min(lev["abs"][1], ls_max) - base[k]
            else:
                lo_b, hi_b = lev["range"]
            if abs(change) > 3 * (hi_b - lo_b):
                continue                                 # 효과가 미미한 레버(예: 최적치 근처 SO₃)는 제외
            feasible = lo_b - 1e-9 <= change <= hi_b + 1e-9
            rows.append({"목표 항목": TARGETS[t]["label"], "차이": gap, "레버": lev["label"], "필요 변경": change,
                         "단위": lev["unit"], "조정 범위 내": "예" if feasible else "아니오(범위 초과)"})
    return pd.DataFrame(rows)


# ── 제어 솔루션 지식베이스 ─────────────────────────────────────────────
@dataclass(frozen=True)
class ControlAction:
    lever: str
    title: str
    mechanism: str
    effect: str          # 정량 효과(경험칙·추정 표기)
    side_effects: str
    how: str
    verify: str
    basis: str


CONTROL_KB: dict[str, dict] = {
    "early_up": {"title": "초기강도(1·3일) 상향", "actions": (
        ControlAction("blaine", "분말도 상향(입도 미세화)",
                      "수화 반응 표면적이 늘어 1~3일 수화량이 증가한다.",
                      "Blaine +100 cm²/g 당 3일 강도 약 +1~1.5 MPa (경험칙, 추정)",
                      "밀 생산성 저하(100 cm²/g 당 약 4~6%, 경험칙)·전력 원단위↑, 물 요구량·수화열↑, 응결 단축",
                      "세퍼레이터 회전수↑, 밀 투입량↓, 분쇄조제 사용", "Blaine·45μm 잔사·레이저 PSD, 1·3일 강도", "이론+경험칙"),
        ControlAction("so3", "SO₃(석고) 최적화",
                      "C₃A·알칼리·분말도에 맞는 석고량이어야 초기 수화가 정상 진행된다. 조기강도 최적 SO₃는 28일 최적보다 다소 높은 경향.",
                      "최적치에서 ±0.3%p 벗어나면 강도 수 % 저하 가능(추정)",
                      "과다 시 응결 지연·지연 팽창, 부족 시 급결·강도 저하",
                      "석고 투입량 단계 변경 시험(최적 SO₃ 시험, ASTM C563 개념)", "SO₃ 수준별 1·3·28일 강도 비교", "문헌+경험칙"),
        ControlAction("ls", "석회석 혼합률 축소",
                      "석회석은 클링커를 희석한다(미분 충전 효과로 일부 상쇄).",
                      "1%p 축소 시 3일 강도 약 +0.3 MPa (경험칙, 추정)",
                      "클링커 원단위·원가·CO₂ 증가", "석회석 공급기 설정 하향", "LOI·CO₂ 분석으로 혼합률 확인, 강도", "경험칙"),
        ControlAction("c3a", "C₃A 상향(IM↑)",
                      "C₃A·알칼리 황산염은 1일 강도에 기여한다.",
                      "C₃A +1%p 당 1일 강도 약 +0.3 MPa (경험칙, 추정)",
                      "응결 단축·위응결 위험, 석고 요구량↑, 황산염 저항성↓",
                      "철질원 비율↓로 IM 상향", "XRD C₃A, 응결시간, 최적 SO₃ 재확인", "문헌+경험칙"),
        ControlAction("alite", "알라이트 상향(LSF↑·소성 강화)",
                      "C₃S는 3~28일 강도의 주 기여 광물이다.",
                      "알라이트 +1%p 당 3일 약 +0.25, 28일 약 +0.3 MPa (경험칙, 추정)",
                      "난소성(f-CaO↑)·연료 사용량↑·내화물 부하", "생료 LSF 목표 +0.5~1 단계 상향, 소성대 온도 확보",
                      "XRD 알라이트, f-CaO, 3·28일 강도", "이론+경험칙"),
        ControlAction("", "분쇄조제·강도증진제(TEA 계열)",
                      "트리에탄올아민(TEA)은 C₃A·C₄AF 수화를 촉진해 초기강도를 높이는 것으로 알려져 있다.",
                      "제품·투입량에 따라 상이 — 실험실 비교시험 필요(추정)",
                      "원가↑, 과량 시 응결 이상", "공급사 권장량 기준 실험실·실기 비교시험", "1·3일 강도, 응결", "문헌"),
        ControlAction("", "클링커 급랭(냉각기 운전)",
                      "급랭은 알라이트 분해를 막고 C₃A 결정을 미세하게 해 반응성을 높인다.",
                      "정량 효과는 공장별 상이(추정)", "냉각기 동력↑", "냉각기 1단 풍량·그레이트 속도 조정",
                      "클링커 현미경 관찰, 출구 클링커 온도", "문헌"),
    )},
    "late_up": {"title": "장기강도(28일) 상향", "actions": (
        ControlAction("alite", "알라이트 상향(LSF↑·소성 강화)", "C₃S가 28일 강도를 주도한다.",
                      "알라이트 +1%p 당 28일 약 +0.3~0.4 MPa (경험칙, 추정)", "난소성·연료↑",
                      "생료 LSF 목표 상향, 소성대 온도 확보", "XRD 알라이트·f-CaO, 28일 강도", "이론+경험칙"),
        ControlAction("fcao", "자유석회 안정화(소성 관리)", "f-CaO가 높으면 결합되지 못한 CaO만큼 C₃S가 줄고 팽창 위험이 커진다.",
                      "f-CaO 1%p 감소 시 28일 약 +1 MPa (경험칙, 추정)", "과소성 시 연료 낭비·분쇄성 저하",
                      "f-CaO 0.8~1.5% 목표로 소성 피드백 운전", "f-CaO(2시간), 리터중량", "경험칙"),
        ControlAction("ls", "석회석 혼합률 축소", "클링커 희석 감소.", "1%p 축소 시 28일 약 +0.4 MPa (경험칙, 추정)",
                      "원가·CO₂ 증가", "석회석 공급기 설정 하향", "혼합률·28일 강도", "경험칙"),
        ControlAction("", "알칼리 저감(원료·연료 관리, 바이패스)", "알칼리는 조기강도를 높이지만 28일 이후 강도 발현을 저해하는 경향이 있다.",
                      "Na₂Oeq 0.1%p 감소 시 28일 약 +0.5 MPa (경험칙, 추정)", "바이패스 운전 시 열손실·더스트 처리",
                      "고알칼리 원료·대체연료 투입 관리, 바이패스 추기량 조정", "클링커 K₂O·Na₂O, 28일 강도", "문헌+경험칙"),
        ControlAction("so3", "SO₃ 최적화(28일 기준)", "28일 강도 최적 SO₃에서 벗어나면 강도가 낮아진다.",
                      "최적치 이탈 0.3%p 시 수 % 저하 가능(추정)", "응결 변화", "최적 SO₃ 시험으로 목표 재설정",
                      "SO₃ 수준별 28일 강도", "문헌+경험칙"),
        ControlAction("", "강도증진제(TIPA 계열)", "트리이소프로판올아민(TIPA)은 페라이트상 수화를 도와 후기강도 향상에 쓰인다.",
                      "실험실 비교시험 필요(추정)", "원가↑", "공급사 권장량 기준 비교시험", "7·28일 강도", "문헌"),
        ControlAction("", "클링커 풍화(프리하이드레이션) 방지", "습기·고온에 노출된 클링커는 표면 수화로 강도 발현이 떨어진다.",
                      "공장별 상이(추정)", "-", "야적 클링커 사용 최소화·사일로 관리", "클링커 LOI, 강도", "경험칙"),
    )},
    "set_longer": {"title": "응결 지연(초결이 너무 빠를 때)", "actions": (
        ControlAction("so3", "석고(SO₃) 증량", "석고가 C₃A의 급격한 수화를 억제한다.",
                      "SO₃ +0.1%p 당 초결 약 +5~10분 (경험칙, 추정)", "과다 시 강도 저하·팽창",
                      "석고 공급기 설정 상향(KS SO₃ 상한 이내)", "SO₃, 초결·종결", "이론+경험칙"),
        ControlAction("mill_temp", "밀 출구 온도 관리", "고온에서 이수석고가 반수석고로 탈수되면 위응결(false set)이 생긴다.",
                      "공장별 상이 — 출구 120 ℃ 이하 관리 권장(경험칙)", "냉각 설비 동력·살수 관리",
                      "밀 내 살수, 냉각 공기량 증대, 시멘트 쿨러", "밀 출구 온도, 석고 형태(이수/반수) 분석, 위응결 시험", "문헌+경험칙"),
        ControlAction("c3a", "C₃A 저감(IM↓)", "C₃A가 적으면 초기 수화가 완만해진다.", "C₃A −1%p 당 초결 약 +6분 (경험칙, 추정)",
                      "조기강도 저하", "철질원 비율↑로 IM 하향", "XRD C₃A, 응결", "이론+경험칙"),
        ControlAction("blaine", "분말도 과다 억제", "분말도가 높을수록 수화가 빨라 응결이 짧아진다.",
                      "Blaine −100 cm²/g 당 초결 약 +5분 (경험칙, 추정)", "조기강도 저하", "세퍼레이터 회전수 조정",
                      "Blaine, 응결", "경험칙"),
    )},
    "set_shorter": {"title": "응결 단축(종결이 너무 늦을 때)", "actions": (
        ControlAction("so3", "석고(SO₃) 과다 해소", "석고가 과다하면 응결이 지연된다.", "SO₃ −0.1%p 당 종결 약 −5분 (경험칙, 추정)",
                      "부족 시 급결·강도 저하", "석고 공급기 설정 하향·정량성 점검", "SO₃, 응결", "이론+경험칙"),
        ControlAction("blaine", "분말도 상향", "수화가 빨라져 응결이 짧아진다.", "Blaine +100 cm²/g 당 종결 약 −6분 (경험칙, 추정)",
                      "생산성 저하", "세퍼레이터 회전수↑", "Blaine, 응결", "경험칙"),
        ControlAction("", "시험 조건 확인", "응결시간은 시험실 온도·습도·표준주도에 민감하다.", "-", "-",
                      "비카 시험 조건(온도 20±2 ℃·습도 50% 이상 등) 및 표준주도 확인", "재시험", "규격+경험칙"),
    )},
}


def needed_goals(pred: dict, goals: dict) -> list[str]:
    """미충족 목표 → 관련 솔루션 그룹(early_up / late_up / set_longer / set_shorter)."""
    keys = []
    for t, (lo, hi) in goals.items():
        p = pred.get(t)
        if p is None:
            continue
        if t in ("phy_s1", "phy_s3") and lo is not None and p < lo:
            keys.append("early_up")
        if t in ("phy_s7", "phy_s28") and lo is not None and p < lo:
            keys.append("late_up")
        if t in ("phy_ist", "phy_fst") and lo is not None and p < lo:
            keys.append("set_longer")
        if t in ("phy_ist", "phy_fst") and hi is not None and p > hi:
            keys.append("set_shorter")
    return list(dict.fromkeys(keys))


def default_goals(registry: SpecRegistry, product: str, models: dict, basis: str = "lsl") -> dict:
    """사내 관리기준으로 기본 목표 구성. basis='target' 이면 강도 목표 = 사내 목표값, 'lsl' 이면 사내 하한.
    응결은 항상 사내 하한~상한."""
    out = {}
    for t in TARGETS:
        if t not in models or t not in registry:
            continue
        lim = registry[t].limits_for(product)
        lo = lim.lsl if lim.lsl is not None else lim.ks_min
        hi = lim.usl if lim.usl is not None else lim.ks_max
        if t in ("phy_s1", "phy_s3", "phy_s7", "phy_s28"):
            hi = None
            if basis == "target" and lim.target is not None:
                lo = lim.target
        if lo is None and hi is None:
            continue
        out[t] = (lo, hi)
    return out


def solution_markdown(sm: StrengthModels, plan: ControlPlan, product: str) -> str:
    """규칙 기반 제어 솔루션(LLM 미사용 시 표시·LLM 입력 근거)."""
    lines = [f"### 규칙 기반 제어 솔루션 — {product}", ""]
    out = plan.outcome_table()
    if len(out):
        lines.append("| 항목 | 목표 | 현재 예측 | 조정 후 예측 | 판정 |")
        lines.append("|---|---|---|---|---|")
        for _, r in out.iterrows():
            lines.append(f"| {r['항목']} | {r['목표']} | {r['현재 예측']:.1f} | {r['조정 후 예측']:.1f} | {r['판정']} |")
        lines.append("")
    lt = plan.lever_table()
    if len(lt):
        lines.append("**권장 조정(최소 변경 조합, 예측 모델 기반 — 추정)**")
        for _, r in lt.iterrows():
            lines.append(f"- {r['레버']}: {r['현재']:.2f} → {r['권장']:.2f} {r['단위']} ({r['변경']:+.2f}) — {r['실행 방법']}")
        lines.append("")
    else:
        lines.append("- 현재 조건에서 목표를 충족하는 것으로 예측됩니다(조정 불필요).")
        lines.append("")
    for msg in plan.messages:
        lines.append(f"> ⚠️ {msg}")
    groups = needed_goals(plan.pred_before, plan.goals)
    for g in groups:
        kb = CONTROL_KB[g]
        lines.append(f"#### {kb['title']} — 실행 가능한 조치")
        for a in kb["actions"]:
            lines.append(f"- **{a.title}** ({a.basis}): {a.mechanism} 효과: {a.effect}. 부작용: {a.side_effects}. "
                         f"실행: {a.how}. 확인: {a.verify}.")
        lines.append("")
    m28 = sm.models.get("phy_s28")
    if m28 is not None:
        lines.append(f"※ 예측 모델: {m28.source}, 28일 강도 LOO RMSE {m28.rmse:.2f} MPa(학습 {m28.n}로트). "
                     "수치 효과는 경험칙·회귀 추정이며 실기 시험으로 확인해야 합니다.")
    return "\n".join(lines)
