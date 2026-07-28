"""경보 엔진 [ML-Engineer].

규격 이탈·지속 이탈·모델 편차·추세를 임계 기반으로 판정한다. 임계는 AlertConfig 로 조정.
경보 수준: GREEN(정상) < YELLOW(주의) < RED(경고).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import pandas as pd

from config.schema import TARGET


class Level(IntEnum):
    GREEN = 0
    YELLOW = 1
    RED = 2

    @property
    def label(self) -> str:
        return {0: "정상", 1: "주의", 2: "경고"}[int(self)]


@dataclass
class AlertConfig:
    lo: float = TARGET.lower          # 규격 하한 (44.1)
    hi: float = TARGET.upper          # 규격 상한 (45.1)
    sustain_hours: int = 3            # 연속 이탈 이 시간 이상이면 RED
    deviation_warn: float = 1.0       # |실측-예측| 이 이상이면 모델편차 주의
    trend_warn: float = 0.5           # 최근 추세 기울기(시간당) 절대값 주의
    trend_window: int = 6             # 추세 계산 창(시간)
    stale_hours: int = 24             # 이 시간 이상 새 측정이 없으면 '데이터 지연'으로 표시


def data_age_hours(latest_time, reference_time) -> float:
    """마지막 측정 이후 경과 시간(h). 판정 불가 시 nan."""
    t = pd.to_datetime(latest_time, errors="coerce")
    ref = pd.to_datetime(reference_time, errors="coerce")
    if pd.isna(t) or pd.isna(ref):
        return float("nan")
    return max(0.0, (ref - t).total_seconds() / 3600.0)


def is_data_stale(latest_time, reference_time, stale_hours: int = 24) -> bool:
    """마지막 측정이 stale_hours 이상 지났으면 True (가동 중지·수집 중단 가능).

    경보(품위 이탈)와 별개 개념 — 오래된 데이터로 '현재 상태'를 단정하지 않기 위함.
    """
    age = data_age_hours(latest_time, reference_time)
    return bool(age == age and age >= stale_hours)  # nan이면 False


@dataclass
class Alert:
    level: Level
    kind: str
    message: str


def _slope(y: np.ndarray) -> float:
    if len(y) < 2:
        return 0.0
    x = np.arange(len(y))
    m = np.isfinite(y)
    if m.sum() < 2:
        return 0.0
    return float(np.polyfit(x[m], y[m], 1)[0])


def evaluate_alerts(
    actual: pd.Series, predicted: pd.Series, cfg: AlertConfig | None = None
) -> list[Alert]:
    """최근 구간의 실측/예측으로 경보 목록을 산출 (심각도 내림차순)."""
    cfg = cfg or AlertConfig()
    a = pd.to_numeric(actual, errors="coerce")
    p = pd.to_numeric(predicted, errors="coerce")
    alerts: list[Alert] = []

    # 1) 현재 규격 이탈 (최신 실측)
    last = a.dropna()
    if len(last):
        v = float(last.iloc[-1])
        if v < cfg.lo or v > cfg.hi:
            alerts.append(Alert(Level.RED, "spec", f"현재 CaO {v:.2f}% 규격[{cfg.lo}~{cfg.hi}] 이탈"))

    # 2) 지속 이탈 (연속 sustain_hours 이상 이탈)
    oos = (a < cfg.lo) | (a > cfg.hi)
    run = 0
    for flag in oos.values[::-1]:
        if flag:
            run += 1
        else:
            break
    if run >= cfg.sustain_hours:
        alerts.append(Alert(Level.RED, "sustain", f"{run}시간 연속 규격 이탈 지속"))
    elif run > 0:
        alerts.append(Alert(Level.YELLOW, "sustain", f"{run}시간 규격 이탈(지속 임박)"))

    # 3) 예측이 향후 이탈 예상 (최신 예측)
    lastp = p.dropna()
    if len(lastp):
        pv = float(lastp.iloc[-1])
        if pv < cfg.lo or pv > cfg.hi:
            alerts.append(Alert(Level.YELLOW, "forecast", f"예측 CaO {pv:.2f}% 규격 이탈 예상"))

    # 4) 모델 편차 (실측 vs 예측 큰 괴리 = 이상/설비 변화 가능)
    common = pd.concat([a, p], axis=1).dropna()
    if len(common):
        dev = float(abs(common.iloc[-1, 0] - common.iloc[-1, 1]))
        if dev >= cfg.deviation_warn:
            alerts.append(Alert(Level.YELLOW, "deviation", f"실측-예측 편차 {dev:.2f}%p (이상 점검)"))

    # 5) 추세 (급격한 상승/하강)
    sl = _slope(a.dropna().values[-cfg.trend_window:])
    if abs(sl) >= cfg.trend_warn:
        arrow = "상승" if sl > 0 else "하강"
        alerts.append(Alert(Level.YELLOW, "trend", f"최근 {cfg.trend_window}h CaO 급{arrow}(기울기 {sl:+.2f}/h)"))

    alerts.sort(key=lambda x: x.level, reverse=True)
    return alerts


def overall_level(alerts: list[Alert]) -> Level:
    return max((a.level for a in alerts), default=Level.GREEN)
