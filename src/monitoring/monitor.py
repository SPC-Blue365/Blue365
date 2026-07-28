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
from config import schema as S
from src.monitoring.alerts import (
    Alert, AlertConfig, Level, data_age_hours, evaluate_alerts, is_data_stale, overall_level,
)

# 모니터에 필요한 최소 행수. 학습 구간(80%)이 F.MIN_TRAIN_ROWS 를 넘도록 잡는다.
MIN_ROWS = max(10, int(F.MIN_TRAIN_ROWS / 0.8) + 1)


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
    age_hours: float = 0.0       # 마지막 측정 이후 경과 시간
    is_stale: bool = False       # 데이터 지연(가동 중지·수집 중단 가능)
    note: str = ""               # 운전 상태 메모 (config.schema.LINE_NOTES)

    @property
    def level_label(self) -> str:
        return self.level.label

    @property
    def badge(self) -> tuple[str, str]:
        """(아이콘, 라벨). 데이터가 지연되면 품위 경보 대신 '중지/지연'으로 표시."""
        if self.is_stale:
            return "⏸️", "가동 중지/데이터 지연"
        return {Level.GREEN: ("🟢", "정상"), Level.YELLOW: ("🟡", "주의"),
                Level.RED: ("🔴", "경고")}[self.level]

    @property
    def as_of(self) -> str:
        t = pd.to_datetime(self.latest_time, errors="coerce")
        return "-" if pd.isna(t) else f"{t:%Y/%m/%d %H:%M}"

    @property
    def age_text(self) -> str:
        if self.age_hours != self.age_hours:      # nan
            return "판정 불가"
        if self.age_hours < 24:
            return f"{self.age_hours:.0f}시간 전"
        return f"{self.age_hours / 24:.0f}일 전"


def _load_saved(line: str):
    p = MODELS_DIR / f"ridge_{line}.joblib"
    if p.exists():
        import joblib
        return joblib.load(p)
    return None


def _insufficient(ld: LineData, msg: str) -> LineStatus:
    """데이터 부족 상태. 다른 코드가 기대하는 series 스키마(datetime/actual/pred)를 유지한다."""
    empty = pd.DataFrame({"datetime": pd.to_datetime([]), "actual": [], "pred": []})
    return LineStatus(ld.line, ld.alias, Level.GREEN, None, np.nan, np.nan, np.nan, 0,
                      [Alert(Level.YELLOW, "data", msg)], empty,
                      age_hours=float("nan"), is_stale=False,
                      note=S.LINE_NOTES.get(ld.line, ""))


def monitor_line(
    ld: LineData, cfg: AlertConfig | None = None, recent_frac: float = 0.2, model_bundle=None,
    reference_time=None,
) -> LineStatus:
    """한 라인의 최근 구간을 모니터링해 상태·경보 반환.

    reference_time: 최신성 판정 기준 시각(미지정 시 그 라인의 마지막 측정 = 지연 0).
                    여러 라인을 비교할 땐 monitor_all 이 전체 최신 시각을 기준으로 넘긴다.
    """
    cfg = cfg or AlertConfig()
    d = ld.features.dropna(subset=F.AR_CORE + ["cao"]).copy()
    if len(d) < MIN_ROWS:
        return _insufficient(ld, f"데이터 부족({len(d)}행) — 모니터 불가")

    k = int(len(d) * (1 - recent_frac))
    bundle = model_bundle or _load_saved(ld.line)
    if bundle is not None:
        model, feats = bundle["model"], bundle["features"]
    else:
        try:
            model, feats = F.fit_final(d.iloc[:k], use_upstream=False)
        except F.InsufficientDataError as e:
            return _insufficient(ld, str(e))

    recent = d.iloc[k:].copy()
    recent["pred"] = model.predict(recent[feats].fillna(0.0).values)
    recent_mae = float(np.abs(recent["cao"].values - recent["pred"].values).mean())

    alerts = evaluate_alerts(recent["cao"], recent["pred"], cfg)
    level = overall_level(alerts)

    series = pd.DataFrame({"datetime": recent.index, "actual": recent["cao"].values,
                           "pred": recent["pred"].values})
    last = series.dropna(subset=["actual"]).iloc[-1]

    # 데이터 최신성 판정 (품위 경보와 별개)
    ref = reference_time if reference_time is not None else last["datetime"]
    age = data_age_hours(last["datetime"], ref)
    stale = is_data_stale(last["datetime"], ref, cfg.stale_hours)
    note = S.LINE_NOTES.get(ld.line, "") if stale else ""
    if stale:
        msg = f"마지막 측정 {last['datetime']:%Y/%m/%d %H:%M} 이후 새 데이터 없음"
        alerts = [Alert(Level.YELLOW, "stale", msg + (f" — {note}" if note else ""))] + alerts

    return LineStatus(
        ld.line, ld.alias, level, last["datetime"], float(last["actual"]), float(last["pred"]),
        recent_mae, len(recent), alerts, series,
        age_hours=age, is_stale=stale, note=note,
    )


def monitor_all(lines: dict[str, LineData], cfg: AlertConfig | None = None,
                reference_time=None) -> dict[str, LineStatus]:
    """모든 라인 모니터링. 최신성은 '전체 라인 중 가장 최근 측정'을 기준으로 판정한다."""
    first = {ln: monitor_line(ld, cfg) for ln, ld in lines.items()}
    if reference_time is None:
        times = [pd.to_datetime(s.latest_time, errors="coerce") for s in first.values()]
        times = [t for t in times if pd.notna(t)]
        reference_time = max(times) if times else None
    if reference_time is None:
        return first
    return {ln: monitor_line(ld, cfg, reference_time=reference_time) for ln, ld in lines.items()}
