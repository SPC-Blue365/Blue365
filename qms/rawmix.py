"""원료 배합 설계(조합 계산) · 클링커 성분 예측 · 생료→클링커 전환 검증.

배합 계산식 (근거: 물질수지 + Lea & Parker LSF, ASTM C150 Bogue)
-----------------------------------------------------------------
  x_i    원료 i의 건조 기준 배합비(합계 1)
  ox_ij  원료 i의 산화물 j 함량(%, 건조 기준),  L_i 원료 i의 강열감량(%)
  a      클링커 1 kg에 흡수되는 석탄회(kg) = 석탄 원단위(kg/t-clk)/1000 × 회분(%)/100 × 흡수율(%)/100
  D(x)   = Σ x_i·(1 − L_i/100)                                   (생료 1 kg 강열 후 잔량)
  클링커 산화물  C_j = (1 − a)·Σx_i·ox_ij / D + a·ash_j
  ⇔ C_j·D = Σ x_i·[(1 − a)·ox_ij + a·ash_j·(1 − L_i/100)] ≡ E_j(x)   ← x 에 대해 선형

  목표 모듈러스를 선형식으로 바꾸면(분모를 곱해 정리)
    LSF : 100·E_CaO − LSF_t·(2.8·E_SiO2 + 1.18·E_Al2O3 + 0.65·E_Fe2O3) = 0
    SM  : E_SiO2 − SM_t·(E_Al2O3 + E_Fe2O3) = 0
    IM  : E_Al2O3 − IM_t·E_Fe2O3 = 0
    C3S : 4.071·E_CaO − 7.600·E_SiO2 − 6.718·E_Al2O3 − 1.430·E_Fe2O3
          − (4.071·fCaO + 2.852·SO3_clk + C3S_t)·D = 0             (Bogue, A/F ≥ 0.64)
  각 식을 기준 배합에서의 분모로 나눠 '목표 단위 편차'로 만든 뒤
    - 최소자승(scipy.optimize.lsq_linear, 원료별 하한·상한·고정 반영)  또는
    - 원가 최소 LP(scipy.optimize.linprog, 목표 허용편차 내)
  로 푼다. 분모·SO3·f-CaO 는 해에 따라 바뀌므로 3회 반복 갱신한다.

  '생료 기준' 목표를 고르면 LSF·SM·IM 식에서 a = 0 (석탄회 미반영)으로 계산한다.

클링커 예측
  - 주성분: 위 물질수지. K2O·Na2O·SO3 는 잔류율(휘발·바이패스 손실)을 곱한다.
  - SO3: (원료 SO3 + 석탄 황분×2.5) × 잔류율
  - f-CaO: 공장 데이터로 학습한 소성성 회귀식(LSF·SM·생료 90μm 잔사·소성대 온도) 또는 경험식
  - XRD 광물: 같은 날 XRD 실측과 Bogue 계산값의 회귀(공장 데이터) — 없으면 Bogue 값을 그대로 사용

※ 기본 원료 성분·단가·킬른 계수는 예시값(추정)이다. 공장 원료 분석값으로 바꿔 사용해야 한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import linprog, lsq_linear

from . import chemistry as chem

OXIDES = ["SiO2", "Al2O3", "Fe2O3", "CaO", "MgO", "SO3", "K2O", "Na2O"]
CATEGORIES = ["석회석", "실리카원", "알루미나원", "철질원", "기타"]
MATERIAL_COLUMNS = ["use", "name", "category", *OXIDES, "LOI", "H2O", "Cr", "cost", "min", "max", "fixed"]
OXIDE_LABELS = {"SiO2": "SiO₂", "Al2O3": "Al₂O₃", "Fe2O3": "Fe₂O₃", "CaO": "CaO", "MgO": "MgO", "SO3": "SO₃",
                "K2O": "K₂O", "Na2O": "Na₂O"}
TARGET_KEYS = ["LSF", "SM", "IM", "C3S"]
TARGET_LABELS = {"LSF": "LSF", "SM": "SM", "IM": "IM", "C3S": "C₃S"}
# 최소자승 가중의 '1단위' (LSF 1 ≈ SM 0.05 ≈ IM 0.05 ≈ C3S 1%p 를 같은 무게로 본다)
UNIT = {"LSF": 1.0, "SM": 0.05, "IM": 0.05, "C3S": 1.0}
# 목표 달성 판정·원가 최소화의 허용 편차
TOL = {"LSF": 0.3, "SM": 0.02, "IM": 0.02, "C3S": 0.5}
DEC = {"LSF": 1, "SM": 2, "IM": 2, "C3S": 1}

ASH_DEFAULT = {"SiO2": 55.0, "Al2O3": 25.0, "Fe2O3": 7.0, "CaO": 5.0, "MgO": 1.5, "K2O": 1.0, "Na2O": 0.4}


def default_materials() -> pd.DataFrame:
    """예시 원료 5종(구분별 1종). 성분·단가는 예시값 — 공장 분석값으로 교체할 것."""
    rows = [
        # use, 이름, 구분, SiO2, Al2O3, Fe2O3, CaO, MgO, SO3, K2O, Na2O, LOI, 수분, Cr(mg/kg), 단가(원/t 습윤), 하한, 상한, 고정
        (True, "석회석", "석회석", 4.0, 1.0, 0.5, 52.0, 1.2, 0.05, 0.20, 0.05, 41.5, 3.0, 14, 7000, 70, 92, None),
        (True, "규석", "실리카원", 88.0, 5.0, 1.5, 1.0, 0.3, 0.02, 1.00, 0.30, 2.0, 5.0, 20, 25000, 0, 15, None),
        (True, "점토(셰일)", "알루미나원", 60.0, 16.0, 6.0, 3.0, 2.0, 0.10, 2.50, 0.80, 8.0, 12.0, 90, 15000, 0, 20, None),
        (True, "철광석", "철질원", 15.0, 3.0, 70.0, 2.0, 1.0, 0.05, 0.10, 0.05, 3.0, 8.0, 300, 60000, 0, 5, None),
        (True, "석탄재(플라이애시)", "기타", 52.0, 24.0, 7.0, 5.0, 1.5, 0.80, 1.20, 0.60, 4.0, 15.0, 190, 5000, 0, 10, None),
    ]
    df = pd.DataFrame(rows, columns=MATERIAL_COLUMNS)
    df["fixed"] = df["fixed"].astype(float)
    return df


@dataclass
class KilnParams:
    """소성 조건(석탄회 흡수·휘발 성분 잔류). 기본값은 예시(추정) — 공장 실적으로 보정."""
    coal_kg_per_t: float = 115.0     # 석탄 원단위(kg/t-클링커)
    coal_ash: float = 14.0           # 석탄 회분(%, 건조)
    ash_absorption: float = 100.0    # 회분의 클링커 흡수율(%) — 바이패스·더스트 손실 시 100 미만
    coal_s: float = 1.0              # 석탄 황분(%)
    so3_retention: float = 60.0      # SO3 클링커 잔류율(%)
    k2o_retention: float = 85.0      # K2O 잔류율(%) — 바이패스 운전 시 낮아짐
    na2o_retention: float = 95.0     # Na2O 잔류율(%)
    fcao: float = 1.0                # 예상 f-CaO(%) — 소성 모델 미사용 시
    r90: float = 13.0                # 생료 90μm 잔사(%) — f-CaO 예측 입력
    bzt: float = 1420.0              # 소성대 온도(℃) — f-CaO 예측 입력
    ash: dict = field(default_factory=lambda: dict(ASH_DEFAULT))

    @property
    def a(self) -> float:
        """클링커 1 kg당 흡수 석탄회(kg)."""
        return self.coal_kg_per_t / 1000.0 * self.coal_ash / 100.0 * self.ash_absorption / 100.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "KilnParams":
        if not d:
            return cls()
        keys = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class MixTargets:
    basis: str = "clinker"           # clinker: 클링커 기준(석탄회 반영) | raw: 생료 기준
    values: dict = field(default_factory=lambda: {"LSF": 95.0, "SM": 2.50, "IM": 1.60, "C3S": 57.0})
    enabled: dict = field(default_factory=lambda: {"LSF": True, "SM": True, "IM": True, "C3S": False})
    weights: dict = field(default_factory=lambda: {"LSF": 1.0, "SM": 1.0, "IM": 1.0, "C3S": 1.0})
    c3s_basis: str = "bogue"         # bogue | xrd (XRD 알라이트 목표 → 보정식으로 Bogue 목표 환산)

    def active(self) -> list[str]:
        return [k for k in TARGET_KEYS if self.enabled.get(k) and self.values.get(k) is not None]


# ── f-CaO(소성성) 모델 · XRD 보정식 ──────────────────────────────────────
FCAO_FEATURES = ["lsf", "sm", "r90", "bzt"]
FCAO_DEFAULT = {"intercept": 1.0, "lsf": 0.25, "sm": 0.60, "r90": 0.07, "bzt": -0.025}   # 경험칙(추정)
FCAO_CENTER = {"lsf": 95.0, "sm": 2.5, "r90": 13.0, "bzt": 1420.0}


@dataclass
class FcaoModel:
    coef: dict                        # intercept + 중심화된 계수 (x − FCAO_CENTER)
    rmse: float
    n: int
    r2: float
    source: str                       # "공장 데이터 학습" | "경험식(기본값)"

    def predict(self, lsf: float, sm: float, r90: float, bzt: float) -> float:
        v = self.coef["intercept"]
        for k, val in zip(FCAO_FEATURES, (lsf, sm, r90, bzt)):
            v += self.coef[k] * (val - FCAO_CENTER[k])
        return float(np.clip(v, 0.2, 5.0))

    def equation(self) -> str:
        names = {"lsf": "(LSF−95)", "sm": "(SM−2.5)", "r90": "(R90−13)", "bzt": "(소성대온도−1420)"}
        t = [f"{self.coef['intercept']:.2f}"]
        for k in FCAO_FEATURES:
            c = self.coef[k]
            t.append(f"{'+' if c >= 0 else '−'} {abs(c):.3f}×{names[k]}")
        return "f-CaO = " + " ".join(t)


def default_fcao_model() -> FcaoModel:
    return FcaoModel(dict(FCAO_DEFAULT), rmse=0.35, n=0, r2=float("nan"), source="경험식(기본값)")


def _fcao_training_frame(store) -> pd.DataFrame:
    clk = store.tables.get("clinker", pd.DataFrame())
    if len(clk) == 0 or "clk_lsf" not in clk:
        return pd.DataFrame()
    d = clk[["timestamp", "clk_fcao", "clk_lsf", "clk_sm"]].dropna().sort_values("timestamp")
    rm = store.tables.get("raw_meal", pd.DataFrame())
    if len(rm) and "rm_r90" in rm:
        r = rm[["timestamp", "rm_r90"]].dropna().sort_values("timestamp").copy()
        r["timestamp"] = r["timestamp"] + pd.Timedelta(hours=2)          # 생료 → 클링커 약 2시간
        d = pd.merge_asof(d, r, on="timestamp", direction="backward", tolerance=pd.Timedelta(hours=4))
    kiln = store.tables.get("kiln", pd.DataFrame())
    if len(kiln) and "kiln_bzt" in kiln:
        k = kiln.set_index("timestamp")["kiln_bzt"].sort_index().rolling("4h").mean().reset_index()
        d = pd.merge_asof(d, k, on="timestamp", direction="backward", tolerance=pd.Timedelta(hours=2))
    return d


def fit_fcao_model(store, min_n: int = 30) -> FcaoModel:
    """클링커 f-CaO ~ LSF + SM + 생료 R90(2h 전) + 소성대 온도(0~4h 평균) 회귀. 데이터 부족 시 경험식."""
    d = _fcao_training_frame(store)
    need = ["clk_fcao", "clk_lsf", "clk_sm", "rm_r90", "kiln_bzt"]
    if len(d) == 0 or any(c not in d for c in need):
        return default_fcao_model()
    d = d.dropna(subset=need)
    if len(d) < min_n:
        return default_fcao_model()
    X = np.column_stack([d["clk_lsf"] - 95.0, d["clk_sm"] - 2.5, d["rm_r90"] - 13.0, d["kiln_bzt"] - 1420.0])
    y = d["clk_fcao"].to_numpy(float)
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    hat = np.einsum("ij,jk,ik->i", A, np.linalg.pinv(A.T @ A), A)
    loo = (y - yhat) / np.clip(1 - hat, 1e-6, None)
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-9
    return FcaoModel({"intercept": float(coef[0]), **{k: float(c) for k, c in zip(FCAO_FEATURES, coef[1:])}},
                     rmse=float(np.sqrt(np.mean(loo ** 2))), n=len(d), r2=1 - float(np.sum((y - yhat) ** 2)) / ss_tot,
                     source="공장 데이터 학습")


XRD_PHASES = {"alite": "C3S", "belite": "C2S", "c3a": "C3A", "c4af": "C4AF"}


@dataclass
class XrdMap:
    """XRD 실측 = b0 + b1 × Bogue 계산값 (광물별). source='Bogue 그대로' 이면 항등식."""
    coef: dict                        # phase -> (b0, b1)
    rmse: dict
    n: int
    source: str

    def apply(self, bogue: dict, fcao: float | None = None, mgo: float | None = None) -> dict:
        out = {}
        for ph, bk in XRD_PHASES.items():
            b0, b1 = self.coef.get(ph, (0.0, 1.0))
            out[ph] = float(max(b0 + b1 * float(bogue[bk]), 0.0))
        b0, b1 = self.coef.get("fcao", (0.0, 1.0))
        out["fcao"] = float(max(b0 + b1 * fcao, 0.0)) if fcao is not None else float("nan")
        b0, b1 = self.coef.get("periclase", (-1.6, 1.0))
        out["periclase"] = float(max(b0 + b1 * mgo, 0.05)) if mgo is not None else float("nan")
        return out

    def bogue_c3s_for_alite(self, alite: float) -> float:
        b0, b1 = self.coef.get("alite", (0.0, 1.0))
        return (alite - b0) / b1 if b1 else alite


def identity_xrd_map() -> XrdMap:
    coef = {ph: (0.0, 1.0) for ph in XRD_PHASES} | {"fcao": (0.0, 1.0), "periclase": (-1.6, 1.0)}
    return XrdMap(coef, {}, 0, "Bogue 그대로(XRD 데이터 없음)")


def xrd_pairs(store) -> pd.DataFrame:
    """일별 XRD 실측과 같은 날 클링커 XRF 기반 Bogue 계산값 짝."""
    xrd = store.tables.get("xrd", pd.DataFrame())
    clk = store.tables.get("clinker", pd.DataFrame())
    if len(xrd) == 0 or len(clk) == 0 or "clk_c3s" not in clk:
        return pd.DataFrame()
    daily = clk.set_index("timestamp")[["clk_c3s", "clk_c2s", "clk_c3a", "clk_c4af", "clk_fcao", "clk_mgo"]]
    daily = daily.resample("1D").mean()
    x = xrd.copy()
    x["day"] = x["timestamp"].dt.normalize()
    return x.merge(daily, left_on="day", right_index=True, how="inner")


def fit_xrd_map(store, min_n: int = 10) -> XrdMap:
    d = xrd_pairs(store)
    if len(d) < min_n:
        return identity_xrd_map()
    pairs = {"alite": ("xrd_alite", "clk_c3s"), "belite": ("xrd_belite", "clk_c2s"), "c3a": ("xrd_c3a", "clk_c3a"),
             "c4af": ("xrd_c4af", "clk_c4af"), "fcao": ("xrd_fcao", "clk_fcao"), "periclase": ("xrd_periclase", "clk_mgo")}
    coef, rmse = {}, {}
    n = 0
    for ph, (yc, xc) in pairs.items():
        if yc not in d or xc not in d:
            continue
        sub = d[[yc, xc]].dropna()
        if len(sub) < min_n or sub[xc].std() < 1e-6:
            continue
        b1, b0 = np.polyfit(sub[xc], sub[yc], 1)
        coef[ph] = (float(b0), float(b1))
        rmse[ph] = float(np.sqrt(np.mean((sub[yc] - (b0 + b1 * sub[xc])) ** 2)))
        n = max(n, len(sub))
    if "alite" not in coef:
        return identity_xrd_map()
    base = identity_xrd_map().coef
    return XrdMap(base | coef, rmse, n, "공장 데이터 학습(XRD↔Bogue 회귀)")


# ── 배합 → 생료 → 클링커 ────────────────────────────────────────────────
def _clean(mats: pd.DataFrame) -> pd.DataFrame:
    df = mats.copy()
    for c in MATERIAL_COLUMNS:
        if c not in df:
            df[c] = {"use": True, "name": "", "category": "기타", "min": 0.0, "max": 100.0}.get(c, 0.0 if c != "fixed" else np.nan)
    for c in [*OXIDES, "LOI", "H2O", "Cr", "cost", "min", "max", "fixed"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in [*OXIDES, "LOI", "H2O", "Cr", "cost"]:
        df[c] = df[c].fillna(0.0)
    df["min"] = df["min"].fillna(0.0).clip(0, 100)
    df["max"] = df["max"].fillna(100.0).clip(0, 100)
    df["use"] = df["use"].fillna(False).astype(bool)
    return df.reset_index(drop=True)


def raw_meal_composition(mats: pd.DataFrame, x: np.ndarray) -> dict:
    """건조 생료 조성(%) — x 는 사용 원료 배합비(합계 1)."""
    ox = mats[OXIDES].to_numpy(float)
    comp = {o: float(v) for o, v in zip(OXIDES, x @ ox)}
    comp["LOI"] = float(x @ mats["LOI"].to_numpy(float))
    return comp


def predict_clinker(mats: pd.DataFrame, x: np.ndarray, kp: KilnParams, fcao: float | None = None,
                    fcao_model: FcaoModel | None = None, xrd_map: XrdMap | None = None) -> dict:
    """배합비 → 생료 → 클링커 화학·모듈러스·Bogue·액상량·(XRD 예측). fcao 를 주지 않으면 모델/기본값 사용."""
    mats = _clean(mats)
    x = np.asarray(x, float)
    raw = raw_meal_composition(mats, x)
    D = 1.0 - raw["LOI"] / 100.0
    a = kp.a
    ash = kp.ash
    clk = {}
    for o in ("SiO2", "Al2O3", "Fe2O3", "CaO", "MgO"):
        clk[o] = (1 - a) * raw[o] / D + a * ash.get(o, 0.0)
    clk["K2O"] = kp.k2o_retention / 100 * ((1 - a) * raw["K2O"] / D + a * ash.get("K2O", 0.0))
    clk["Na2O"] = kp.na2o_retention / 100 * ((1 - a) * raw["Na2O"] / D + a * ash.get("Na2O", 0.0))
    clk["SO3"] = kp.so3_retention / 100 * ((1 - a) * raw["SO3"] / D + kp.coal_kg_per_t * kp.coal_s * 0.0025)
    lsf = float(chem.lsf(clk["CaO"], clk["SiO2"], clk["Al2O3"], clk["Fe2O3"]))
    sm = float(chem.silica_modulus(clk["SiO2"], clk["Al2O3"], clk["Fe2O3"]))
    im = float(chem.iron_modulus(clk["Al2O3"], clk["Fe2O3"]))
    fcao_src = "입력값"
    if fcao is None:
        if fcao_model is not None:
            fcao = fcao_model.predict(lsf, sm, kp.r90, kp.bzt)
            fcao_src = fcao_model.source
        else:
            fcao = kp.fcao
    ph = chem.bogue(clk["CaO"], clk["SiO2"], clk["Al2O3"], clk["Fe2O3"], clk["SO3"], fcao)
    out = {
        "raw": raw, "clinker": clk, "a": a, "D": D,
        "raw_lsf": float(chem.lsf(raw["CaO"], raw["SiO2"], raw["Al2O3"], raw["Fe2O3"])),
        "raw_sm": float(chem.silica_modulus(raw["SiO2"], raw["Al2O3"], raw["Fe2O3"])),
        "raw_im": float(chem.iron_modulus(raw["Al2O3"], raw["Fe2O3"])),
        "LSF": lsf, "SM": sm, "IM": im, "fcao": float(fcao), "fcao_source": fcao_src,
        "C3S": float(ph["C3S"]), "C2S": float(ph["C2S"]), "C3A": float(ph["C3A"]), "C4AF": float(ph["C4AF"]),
        "liquid": float(chem.liquid_phase_1450(clk["Al2O3"], clk["Fe2O3"], clk["MgO"], clk["K2O"], clk["Na2O"])),
        "na2oeq": float(chem.na2o_eq(clk["Na2O"], clk["K2O"])),
        # 생료(건조) t / 클링커 t
        "kiln_factor": (1 - a) / D,
    }
    out["BI"] = float(chem.burnability_index(out["C3S"], out["C3A"], out["C4AF"]))
    xm = xrd_map or identity_xrd_map()
    out["xrd"] = xm.apply(ph, fcao, clk["MgO"])
    out["xrd_source"] = xm.source
    return out


def wet_ratios(mats: pd.DataFrame, x: np.ndarray) -> np.ndarray:
    """건조 배합비 → 습윤(정량공급기 설정) 배합비(합계 1)."""
    h2o = np.clip(mats["H2O"].to_numpy(float), 0, 95) / 100.0
    w = np.asarray(x, float) / (1 - h2o)
    return w / w.sum() if w.sum() > 0 else w


# ── 배합 최적화 ─────────────────────────────────────────────────────────
@dataclass
class MixResult:
    names: list[str]
    x: np.ndarray                     # 건조 배합비(합계 1, 사용 원료 순)
    wet: np.ndarray                   # 습윤 배합비
    clinker: dict                     # predict_clinker 결과
    achieved: dict                    # 목표 항목별 달성값(목표 기준)
    deviation: dict                   # 달성값 − 목표
    feasible: bool
    mode: str
    messages: list[str]
    cost_per_t_clk: float             # 원/t-클링커 (원료비만)
    active_bounds: list[str]
    mats: pd.DataFrame                # 계산에 사용한 원료(사용 원료만)

    def table(self) -> pd.DataFrame:
        kf = self.clinker["kiln_factor"]
        h2o = self.mats["H2O"].to_numpy(float) / 100
        dry_kg = self.x * kf * 1000
        return pd.DataFrame({
            "원료": self.names, "구분": self.mats["category"].tolist(),
            "건조 배합비(%)": self.x * 100, "습윤 배합비(%)": self.wet * 100,
            "건조 투입량(kg/t-clk)": dry_kg, "습윤 투입량(kg/t-clk)": dry_kg / (1 - h2o),
            "하한(%)": self.mats["min"].to_numpy(float), "상한(%)": self.mats["max"].to_numpy(float),
        })


def _target_value(cl: dict, key: str, basis: str) -> float:
    if basis == "raw" and key in ("LSF", "SM", "IM"):
        return cl[{"LSF": "raw_lsf", "SM": "raw_sm", "IM": "raw_im"}[key]]
    return cl[key]


def _rows(mats: pd.DataFrame, targets: MixTargets, kp: KilnParams, ref: dict, xrd_map: XrdMap | None):
    """목표별 선형 계수 행(정규화 전)과 정규화 분모."""
    ox = mats[OXIDES].to_numpy(float)
    loi = mats["LOI"].to_numpy(float) / 100.0
    a_clk = kp.a
    idx = {o: OXIDES.index(o) for o in OXIDES}

    def e(a: float) -> dict:
        return {o: (1 - a) * ox[:, idx[o]] + a * kp.ash.get(o, 0.0) * (1 - loi) for o in ("SiO2", "Al2O3", "Fe2O3", "CaO")}

    rows, scales, keys = [], [], []
    for k in targets.active():
        t = float(targets.values[k])
        a = 0.0 if (targets.basis == "raw" and k != "C3S") else a_clk
        E = e(a)
        D = 1 - loi
        if k == "LSF":
            g = 100 * E["CaO"] - t * (2.8 * E["SiO2"] + 1.18 * E["Al2O3"] + 0.65 * E["Fe2O3"])
            s = ref["den_lsf_raw"] if a == 0.0 else ref["den_lsf"]
        elif k == "SM":
            g = E["SiO2"] - t * (E["Al2O3"] + E["Fe2O3"])
            s = ref["den_sm_raw"] if a == 0.0 else ref["den_sm"]
        elif k == "IM":
            g = E["Al2O3"] - t * E["Fe2O3"]
            s = ref["den_im_raw"] if a == 0.0 else ref["den_im"]
        else:  # C3S (항상 클링커 기준)
            if targets.c3s_basis == "xrd" and xrd_map is not None:
                t = xrd_map.bogue_c3s_for_alite(t)
            const = 4.071 * ref["fcao"] + 2.852 * ref["so3"] + t
            g = 4.071 * E["CaO"] - 7.600 * E["SiO2"] - 6.718 * E["Al2O3"] - 1.430 * E["Fe2O3"] - const * D
            s = ref["D"]
        rows.append(g)
        scales.append(max(abs(s), 1e-9))
        keys.append(k)
    return np.array(rows), np.array(scales), keys


def _ref_values(mats: pd.DataFrame, x: np.ndarray, kp: KilnParams, fcao: float, so3: float) -> dict:
    raw = raw_meal_composition(mats, x)
    D = 1 - raw["LOI"] / 100
    a = kp.a
    C = {o: (1 - a) * raw[o] / D + a * kp.ash.get(o, 0.0) for o in ("SiO2", "Al2O3", "Fe2O3", "CaO")}
    # E = C·D (분모를 같은 형태로 맞춤)
    return {
        "den_lsf": (2.8 * C["SiO2"] + 1.18 * C["Al2O3"] + 0.65 * C["Fe2O3"]) * D,
        "den_sm": (C["Al2O3"] + C["Fe2O3"]) * D,
        "den_im": C["Fe2O3"] * D,
        "den_lsf_raw": 2.8 * raw["SiO2"] + 1.18 * raw["Al2O3"] + 0.65 * raw["Fe2O3"],
        "den_sm_raw": raw["Al2O3"] + raw["Fe2O3"],
        "den_im_raw": raw["Fe2O3"],
        "D": D, "fcao": fcao, "so3": so3,
    }


def _start_point(m: pd.DataFrame) -> np.ndarray:
    lo, hi = m["min"].to_numpy(float) / 100, m["max"].to_numpy(float) / 100
    fixed = m["fixed"].to_numpy(float)
    x = np.where(np.isfinite(fixed), fixed / 100, (lo + hi) / 2)
    free = ~np.isfinite(fixed)
    rest = 1 - x[~free].sum()
    if free.any() and x[free].sum() > 0:
        x[free] = x[free] / x[free].sum() * max(rest, 0)
    return np.clip(x, 0, 1)


def solve_mix(mats: pd.DataFrame, targets: MixTargets, kp: KilnParams | None = None, mode: str = "lsq",
              fcao_model: FcaoModel | None = None, xrd_map: XrdMap | None = None, x0: np.ndarray | None = None,
              iterations: int = 4) -> MixResult:
    """목표 모듈러스를 만족하는 배합비 계산.

    mode='lsq'  가중 최소자승(목표에 최대한 근접, 기준 배합과 가장 가까운 해)
    mode='cost' 원가 최소(목표 허용편차 TOL 이내에서 원료비 최소). 해가 없으면 lsq 로 대체.
    """
    kp = kp or KilnParams()
    allm = _clean(mats)
    m = allm[allm["use"]].reset_index(drop=True)
    names = m["name"].astype(str).tolist()
    msgs: list[str] = []
    n = len(m)
    if n == 0:
        raise ValueError("사용할 원료가 없습니다.")
    keys_on = targets.active()
    if len(keys_on) == 0:
        raise ValueError("목표(LSF·SM·IM·C₃S) 중 최소 1개를 선택하세요.")
    fixed = m["fixed"].to_numpy(float)
    is_fixed = np.isfinite(fixed)
    lo = m["min"].to_numpy(float) / 100
    hi = m["max"].to_numpy(float) / 100
    same = (~is_fixed) & (hi - lo < 1e-9)
    fixed = np.where(same, lo * 100, fixed)
    is_fixed = is_fixed | same
    if fixed[is_fixed].sum() > 100 + 1e-6:
        raise ValueError("고정 배합비 합계가 100%를 넘습니다.")
    if (lo > hi + 1e-12).any():
        bad = [names[i] for i in np.where(lo > hi)[0]]
        raise ValueError(f"하한이 상한보다 큰 원료: {', '.join(bad)}")
    free = ~is_fixed
    if free.sum() == 0:
        x = fixed / 100
        msgs.append("모든 원료가 고정되어 계산 없이 결과만 평가했습니다.")
        return _finish(m, names, x, targets, kp, fcao_model, xrd_map, "평가", msgs, [])
    if len(keys_on) + 1 > free.sum():
        msgs.append(f"조정 가능한 원료 {int(free.sum())}종으로 목표 {len(keys_on)}개를 모두 정확히 맞추기 어렵습니다"
                    "(원료 수 ≥ 목표 수 + 1 필요) — 가중 절충 결과입니다.")
    if "LSF" in keys_on and "C3S" in keys_on:
        msgs.append("LSF와 C₃S는 서로 종속적인 목표라 동시에 지정하면 가중치에 따라 절충됩니다.")

    x = np.asarray(x0, float) if x0 is not None and len(x0) == n else _start_point(m.assign(fixed=np.where(is_fixed, fixed, np.nan)))
    x = np.where(is_fixed, fixed / 100, x)
    fcao_ref, so3_ref = kp.fcao, 0.5
    used_mode = mode
    for _ in range(max(iterations, 1)):
        ref = _ref_values(m, x, kp, fcao_ref, so3_ref)
        G, S, keys = _rows(m, targets, kp, ref, xrd_map)
        unit = np.array([UNIT[k] for k in keys])
        w = np.sqrt(np.array([max(float(targets.weights.get(k, 1.0)), 0.0) for k in keys]))
        A_t = G / S[:, None] / unit[:, None] * w[:, None]
        xf = fixed / 100
        b_t = -(A_t[:, is_fixed] @ xf[is_fixed]) if is_fixed.any() else np.zeros(len(keys))
        rest = 1 - (xf[is_fixed].sum() if is_fixed.any() else 0.0)
        if used_mode == "cost":
            sol = _solve_cost(m, G, S, keys, free, is_fixed, xf, rest, lo, hi)
            if sol is None:
                msgs.append("원가 최소화: 목표 허용편차(" + ", ".join(f"{TARGET_LABELS[k]} ±{TOL[k]}" for k in keys)
                            + ") 안에서 해가 없어 최소자승 결과로 대체했습니다.")
                used_mode = "lsq"
            else:
                x = np.where(is_fixed, xf, 0.0)
                x[free] = sol
        if used_mode == "lsq":
            A_free = A_t[:, free]
            big = 1e3
            mu = 1e-2
            x_ref = x[free]
            A = np.vstack([A_free, big * np.ones((1, int(free.sum()))), np.sqrt(mu) * np.eye(int(free.sum()))])
            b = np.concatenate([b_t, [big * rest], np.sqrt(mu) * x_ref])
            res = lsq_linear(A, b, bounds=(lo[free], np.maximum(hi[free], lo[free] + 1e-12)), method="bvls")
            x = np.where(is_fixed, xf, 0.0)
            x[free] = res.x
        cl = predict_clinker(m, x, kp, fcao_model=fcao_model, xrd_map=xrd_map,
                             fcao=None if fcao_model is not None else kp.fcao)
        fcao_ref, so3_ref = cl["fcao"], cl["clinker"]["SO3"]
    active = []
    for i in np.where(free)[0]:
        if x[i] <= lo[i] + 1e-6 and lo[i] > 0:
            active.append(f"{names[i]} 하한({lo[i] * 100:g}%)")
        elif x[i] >= hi[i] - 1e-6 and hi[i] < 1:
            active.append(f"{names[i]} 상한({hi[i] * 100:g}%)")
        elif x[i] <= 1e-6 and lo[i] == 0:
            active.append(f"{names[i]} 미사용(0%)")
    if abs(x.sum() - 1) > 1e-4:
        msgs.append(f"배합비 합계가 {x.sum() * 100:.2f}%입니다 — 하한·상한·고정 조건을 확인하세요.")
    return _finish(m, names, x, targets, kp, fcao_model, xrd_map, "원가 최소" if used_mode == "cost" else "최소자승",
                   msgs, active)


def _solve_cost(m, G, S, keys, free, is_fixed, xf, rest, lo, hi) -> np.ndarray | None:
    """원가 최소 LP: |정규화 잔차| ≤ TOL(목표 단위), 합계 = 1, 하한·상한."""
    h2o = np.clip(m["H2O"].to_numpy(float), 0, 95) / 100
    price_dry = m["cost"].to_numpy(float) / (1 - h2o)          # 원/t(건조)
    Gn = G / S[:, None]
    tol = np.array([TOL[k] for k in keys])
    fixed_part = Gn[:, is_fixed] @ xf[is_fixed] if is_fixed.any() else np.zeros(len(keys))
    A_ub = np.vstack([Gn[:, free], -Gn[:, free]])
    b_ub = np.concatenate([tol - fixed_part, tol + fixed_part])
    res = linprog(price_dry[free], A_ub=A_ub, b_ub=b_ub, A_eq=np.ones((1, int(free.sum()))), b_eq=[rest],
                  bounds=list(zip(lo[free], hi[free])), method="highs")
    return res.x if res.status == 0 else None


def _finish(m, names, x, targets, kp, fcao_model, xrd_map, mode, msgs, active) -> MixResult:
    cl = predict_clinker(m, x, kp, fcao_model=fcao_model, xrd_map=xrd_map,
                         fcao=None if fcao_model is not None else kp.fcao)
    achieved, dev = {}, {}
    ok = True
    for k in TARGET_KEYS:
        v = _target_value(cl, k, targets.basis)
        if k == "C3S" and targets.c3s_basis == "xrd":
            v = cl["xrd"]["alite"]
        achieved[k] = v
        if targets.enabled.get(k) and targets.values.get(k) is not None:
            dev[k] = v - float(targets.values[k])
            if abs(dev[k]) > TOL[k] + 1e-9:
                ok = False
    if not ok:
        miss = [f"{TARGET_LABELS[k]} {achieved[k]:.{DEC[k]}f} (목표 {targets.values[k]:g}, 편차 {d:+.{DEC[k]}f})"
                for k, d in dev.items() if abs(d) > TOL[k] + 1e-9]
        msgs.append("목표 미달: " + "; ".join(miss) + (" — 제약에 걸린 원료: " + ", ".join(active) if active else ""))
    h2o = np.clip(m["H2O"].to_numpy(float), 0, 95) / 100
    wet_kg = x * cl["kiln_factor"] / (1 - h2o)                 # t 습윤 원료 / t 클링커
    cost = float(np.sum(wet_kg * m["cost"].to_numpy(float)))
    return MixResult(names, x, wet_ratios(m, x), cl, achieved, dev, ok, mode, msgs, cost, active, m)


def sensitivity(mats: pd.DataFrame, x: np.ndarray, kp: KilnParams, step: float = 0.01) -> pd.DataFrame:
    """원료별 +1%p 증량(나머지 원료는 비례 감량) 시 클링커 LSF·SM·IM·C3S 변화."""
    m = _clean(mats)
    m = m[m["use"]].reset_index(drop=True)
    base = predict_clinker(m, x, kp)
    rows = []
    for i, name in enumerate(m["name"]):
        xi = np.asarray(x, float).copy()
        others = 1 - xi[i]
        if others <= step:
            continue
        xi = np.where(np.arange(len(xi)) == i, xi[i] + step, xi * (others - step) / others)
        cl = predict_clinker(m, xi, kp)
        rows.append({"원료": name, "ΔLSF": cl["LSF"] - base["LSF"], "ΔSM": cl["SM"] - base["SM"],
                     "ΔIM": cl["IM"] - base["IM"], "ΔC₃S(Bogue)": cl["C3S"] - base["C3S"]})
    return pd.DataFrame(rows)


# ── 공장 실적 기반 보정·검증 ────────────────────────────────────────────
def estimate_loi(rm: pd.DataFrame) -> pd.Series:
    """생료 강열감량 — 실측(rm_loi)이 없으면 CO₂ 화학양론 추정(0.785·CaO + 1.092·MgO + 0.6)."""
    est = 0.785 * rm["rm_cao"] + 1.092 * rm["rm_mgo"] + 0.6
    if "rm_loi" in rm:
        return rm["rm_loi"].where(rm["rm_loi"].notna(), est)
    return est


def conversion_check(store, kp: KilnParams, lag_hours: float = 2.0) -> tuple[pd.DataFrame, dict]:
    """생료 실측 → (물질수지) 클링커 예측 vs 클링커 실측. 반환: (시점별 비교표, 요약)."""
    rm = store.tables.get("raw_meal", pd.DataFrame())
    clk = store.tables.get("clinker", pd.DataFrame())
    need_rm = ["rm_cao", "rm_sio2", "rm_al2o3", "rm_fe2o3", "rm_mgo"]
    if len(rm) == 0 or len(clk) == 0 or any(c not in rm for c in need_rm):
        return pd.DataFrame(), {}
    r = rm.copy()
    r["rm_loi_used"] = estimate_loi(r)
    r = r.dropna(subset=need_rm + ["rm_loi_used"]).sort_values("timestamp")
    r["timestamp"] = r["timestamp"] + pd.Timedelta(hours=lag_hours)
    c = clk.dropna(subset=["clk_cao", "clk_sio2", "clk_al2o3", "clk_fe2o3"]).sort_values("timestamp")
    d = pd.merge_asof(c, r, on="timestamp", direction="backward", tolerance=pd.Timedelta(hours=lag_hours + 2))
    d = d.dropna(subset=need_rm)
    if len(d) == 0:
        return pd.DataFrame(), {}
    a = kp.a
    D = 1 - d["rm_loi_used"] / 100
    pred = {}
    for o, col in (("CaO", "rm_cao"), ("SiO2", "rm_sio2"), ("Al2O3", "rm_al2o3"), ("Fe2O3", "rm_fe2o3")):
        pred[o] = (1 - a) * d[col] / D + a * kp.ash.get(o, 0.0)
    out = pd.DataFrame({"timestamp": d["timestamp"]})
    out["LSF 예측"] = chem.lsf(pred["CaO"], pred["SiO2"], pred["Al2O3"], pred["Fe2O3"])
    out["LSF 실측"] = d["clk_lsf"]
    out["SM 예측"] = chem.silica_modulus(pred["SiO2"], pred["Al2O3"], pred["Fe2O3"])
    out["SM 실측"] = d["clk_sm"]
    out["IM 예측"] = chem.iron_modulus(pred["Al2O3"], pred["Fe2O3"])
    out["IM 실측"] = d["clk_im"]
    summary = {}
    for k in ("LSF", "SM", "IM"):
        err = out[f"{k} 예측"] - out[f"{k} 실측"]
        summary[k] = {"bias": float(err.mean()), "rmse": float(np.sqrt(np.mean(err ** 2))), "n": int(err.notna().sum())}
    # 유효 석탄회 흡수량 a 추정: C_clk − R/D = a·(ash − R/D)  (CaO·SiO2·Al2O3·Fe2O3 동시 최소자승)
    num, den = 0.0, 0.0
    for o, rc, cc in (("CaO", "rm_cao", "clk_cao"), ("SiO2", "rm_sio2", "clk_sio2"),
                      ("Al2O3", "rm_al2o3", "clk_al2o3"), ("Fe2O3", "rm_fe2o3", "clk_fe2o3")):
        ign = d[rc] / D
        u = kp.ash.get(o, 0.0) - ign
        v = d[cc] - ign
        num += float(np.sum(u * v))
        den += float(np.sum(u * u))
    summary["a_eff"] = num / den if den else float("nan")
    summary["a_set"] = a
    return out, summary


def estimate_coal_rate(store) -> float | None:
    """DCS 석탄 투입량(t/h)·원료 투입량(t/h)과 생료 강열감량으로 석탄 원단위(kg/t-clk) 추정."""
    kiln = store.tables.get("kiln", pd.DataFrame())
    rm = store.tables.get("raw_meal", pd.DataFrame())
    if len(kiln) == 0 or not {"coal_rate", "kiln_feed"} <= set(kiln.columns) or len(rm) == 0:
        return None
    end = kiln["timestamp"].max()
    k = kiln[kiln["timestamp"] >= end - pd.Timedelta(days=14)]
    loi = estimate_loi(rm[rm["timestamp"] >= end - pd.Timedelta(days=14)]).mean()
    if not np.isfinite(loi):
        return None
    clinker_tph = k["kiln_feed"].mean() * (1 - loi / 100)     # 석탄회 흡수 미반영(근사)
    if clinker_tph <= 0:
        return None
    return float(k["coal_rate"].mean() / clinker_tph * 1000)


def current_mix_from_ratios(mats: pd.DataFrame, ratios_pct: list[float]) -> np.ndarray:
    """사용자가 입력한 배합비(%) → 사용 원료 배합비(합계 1)."""
    m = _clean(mats)
    x = np.asarray(ratios_pct, float)[m["use"].to_numpy()] / 100.0
    s = x.sum()
    return x / s if s > 0 else x


# ── 엑셀 배합 설계서 ────────────────────────────────────────────────────
def design_workbook(mats: pd.DataFrame, targets: MixTargets, kp: KilnParams, res: MixResult) -> bytes:
    """원료 성분·목표·배합 결과·클링커 예측을 담은 배합 설계서(엑셀)."""
    import io

    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cl = res.clinker
    mat = _clean(mats).rename(columns={"use": "사용", "name": "원료", "category": "구분", "LOI": "강열감량(%)",
                                       "H2O": "수분(%)", "Cr": "총Cr(mg/kg)", "cost": "단가(원/t 습윤)",
                                       "min": "하한(%)", "max": "상한(%)", "fixed": "고정(%)"})
    cond = pd.DataFrame(
        [("목표 기준", "클링커(석탄회 반영)" if targets.basis == "clinker" else "생료"), ("계산 방식", res.mode)]
        + [(f"목표 {TARGET_LABELS[k]}", f"{targets.values[k]:g}" + ("" if targets.enabled.get(k) else " (미사용)"))
           for k in TARGET_KEYS]
        + [("석탄 원단위(kg/t-clk)", kp.coal_kg_per_t), ("석탄 회분(%)", kp.coal_ash), ("회분 흡수율(%)", kp.ash_absorption),
           ("석탄 황분(%)", kp.coal_s), ("SO₃ 잔류율(%)", kp.so3_retention), ("K₂O 잔류율(%)", kp.k2o_retention),
           ("Na₂O 잔류율(%)", kp.na2o_retention), ("흡수 석탄회 a(kg/kg-clk)", round(kp.a, 5))],
        columns=["항목", "값"])
    comp = pd.DataFrame({"성분": OXIDES + ["LOI"],
                         "생료(건조, %)": [cl["raw"][o] for o in OXIDES] + [cl["raw"]["LOI"]],
                         "클링커 예측(%)": [cl["clinker"].get(o, np.nan) for o in OXIDES] + [np.nan]})
    mod = pd.DataFrame([
        ("생료 LSF", cl["raw_lsf"]), ("생료 SM", cl["raw_sm"]), ("생료 IM", cl["raw_im"]),
        ("클링커 LSF", cl["LSF"]), ("클링커 SM", cl["SM"]), ("클링커 IM", cl["IM"]),
        ("C₃S(Bogue)", cl["C3S"]), ("C₂S(Bogue)", cl["C2S"]), ("C₃A(Bogue)", cl["C3A"]), ("C₄AF(Bogue)", cl["C4AF"]),
        ("액상량 1450℃(%)", cl["liquid"]), ("Na₂Oeq(%)", cl["na2oeq"]), ("f-CaO 예측(%)", cl["fcao"]),
        ("XRD 알라이트 예측(%)", cl["xrd"]["alite"]), ("XRD 벨라이트 예측(%)", cl["xrd"]["belite"]),
        ("생료/클링커(t/t)", cl["kiln_factor"]), ("원료비(원/t-클링커)", res.cost_per_t_clk)], columns=["항목", "값"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame({"배합 설계서": [
            "Blue365 QMS 원료 배합 설계서", f"달성 여부: {'목표 달성' if res.feasible else '목표 미달'}",
            *res.messages, "※ 원료 성분·킬른 계수 기본값은 예시(추정)입니다. 공장 분석값으로 확인하세요."]}).to_excel(
            xw, sheet_name="요약", index=False)
        res.table().round(3).to_excel(xw, sheet_name="배합결과", index=False)
        mat.to_excel(xw, sheet_name="원료성분", index=False)
        cond.to_excel(xw, sheet_name="목표·조건", index=False)
        comp.round(3).to_excel(xw, sheet_name="생료·클링커조성", index=False)
        mod.round(3).to_excel(xw, sheet_name="클링커예측", index=False)
        for ws in xw.book.worksheets:
            for cell in ws[1]:
                cell.font = Font(name="맑은 고딕", bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F3A5F")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.font = Font(name="맑은 고딕", size=10)
            for i, col in enumerate(ws.columns, 1):
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[get_column_letter(i)].width = min(max(10, width * 1.6), 60)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def parse_materials(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """원료 성분표 업로드(엑셀/CSV). 한글 열 이름(설계서 '원료성분' 시트)도 인식한다."""
    import io

    df = pd.read_csv(io.BytesIO(file_bytes)) if filename.lower().endswith(".csv") else \
        pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    back = {"사용": "use", "원료": "name", "구분": "category", "강열감량(%)": "LOI", "수분(%)": "H2O",
            "총Cr(mg/kg)": "Cr", "단가(원/t 습윤)": "cost", "하한(%)": "min", "상한(%)": "max", "고정(%)": "fixed"}
    df = df.rename(columns=back)
    if "name" not in df.columns or not any(o in df.columns for o in OXIDES):
        raise ValueError("원료 이름(원료/name)과 산화물(SiO2·CaO 등) 열이 필요합니다.")
    return _clean(df)[MATERIAL_COLUMNS]
