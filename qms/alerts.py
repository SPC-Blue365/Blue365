"""알림 엔진: 규격·관리기준·SPC 판정규칙 위반을 '이벤트' 단위로 묶는다.

심각도
  위험  KS 규격 이탈 (제품 부적합 가능)
  경고  사내 관리기준 이탈, 또는 시험조건(KS L ISO 679) 이탈
  주의  SPC 판정규칙 위반(규격 이내이지만 공정이 불안정해지는 징후)
  ※ 예측값(28일 강도 예측)은 실측이 아니므로 최고 심각도를 '경고'로 제한한다.

묶음(이벤트화) 원칙 — 알림 피로도를 줄이기 위함
  - 같은 항목·품종에서 시간 간격이 짧은(테이블별 merge_gap 이내) 위반점은 하나의 이벤트로 묶는다.
  - 규격/관리기준 이탈 이벤트와 기간이 겹치는 SPC 패턴은 별도 이벤트로 만들지 않고
    '동반 패턴'으로 기록한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .spc import ControlStats, baseline_stats, rule_flags, rule_name
from .standards import TABLES, SpecRegistry
from .store import DataStore

SEVERITY_ORDER = {"위험": 3, "경고": 2, "주의": 1, "정상": 0}
SEVERITY_COLOR = {"위험": "#C62828", "경고": "#EF6C00", "주의": "#F9A825", "정상": "#2E7D32"}
SEVERITY_ICON = {"위험": "🔴", "경고": "🟠", "주의": "🟡", "정상": "🟢"}
MAX_GAP = 3  # (시간 정보가 없을 때) 위반점 사이 위치 차이가 이 값 이하이면 같은 이벤트


def _cap_prediction(sev: str) -> str:
    """예측값은 실측이 아니므로 최고 심각도를 '경고'로 제한한다."""
    return "경고" if sev == "위험" else sev


@dataclass
class AlertEvent:
    event_id: str
    item_key: str
    item_name: str
    stage: str
    product: str | None
    severity: str
    rule: str                 # KS / SPEC / R1 / R2 / R3 / R5 / R6
    rule_desc: str
    direction: str            # high / low
    start: pd.Timestamp
    end: pd.Timestamp
    n_points: int
    worst_value: float
    limit_value: float | None
    unit: str
    decimals: int
    message: str
    patterns: list[str] = field(default_factory=list)
    is_prediction: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["patterns"] = ", ".join(self.patterns)
        return d

    @property
    def label(self) -> str:
        prod = f"[{self.product}] " if self.product else ""
        return f"{SEVERITY_ICON[self.severity]} {prod}{self.item_name} — {self.rule_desc}"


def _event_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _group_positions(pos: np.ndarray, times: pd.DatetimeIndex | None = None,
                     max_gap: pd.Timedelta | None = None) -> list[np.ndarray]:
    """위반점 위치를 이벤트로 묶는다. times/max_gap 이 주어지면 시간 간격 기준으로 묶는다."""
    if len(pos) == 0:
        return []
    groups, cur = [], [pos[0]]
    for p in pos[1:]:
        if times is not None and max_gap is not None:
            close = (times[p] - times[cur[-1]]) <= max_gap
        else:
            close = (p - cur[-1]) <= MAX_GAP
        if close:
            cur.append(p)
        else:
            groups.append(np.array(cur))
            cur = [p]
    groups.append(np.array(cur))
    return groups


def merge_gap(item) -> pd.Timedelta:
    """같은 이벤트로 묶는 최대 시간 간격(테이블 설정)."""
    return pd.Timedelta(TABLES[item.table].get("merge_gap", "12h"))


def _fmt(v: float | None, nd: int) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v:,.{nd}f}"


def _period(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start == end:
        return f"{start:%m/%d %H:%M}"
    return f"{start:%m/%d %H:%M} ~ {end:%m/%d %H:%M}"


def detect_item_events(series: pd.Series, item, product: str | None, settings: dict,
                       stats: ControlStats | None = None) -> list[AlertEvent]:
    """단일 항목·품종 시계열에서 이벤트를 검출한다."""
    s = series.dropna()
    if len(s) == 0:
        return []
    x = s.to_numpy(dtype=float)
    idx = s.index
    lim = item.limits_for(product)
    nd = item.decimals
    events: list[AlertEvent] = []

    # 1) 규격/관리기준 이탈 -------------------------------------------------
    ks_hi = (x > lim.ks_max) if lim.ks_max is not None else np.zeros(len(x), bool)
    ks_lo = (x < lim.ks_min) if lim.ks_min is not None else np.zeros(len(x), bool)
    sp_hi = (x > lim.usl) if lim.usl is not None else np.zeros(len(x), bool)
    sp_lo = (x < lim.lsl) if lim.lsl is not None else np.zeros(len(x), bool)
    limit_spans: list[tuple[int, int]] = []

    for direction, ks_m, sp_m in (("high", ks_hi, sp_hi), ("low", ks_lo, sp_lo)):
        mask = ks_m | sp_m
        for g in _group_positions(np.flatnonzero(mask), idx, merge_gap(item)):
            any_ks = bool(ks_m[g].any())
            vals = x[g]
            worst = float(vals.max() if direction == "high" else vals.min())
            if any_ks:
                rule = "KS"
                sev = "경고" if item.ks_is_method else "위험"
                lv = lim.ks_max if direction == "high" else lim.ks_min
                desc = ("KS 시험조건 " if item.ks_is_method else "KS 규격 ") + ("상한 초과" if direction == "high" else "하한 미달")
            else:
                rule, sev = "SPEC", "경고"
                lv = lim.usl if direction == "high" else lim.lsl
                desc = "사내 관리기준 " + ("상한 초과" if direction == "high" else "하한 미달")
            if item.prediction:
                sev = _cap_prediction(sev)
                desc += "(예측)"
            start, end = idx[g[0]], idx[g[-1]]
            limit_spans.append((g[0], g[-1]))
            prod = f"[{product}] " if product else ""
            msg = (f"{prod}{item.name} {desc} — 기준 {_fmt(lv, nd)} {item.unit}, "
                   f"{'최대' if direction == 'high' else '최소'} {_fmt(worst, nd)} {item.unit}, "
                   f"{len(g)}점 ({_period(start, end)})")
            events.append(AlertEvent(
                _event_id(item.key, product, "LIMIT", direction, start.isoformat()), item.key, item.name,
                item.stage, product, sev, rule, desc, direction, start, end, len(g), worst, lv,
                item.unit, nd, msg, is_prediction=item.prediction))

    # 2) SPC 판정규칙 (고빈도 데이터는 근무조 평균에 적용) ---------------------
    enabled = [r for r in item.rules if r in settings.get("enabled_rules", [])]
    spc_s = spc_series(s, item)
    if enabled and len(spc_s) >= 10:
        stats = stats or baseline_stats(spc_s, settings)
        if stats is not None:
            run_l, trend_l = settings.get("run_length", 9), settings.get("trend_length", 6)
            xs, ts = spc_s.to_numpy(dtype=float), spc_s.index
            bin_width = pd.Timedelta(TABLES[item.table].get("spc_resample") or "0s")
            basis = f" [{TABLES[item.table]['spc_resample']} 평균]" if bin_width > pd.Timedelta(0) else ""
            spans = [(idx[a], idx[b]) for a, b in limit_spans]
            flags = rule_flags(xs, stats, enabled, run_l, trend_l)
            for code, fl in flags.items():
                for g in _group_positions(np.flatnonzero(fl), ts, merge_gap(item) + bin_width):
                    g_start, g_end = ts[g[0]], ts[g[-1]] + bin_width
                    overlap = [i for i, (a, b) in enumerate(spans) if not (g_end < a or g_start > b)]
                    if overlap:
                        for i in overlap:
                            if code not in events[i].patterns:
                                events[i].patterns.append(code)
                        continue
                    vals = xs[g]
                    if code == "R3":
                        direction = "high" if vals[-1] >= vals[0] else "low"
                    else:
                        direction = "high" if float(np.mean(vals) - stats.center) >= 0 else "low"
                    worst = float(vals.max() if direction == "high" else vals.min())
                    desc = rule_name(code, run_l, trend_l) + ("(예측)" if item.prediction else "")
                    lv = stats.ucl if direction == "high" else stats.lcl
                    prod = f"[{product}] " if product else ""
                    arrow = "↑" if direction == "high" else "↓"
                    end_ts = ts[g[-1]] + (bin_width - pd.Timedelta(seconds=1) if bin_width > pd.Timedelta(0) else pd.Timedelta(0))
                    msg = (f"{prod}{item.name} {desc}{basis} {arrow} — 중심 {_fmt(stats.center, nd)}, "
                           f"{'최대' if direction == 'high' else '최소'} {_fmt(worst, nd)} {item.unit}, "
                           f"{len(g)}점 ({_period(ts[g[0]], end_ts)})")
                    events.append(AlertEvent(
                        _event_id(item.key, product, code, ts[g[0]].isoformat()), item.key, item.name, item.stage,
                        product, "주의", code, desc, direction, ts[g[0]], end_ts, len(g), worst, lv, item.unit, nd,
                        msg, is_prediction=item.prediction))
    return events


def spc_series(series: pd.Series, item) -> pd.Series:
    """SPC 판정에 쓰는 시계열: 테이블 설정(spc_resample)에 따라 근무조 평균으로 집계."""
    rule = TABLES[item.table].get("spc_resample")
    s = series.dropna()
    if not rule or len(s) == 0:
        return s
    return s.resample(rule).mean().dropna()


def detect_events(store: DataStore, registry: SpecRegistry, settings: dict,
                  start=None, end=None) -> list[AlertEvent]:
    """전 항목 이벤트 검출. start/end 로 이벤트 기간(종료 시각 기준)을 필터링한다."""
    events: list[AlertEvent] = []
    for item in registry.all():
        if not (item.limits or item.rules):
            continue
        for product in registry.products_for(item.key):
            s = store.series(item.key, registry, product)
            if len(s) == 0:
                continue
            events.extend(detect_item_events(s, item, product, settings))
    if start is not None:
        events = [e for e in events if e.end >= pd.Timestamp(start)]
    if end is not None:
        events = [e for e in events if e.start <= pd.Timestamp(end)]
    events.sort(key=lambda e: (e.end, SEVERITY_ORDER[e.severity]), reverse=True)
    return events


def events_frame(events: list[AlertEvent], status: pd.DataFrame | None = None) -> pd.DataFrame:
    """이벤트 목록 → 표. status(알림 처리상태)를 병합한다."""
    cols = ["event_id", "severity", "stage", "product", "item_name", "rule_desc", "direction", "start", "end",
            "n_points", "worst_value", "limit_value", "unit", "patterns", "message", "item_key", "rule",
            "is_prediction"]
    if not events:
        df = pd.DataFrame(columns=cols + ["status", "assignee", "note", "notified"])
        return df
    df = pd.DataFrame([e.to_dict() for e in events])[cols]
    if status is not None and len(status):
        df = df.merge(status[["event_id", "status", "assignee", "note", "notified"]], on="event_id", how="left")
    for c, default in (("status", "신규"), ("assignee", ""), ("note", ""), ("notified", 0)):
        if c not in df:
            df[c] = default
        df[c] = df[c].fillna(default)
    return df


def latest_status(store: DataStore, registry: SpecRegistry, settings: dict,
                  events: list[AlertEvent] | None = None, recent_points: int = 1) -> pd.DataFrame:
    """핵심관리항목의 최신값과 현재 상태(가장 최근 점이 속한 이벤트의 심각도)."""
    events = events if events is not None else detect_events(store, registry, settings)
    rows = []
    for item in registry.key_items():
        for product in registry.products_for(item.key):
            s = store.series(item.key, registry, product)
            if len(s) == 0:
                continue
            last_ts = s.index[-recent_points]
            sev = "정상"
            for e in events:
                if e.item_key == item.key and e.product == product and e.end >= last_ts:
                    if SEVERITY_ORDER[e.severity] > SEVERITY_ORDER[sev]:
                        sev = e.severity
            lim = item.limits_for(product)
            rows.append({"stage": item.stage, "item_key": item.key, "item_name": item.name, "product": product,
                         "unit": item.unit, "decimals": item.decimals, "last_time": s.index[-1],
                         "last_value": float(s.iloc[-1]), "target": lim.target, "lsl": lim.lsl, "usl": lim.usl,
                         "ks_min": lim.ks_min, "ks_max": lim.ks_max, "status": sev})
    return pd.DataFrame(rows)
