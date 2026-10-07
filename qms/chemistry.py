"""시멘트 화학 계산.

모든 함수는 스칼라, numpy 배열, pandas Series를 모두 받는다(벡터 연산).
산화물 값은 질량 % 기준이다.

근거
----
- LSF (석회포화도): Lea & Parker 식, MgO ≤ 2% 범위에서 유효
      LSF = 100·CaO / (2.8·SiO2 + 1.18·Al2O3 + 0.65·Fe2O3)
  시멘트(석고 포함)는 CaO에서 석고분(0.7·SO3)을 뺀 값을 사용한다.
- SM (규산율) = SiO2 / (Al2O3 + Fe2O3)
- IM (철률, AM) = Al2O3 / Fe2O3
- Bogue 광물 조성: ASTM C150 부속서(A1) 식
      A/F ≥ 0.64:
        C3S  = 4.071·CaO' − 7.600·SiO2 − 6.718·Al2O3 − 1.430·Fe2O3 − 2.852·SO3
        C2S  = 2.867·SiO2 − 0.7544·C3S
        C3A  = 2.650·Al2O3 − 1.692·Fe2O3
        C4AF = 3.043·Fe2O3
      A/F < 0.64 (C3A = 0, 고용체 ss(C4AF+C2F) 생성):
        ss   = 2.100·Al2O3 + 1.702·Fe2O3
        C3S  = 4.071·CaO' − 7.600·SiO2 − 4.479·Al2O3 − 2.859·Fe2O3 − 2.852·SO3
      CaO' = CaO − 자유석회(f-CaO)
- 액상량(1450 ℃): Lea & Parker 경험식
      A/F ≥ 1.38:  L = 3.00·Al2O3 + 2.25·Fe2O3 + MgO + K2O + Na2O
      A/F < 1.38:  L = 8.20·Al2O3 − 5.22·Fe2O3 + MgO + K2O + Na2O
  (MgO는 액상에 용해되는 한계인 2.0%까지만 반영)
- 등가 알칼리 Na2Oeq = Na2O + 0.658·K2O (ASTM C150)
- 소성성 지수 BI = C3S / (C3A + C4AF)  — 경험 지표(값이 클수록 난소성)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Number = float | np.ndarray | pd.Series


def _safe_div(num: Number, den: Number) -> Number:
    """0으로 나누기를 NaN으로 처리한다."""
    if isinstance(den, (pd.Series, np.ndarray)):
        den = den.astype(float)
        if isinstance(den, pd.Series):
            den = den.where(den != 0)
        else:
            den = np.where(den == 0, np.nan, den)
        return num / den
    return num / den if den else float("nan")


def lsf(cao: Number, sio2: Number, al2o3: Number, fe2o3: Number, so3: Number = 0.0,
        gypsum_correction: bool = False) -> Number:
    """석회포화도(LSF, %).

    gypsum_correction=True 이면 시멘트 분석값에서 석고분 CaO(0.7·SO3)를 빼고 계산한다.
    """
    cao_eff = cao - 0.7 * so3 if gypsum_correction else cao
    return 100.0 * _safe_div(cao_eff, 2.8 * sio2 + 1.18 * al2o3 + 0.65 * fe2o3)


def silica_modulus(sio2: Number, al2o3: Number, fe2o3: Number) -> Number:
    """규산율(SM)."""
    return _safe_div(sio2, al2o3 + fe2o3)


def iron_modulus(al2o3: Number, fe2o3: Number) -> Number:
    """철률(IM, 알루미나율 AM)."""
    return _safe_div(al2o3, fe2o3)


def bogue(cao: Number, sio2: Number, al2o3: Number, fe2o3: Number, so3: Number = 0.0,
          fcao: Number = 0.0) -> dict[str, Number]:
    """Bogue 광물 조성(%). 반환: {'C3S','C2S','C3A','C4AF'}.

    A/F < 0.64 인 경우 C3A=0 이고, C4AF 자리에 고용체 ss(C4AF+C2F)를 넣는다.
    음수로 계산되는 광물은 0으로 절사한다(조성 범위 밖 = 계산 무의미).
    """
    cao_eff = cao - fcao
    af = _safe_div(al2o3, fe2o3)
    normal = np.asarray(af >= 0.64)

    c3s_n = 4.071 * cao_eff - 7.600 * sio2 - 6.718 * al2o3 - 1.430 * fe2o3 - 2.852 * so3
    c3s_l = 4.071 * cao_eff - 7.600 * sio2 - 4.479 * al2o3 - 2.859 * fe2o3 - 2.852 * so3
    c3a_n = 2.650 * al2o3 - 1.692 * fe2o3
    c4af_n = 3.043 * fe2o3
    ss_l = 2.100 * al2o3 + 1.702 * fe2o3

    c3s = np.where(normal, c3s_n, c3s_l)
    c3a = np.where(normal, c3a_n, 0.0)
    c4af = np.where(normal, c4af_n, ss_l)
    c3s = np.clip(c3s, 0, None)
    c2s = np.clip(2.867 * np.asarray(sio2, dtype=float) - 0.7544 * c3s, 0, None)
    c3a = np.clip(c3a, 0, None)

    out = {"C3S": c3s, "C2S": c2s, "C3A": c3a, "C4AF": c4af}
    if isinstance(cao, pd.Series):
        return {k: pd.Series(np.asarray(v, dtype=float), index=cao.index) for k, v in out.items()}
    if np.ndim(c3s) == 0:
        return {k: float(v) for k, v in out.items()}
    return out


def liquid_phase_1450(al2o3: Number, fe2o3: Number, mgo: Number = 0.0, k2o: Number = 0.0,
                      na2o: Number = 0.0) -> Number:
    """1450 ℃ 액상량(%) — Lea & Parker 경험식."""
    af = _safe_div(al2o3, fe2o3)
    mgo_eff = np.minimum(mgo, 2.0)
    high = 3.00 * al2o3 + 2.25 * fe2o3
    low = 8.20 * al2o3 - 5.22 * fe2o3
    base = np.where(np.asarray(af >= 1.38), high, low)
    result = base + mgo_eff + k2o + na2o
    if isinstance(al2o3, pd.Series):
        return pd.Series(np.asarray(result, dtype=float), index=al2o3.index)
    return float(result) if np.ndim(result) == 0 else result


def na2o_eq(na2o: Number, k2o: Number) -> Number:
    """등가 알칼리(Na2Oeq, %)."""
    return na2o + 0.658 * k2o


def burnability_index(c3s: Number, c3a: Number, c4af: Number) -> Number:
    """소성성 지수 BI = C3S/(C3A+C4AF). 경험 지표."""
    return _safe_div(c3s, c3a + c4af)


def add_raw_meal_moduli(df: pd.DataFrame, prefix: str = "rm_") -> pd.DataFrame:
    """생료 데이터프레임에 LSF/SM/IM 파생 열을 추가한다(입력은 수정하지 않음)."""
    p = prefix
    out = df.copy()
    out[f"{p}lsf"] = lsf(out[f"{p}cao"], out[f"{p}sio2"], out[f"{p}al2o3"], out[f"{p}fe2o3"])
    out[f"{p}sm"] = silica_modulus(out[f"{p}sio2"], out[f"{p}al2o3"], out[f"{p}fe2o3"])
    out[f"{p}im"] = iron_modulus(out[f"{p}al2o3"], out[f"{p}fe2o3"])
    return out


def add_clinker_derived(df: pd.DataFrame, prefix: str = "clk_") -> pd.DataFrame:
    """클링커 데이터프레임에 모듈러스·Bogue 광물·액상량·등가알칼리를 추가한다."""
    p = prefix
    out = df.copy()
    out[f"{p}lsf"] = lsf(out[f"{p}cao"], out[f"{p}sio2"], out[f"{p}al2o3"], out[f"{p}fe2o3"])
    out[f"{p}sm"] = silica_modulus(out[f"{p}sio2"], out[f"{p}al2o3"], out[f"{p}fe2o3"])
    out[f"{p}im"] = iron_modulus(out[f"{p}al2o3"], out[f"{p}fe2o3"])
    so3 = out[f"{p}so3"] if f"{p}so3" in out else 0.0
    fcao = out[f"{p}fcao"] if f"{p}fcao" in out else 0.0
    phases = bogue(out[f"{p}cao"], out[f"{p}sio2"], out[f"{p}al2o3"], out[f"{p}fe2o3"], so3, fcao)
    for name, values in phases.items():
        out[f"{p}{name.lower()}"] = values
    out[f"{p}liquid"] = liquid_phase_1450(out[f"{p}al2o3"], out[f"{p}fe2o3"], out[f"{p}mgo"],
                                          out[f"{p}k2o"], out[f"{p}na2o"])
    out[f"{p}na2oeq"] = na2o_eq(out[f"{p}na2o"], out[f"{p}k2o"])
    return out


def raw_mix_3(materials: list[dict], lsf_target: float, sm_target: float) -> dict:
    """3성분 조합 계산: 목표 LSF·SM을 만족하는 원료 배합비(건조 기준, 합계 100%).

    materials: [{"name", "CaO", "SiO2", "Al2O3", "Fe2O3"}, ...] 3개
    풀이: Σx_i·(100·C_i − LSF·(2.8S_i + 1.18A_i + 0.65F_i)) = 0
          Σx_i·(S_i − SM·(A_i + F_i)) = 0,  Σx_i = 1  (3×3 연립방정식)
    반환: {"ratios": [..](%), "feasible": bool, "mix": {산화물: 값}, "lsf", "sm", "im"}
    음수 배합비가 나오면 목표 조합이 해당 원료로 불가능(feasible=False).
    """
    if len(materials) != 3:
        raise ValueError("원료 3종이 필요합니다.")
    A = np.zeros((3, 3))
    for j, m in enumerate(materials):
        c, s_, a, f = (float(m[k]) for k in ("CaO", "SiO2", "Al2O3", "Fe2O3"))
        A[0, j] = 100 * c - lsf_target * (2.8 * s_ + 1.18 * a + 0.65 * f)
        A[1, j] = s_ - sm_target * (a + f)
        A[2, j] = 1.0
    try:
        x = np.linalg.solve(A, np.array([0.0, 0.0, 1.0]))
    except np.linalg.LinAlgError:
        return {"ratios": [float("nan")] * 3, "feasible": False, "mix": {}, "lsf": float("nan"),
                "sm": float("nan"), "im": float("nan")}
    mix = {k: float(sum(x[j] * float(materials[j][k]) for j in range(3))) for k in ("CaO", "SiO2", "Al2O3", "Fe2O3")}
    return {"ratios": [float(v * 100) for v in x], "feasible": bool(np.all(x >= -1e-9)), "mix": mix,
            "lsf": float(lsf(mix["CaO"], mix["SiO2"], mix["Al2O3"], mix["Fe2O3"])),
            "sm": float(silica_modulus(mix["SiO2"], mix["Al2O3"], mix["Fe2O3"])),
            "im": float(iron_modulus(mix["Al2O3"], mix["Fe2O3"]))}
