"""모니터 오케스트레이션 [ML-Engineer].

라인별로 확정 모델(Ridge)을 최근 구간에 적용해 예측·경보·상태를 산출한다.
저장된 모델(models/)이 있으면 로드, 없으면 학습구간으로 적합해 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from config.paths import MODELS_DIR
from src.models import forecast as F
from src.models.dataset import LineData
from src.monitoring.alerts import Alert, AlertConfig, Level, evaluate_alerts, overall_level


@dataclass
class LineStatus:
    line: str
    alias: str
    level: Level
    latest_time: object
    latest_actual: float
    latest_pred: float
    recent_mae: float
    n_monitored: int
    alerts: list[Alert] = field(default_factory=list)
    series: pd.DataFrame = None  # datetime, actual, pred (최근 구간)

    @property
    def level_label(self) -> str:
        return self.level.label


def _load_saved(line: str):
    p = MODELS_DIR / f"ridge_{line}.joblib"
    if p.exists():
        import joblib
        return joblib.load(p)
    return None


def monitor_line(
    ld: LineData, cfg: AlertConfig | None = None, recent_frac: float = 0.2, model_bundle=None
) -> LineStatus:
    """한 라인의 최근 구간을 모니터링해 상태·경보 반환."""
    cfg = cfg or AlertConfig()
    d = ld.features.dropna(subset=F.AR_CORE + ["cao"]).copy()
    if len(d) < 10:
        return LineStatus(ld.line, ld.alias, Level.GREEN, None, np.nan, np.nan, np.nan, 0,
                          [Alert(Level.YELLOW, "data", "데이터 부족(모니터 불가)")], d.assign(pred=np.nan))

    k = int(len(d) * (1 - recent_frac))
    bundle = model_bundle or _load_saved(ld.line)
    if bundle is not None:
        model, feats = bundle["model"], bundle["features"]
    else:
        model, feats = F.fit_final(d.iloc[:k], use_upstream=False)

    recent = d.iloc[k:].copy()
    recent["pred"] = model.predict(recent[feats].fillna(0.0).values)
    recent_mae = float(np.abs(recent["cao"].values - recent["pred"].values).mean())

    alerts = evaluate_alerts(recent["cao"], recent["pred"], cfg)
    level = overall_level(alerts)

    series = pd.DataFrame({"datetime": recent.index, "actual": recent["cao"].values,
                           "pred": recent["pred"].values})
    last = series.dropna(subset=["actual"]).iloc[-1]
    return LineStatus(
        ld.line, ld.alias, level, last["datetime"], float(last["actual"]), float(last["pred"]),
        recent_mae, len(recent), alerts, series,
    )


def monitor_all(lines: dict[str, LineData], cfg: AlertConfig | None = None) -> dict[str, LineStatus]:
    return {ln: monitor_line(ld, cfg) for ln, ld in lines.items()}
