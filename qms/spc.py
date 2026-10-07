"""통계적 공정관리(SPC): 관리한계, 판정규칙, 공정능력지수.

판정규칙 (Western Electric / Nelson 규칙 기반)
  R1  관리한계(±3σ) 밖의 점
  R2  중심선 한쪽에 연속 n점(기본 9점) — 평균 이동(shift)
  R3  연속 n점(기본 6점) 상승 또는 하강 — 추세(trend)
  R5  연속 3점 중 2점이 같은 쪽 ±2σ 밖
  R6  연속 5점 중 4점이 같은 쪽 ±1σ 밖

σ 추정
  - 관리한계용 σ: 기준기간 표준편차(전체 변동). 공정 데이터는 자기상관이 커서
    이동범위(MR) 기반 σ를 쓰면 관리한계가 과도하게 좁아져 허위 경보가 많아지기 때문이다.
  - 공정능력 Cpk: 군내 변동 σ_within = MR̄/1.128 (d2, n=2)
  - 공정성능 Ppk: 전체 표준편차
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RULE_NAMES: dict[str, str] = {
    "R1": "관리한계(±3σ) 이탈",
    "R2": "중심선 한쪽 연속 {run}점(평균 이동)",
    "R3": "연속 {trend}점 상승/하강(추세)",
    "R5": "3점 중 2점 ±2σ 밖(같은 쪽)",
    "R6": "5점 중 4점 ±1σ 밖(같은 쪽)",
}


def rule_name(code: str, run_length: int = 9, trend_length: int = 6) -> str:
    return RULE_NAMES.get(code, code).format(run=run_length, trend=trend_length)


@dataclass(frozen=True)
class ControlStats:
    center: float
    sigma: float          # 관리한계용(기준기간 전체 표준편차)
    sigma_within: float   # MR̄/1.128
    n: int
    base_start: pd.Timestamp | None = None
    base_end: pd.Timestamp | None = None

    @property
    def ucl(self) -> float:
        return self.center + 3 * self.sigma

    @property
    def lcl(self) -> float:
        return self.center - 3 * self.sigma


def _mr_sigma(x: np.ndarray) -> float:
    if len(x) < 2:
        return float("nan")
    return float(np.mean(np.abs(np.diff(x))) / 1.128)


def baseline_stats(series: pd.Series, settings: dict | None = None, min_points: int = 20) -> ControlStats | None:
    """기준기간 관리 통계. 3σ 밖 점을 1회 제외하고 재계산(Phase I 정제)."""
    s = series.dropna()
    if len(s) < 5:
        return None
    settings = settings or {}
    b_start, b_end = settings.get("baseline_start"), settings.get("baseline_end")
    if b_start and b_end:
        base = s[(s.index >= pd.Timestamp(b_start)) & (s.index <= pd.Timestamp(b_end) + pd.Timedelta(days=1))]
    else:
        days = settings.get("baseline_days", 30)
        base = s[s.index < s.index.min() + pd.Timedelta(days=days)]
    if len(base) < min_points:
        base = s.iloc[: max(min_points, int(len(s) * 0.3))]
    x = base.to_numpy(dtype=float)
    c, sd = float(np.mean(x)), float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    if sd > 0:
        keep = np.abs(x - c) <= 3 * sd
        if keep.sum() >= 5 and keep.sum() < len(x):
            x = x[keep]
            c, sd = float(np.mean(x)), float(np.std(x, ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        sd = abs(c) * 1e-3 or 1e-6
    sw = _mr_sigma(x)
    return ControlStats(center=c, sigma=sd, sigma_within=sw if np.isfinite(sw) and sw > 0 else sd,
                        n=len(x), base_start=base.index.min(), base_end=base.index.max())


def _runs(mask_values: np.ndarray) -> list[tuple[int, int, int]]:
    """정수 배열에서 같은 값이 연속되는 구간 [(start, end_inclusive, value)]."""
    runs = []
    if len(mask_values) == 0:
        return runs
    start = 0
    for i in range(1, len(mask_values) + 1):
        if i == len(mask_values) or mask_values[i] != mask_values[start]:
            runs.append((start, i - 1, int(mask_values[start])))
            start = i
    return runs


def rule_flags(values: np.ndarray, stats: ControlStats, rules: tuple[str, ...] | list[str],
               run_length: int = 9, trend_length: int = 6) -> dict[str, np.ndarray]:
    """규칙별 위반 점(bool 배열)을 반환한다. 패턴 규칙은 패턴을 구성하는 모든 점을 표시."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    z = (x - stats.center) / stats.sigma
    out: dict[str, np.ndarray] = {}

    if "R1" in rules:
        out["R1"] = np.abs(z) > 3

    if "R2" in rules:
        flag = np.zeros(n, dtype=bool)
        side = np.sign(z).astype(int)
        for a, b, v in _runs(side):
            if v != 0 and (b - a + 1) >= run_length:
                flag[a:b + 1] = True
        out["R2"] = flag

    if "R3" in rules:
        flag = np.zeros(n, dtype=bool)
        if n >= 2:
            d = np.sign(np.diff(x)).astype(int)  # 길이 n-1
            for a, b, v in _runs(d):
                # 증가(감소) 차분 k개 = 연속 k+1점 상승(하강)
                if v != 0 and (b - a + 2) >= trend_length:
                    flag[a:b + 2] = True
        out["R3"] = flag

    for code, k, m, thr in (("R5", 2, 3, 2.0), ("R6", 4, 5, 1.0)):
        if code not in rules:
            continue
        flag = np.zeros(n, dtype=bool)
        for sign in (1, -1):
            beyond = (sign * z) > thr
            for i in range(0, max(n - m + 1, 0)):
                w = beyond[i:i + m]
                if w.sum() >= k:
                    flag[i:i + m] |= w
        out[code] = flag
    return out


def capability(series: pd.Series, lsl: float | None, usl: float | None,
               sigma_within: float | None = None) -> dict:
    """공정능력. Cp/Cpk(군내), Pp/Ppk(전체), 규격 밖 비율."""
    x = series.dropna().to_numpy(dtype=float)
    res = {"n": len(x), "mean": np.nan, "std": np.nan, "Cp": np.nan, "Cpk": np.nan, "Pp": np.nan,
           "Ppk": np.nan, "out_pct": np.nan}
    if len(x) < 5:
        return res
    mu, sd = float(np.mean(x)), float(np.std(x, ddof=1))
    sw = sigma_within if sigma_within and np.isfinite(sigma_within) else _mr_sigma(x)
    res.update(mean=mu, std=sd)
    out = np.zeros(len(x), dtype=bool)
    if lsl is not None:
        out |= x < lsl
    if usl is not None:
        out |= x > usl
    res["out_pct"] = float(out.mean() * 100) if (lsl is not None or usl is not None) else np.nan

    def _idx(sig: float) -> tuple[float, float]:
        if not sig or not np.isfinite(sig) or sig <= 0:
            return np.nan, np.nan
        cpu = (usl - mu) / (3 * sig) if usl is not None else np.nan
        cpl = (mu - lsl) / (3 * sig) if lsl is not None else np.nan
        cp = (usl - lsl) / (6 * sig) if (usl is not None and lsl is not None) else np.nan
        cpk = np.nanmin([cpu, cpl]) if not (np.isnan(cpu) and np.isnan(cpl)) else np.nan
        return cp, cpk

    res["Cp"], res["Cpk"] = _idx(sw)
    res["Pp"], res["Ppk"] = _idx(sd)
    return res


def capability_grade(cpk: float) -> str:
    """공정능력 등급(관용 기준: 1.33 이상 충분, 1.0~1.33 보통, 1.0 미만 부족)."""
    if cpk is None or not np.isfinite(cpk):
        return "-"
    if cpk >= 1.67:
        return "매우 우수"
    if cpk >= 1.33:
        return "충분"
    if cpk >= 1.0:
        return "보통(개선 권장)"
    if cpk >= 0.67:
        return "부족(개선 필요)"
    return "매우 부족(즉시 개선)"
