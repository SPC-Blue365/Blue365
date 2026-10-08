"""증거 기반 원인 진단 → 5단계 분석 보고.

① 현상 정의와 정량화
② 원인 가설 5축(화학·원료·공정·설비·시험오차) 우선순위화 — 데이터 증거로 점수화
③ 가설별 확인 방법(데이터·시험)
④ 단기 조치 vs 근본 대책
⑤ KS 규격·사내 관리기준 대비 평가

증거 점수 계산
  - 관련 항목의 '이벤트 구간 평균'을 '직전 기준기간(기본 14일) 평균·표준편차'와 비교한 효과크기
    d = (구간 평균 − 기준 평균) / 기준 σ 를 구한다.
  - 기대 방향으로 d ≥ 2 이면 지지도 +1, d ≈ 0.5 이면 0, 반대 방향이면 음수(최소 −1).
  - 가설 점수 = 사전가중치 × (1 + 1.5 × 가중평균 지지도). 데이터가 없는 가설은 사전가중치 × 0.6.
  - 순위 = 판정 등급 우선(데이터 지지 → 부분 확인 → 데이터 없음 → 근거 약함 → 반증), 같은 등급은 점수 순.
판정 표기 — 사용자 요청에 따라 사실과 추정을 구분한다.
  데이터 지지 / 부분 확인 / 근거 약함 / 반증(가능성 낮음) / 데이터 없음(추정)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .alerts import AlertEvent
from .knowledge import AXIS_ICON, Check, Hypothesis, Phenomenon, lookup
from .standards import TABLES, SpecRegistry
from .store import DataStore

VERDICT_ORDER = ["데이터 지지", "부분 확인", "데이터 없음(추정)", "근거 약함", "반증(가능성 낮음)"]  # 정렬 우선순위
VERDICT_LEGEND = ("판정 표기 — '데이터 지지': 가설이 예상하는 변화가 측정 데이터에서 실제로 확인됨(사실). "
                  "단, 인과관계는 현장 확인으로 확정해야 함. '데이터 없음(추정)': 측정 데이터가 없어 경험칙으로만 제시한 가설. "
                  "'반증': 가설이 예상하는 변화가 데이터에 나타나지 않음.")
VERDICT_ICON = {"데이터 지지": "✅", "부분 확인": "☑️", "데이터 없음(추정)": "❔",
                "근거 약함": "▫️", "반증(가능성 낮음)": "✖️"}

# 이벤트 테이블 → 하류 제품 항목을 볼 구간(lag, 시간). 음수 = 이벤트 이후
DOWNSTREAM_LAG = {"raw_meal": (-72, -12), "kiln": (-60, -12), "clinker": (-60, -12), "cement": (-12, 12),
                  "physical": (0, 0), "xrd": (-60, -12)}


@dataclass
class Evidence:
    check: Check
    item_name: str
    support: float | None
    status: str
    text: str
    window_mean: float | None = None
    base_mean: float | None = None
    effect: float | None = None


@dataclass
class HypothesisResult:
    hyp: Hypothesis
    evidences: list[Evidence]
    support: float | None
    score: float
    verdict: str

    @property
    def evidence_score(self) -> int | None:
        return None if self.support is None else int(round(50 + 50 * self.support))

    @property
    def supported(self) -> bool:
        return self.verdict in ("데이터 지지", "부분 확인")


@dataclass
class Diagnosis:
    event: AlertEvent
    phenomenon: Phenomenon
    registered: bool
    quant: dict
    results: list[HypothesisResult]
    ks_eval: list[dict]
    summary: str
    short_term: list[tuple[str, str]] = field(default_factory=list)
    root_cause: list[tuple[str, str]] = field(default_factory=list)

    def verification_plan(self, top: int = 8) -> pd.DataFrame:
        rows = []
        for i, r in enumerate(self.results[:top], 1):
            due = {"데이터 지지": "즉시(24시간 내)", "부분 확인": "3일 이내",
                   "데이터 없음(추정)": "3일 이내(현장 확인)"}.get(r.verdict, "필요 시")
            rows.append({"순위": i, "축": r.hyp.axis, "원인 가설": r.hyp.title, "판정": r.verdict,
                         "근거 점수": r.evidence_score if r.evidence_score is not None else "-",
                         "확인 방법(데이터·시험)": " / ".join(r.hyp.verify), "담당(제안)": r.hyp.owner, "기한": due})
        return pd.DataFrame(rows)


def _window(event: AlertEvent, lag: tuple[float, float]) -> tuple[pd.Timestamp, pd.Timestamp]:
    a, b = lag
    return event.start - pd.Timedelta(hours=b), event.end - pd.Timedelta(hours=a)


def _support_level(d: float) -> float:
    return float(np.clip((d - 0.5) / 1.5, -1, 1))


def _status(s: float | None) -> str:
    if s is None:
        return "데이터 없음"
    if s >= 0.4:
        return "지지"
    if s >= 0.1:
        return "약한 지지"
    if s > -0.4:
        return "변화 없음"
    return "반대 경향"


def _product_for(item, event: AlertEvent) -> str | None:
    return event.product if TABLES[item.table]["by_product"] else None


def _baseline(s: pd.Series, ws: pd.Timestamp, days: int) -> pd.Series:
    base = s[(s.index >= ws - pd.Timedelta(days=days)) & (s.index < ws)]
    if len(base) < 3:
        base = s[s.index < ws].tail(30)
    return base


def evaluate_check(check: Check, event: AlertEvent, store: DataStore, registry: SpecRegistry,
                   settings: dict) -> Evidence:
    days = int(settings.get("evidence_baseline_days", 14))
    ws, we = _window(event, check.lag)

    if check.item == "__isolated":
        isolated = event.n_points <= 2
        sup = 0.8 if isolated else -0.6
        sup = -sup if check.invert else sup
        return Evidence(check, "이벤트 지속성", sup, _status(sup),
                        f"이벤트 {event.n_points}점 — {'단발성(재분석 권장)' if isolated else '지속성 이탈(단발 아님)'}")

    if check.item == "__resid":
        phy = store.tables.get("physical", pd.DataFrame())
        if "resid_z" not in phy:
            return Evidence(check, "예측 잔차", None, "데이터 없음", "예측 모델 미학습")
        m = (phy["timestamp"] >= ws) & (phy["timestamp"] <= we)
        if event.product:
            m &= phy["product"] == event.product
        z = phy.loc[m, "resid_z"].dropna()
        if len(z) == 0:
            return Evidence(check, "예측 잔차", None, "데이터 없음", "해당 로트의 7일 강도 기반 예측 잔차 없음")
        zv = float(z.mean())
        sup = float(np.clip((-zv - 1) / 1.5, -1, 1))
        sup = -sup if check.invert else sup
        meaning = ("조기강도로 설명되지 않는 저하 → 시험오차·후기강도 요인 의심" if sup >= 0.4 else
                   "조기강도로 일부 설명되지 않는 편차" if sup >= 0.1 else "조기강도와 일관된 결과")
        return Evidence(check, "28일 실측−조기강도 예측 잔차", sup, _status(sup),
                        f"28일 실측 − 7일 강도 기반 예측 = 평균 {zv:+.1f}σ ({len(z)}로트, {meaning})", effect=zv)

    if check.expect == "change":  # 문자열 열(예: 표준사 Lot) 변경 여부 — physical 테이블 기록
        df = store.tables.get("physical", pd.DataFrame())
        return _evidence_change(check, event, df, ws, we, event.product)

    item = registry.get(check.item)
    if item is None:
        return Evidence(check, check.item, None, "데이터 없음", f"{check.item}: 항목 정의 없음")
    product = _product_for(item, event)

    s = store.series(check.item, registry, product)
    win = s[(s.index >= ws) & (s.index <= we)]
    base = _baseline(s, ws, days)
    nd = item.decimals
    if len(win) == 0 or len(base) < 3:
        return Evidence(check, item.name, None, "데이터 없음", f"{item.name}: 비교 데이터 부족")
    mw, mb = float(win.mean()), float(base.mean())
    sd = float(base.std(ddof=1)) if len(base) > 2 else float("nan")
    if not np.isfinite(sd) or sd <= 0:
        sd = float(s.std(ddof=1)) if len(s) > 2 else 1.0
        sd = sd if np.isfinite(sd) and sd > 0 else 1.0

    if check.expect in ("high", "low"):
        d = (mw - mb) / sd
        sup = _support_level(d if check.expect == "high" else -d)
        text = (f"{item.name}: 기준 {mb:,.{nd}f} → 구간 {mw:,.{nd}f} {item.unit} "
                f"(Δ {mw - mb:+,.{nd}f}, {d:+.1f}σ)")
    elif check.expect == "var":
        if len(win) < 3:
            return Evidence(check, item.name, None, "데이터 없음", f"{item.name}: 변동성 평가 데이터 부족")
        ratio = float(win.std(ddof=1)) / sd
        d = ratio
        sup = float(np.clip((ratio - 1.2) / 0.8, -1, 1))
        text = f"{item.name} 변동(σ): 기준 {sd:.{nd + 1}f} → 구간 {win.std(ddof=1):.{nd + 1}f} (×{ratio:.2f})"
    elif check.expect == "dev":
        target = item.limits_for(product).target
        target = target if target is not None else mb
        dw, db = float((win - target).abs().mean()), float((base - target).abs().mean())
        d = (dw - db) / sd
        sup = _support_level(d)
        text = (f"{item.name} 목표({target:,.{nd}f}) 대비 평균 편차: 기준 {db:.{nd}f} → 구간 {dw:.{nd}f} {item.unit} "
                f"(구간 평균 {mw:,.{nd}f})")
    elif check.expect == "out":
        lim = item.limits_for(product)
        lo = [v for v in (lim.ks_min, lim.lsl) if v is not None]
        hi = [v for v in (lim.ks_max, lim.usl) if v is not None]
        lo_v, hi_v = (max(lo) if lo else None), (min(hi) if hi else None)
        n_out = int(((win < lo_v).sum() if lo_v is not None else 0) + ((win > hi_v).sum() if hi_v is not None else 0))
        d = float(n_out)
        sup = 1.0 if n_out > 0 else -0.4
        rng = f"{'' if lo_v is None else f'{lo_v:g}'}~{'' if hi_v is None else f'{hi_v:g}'}"
        text = (f"{item.name}: 구간 {win.min():,.{nd}f}~{win.max():,.{nd}f} {item.unit}, 기준({rng}) "
                + (f"이탈 {n_out}건" if n_out else "이내"))
    else:
        return Evidence(check, item.name, None, "데이터 없음", f"알 수 없는 조건: {check.expect}")

    if check.invert:
        sup = -sup
        text += " — 하류/연관 항목 변화가 없을수록 이 가설을 지지"
    return Evidence(check, item.name, sup, _status(sup), text, mw, mb, d)


def _evidence_change(check: Check, event: AlertEvent, df: pd.DataFrame, ws, we, product) -> Evidence:
    col = check.item
    if len(df) == 0 or col not in df:
        return Evidence(check, col, None, "데이터 없음", f"{col}: 기록 없음")
    d = df if product is None or "product" not in df else df[df["product"] == product]
    win = d[(d["timestamp"] >= ws) & (d["timestamp"] <= we)][col].dropna()
    prev = d[d["timestamp"] < ws][col].dropna()
    if len(win) == 0 or len(prev) == 0:
        return Evidence(check, col, None, "데이터 없음", f"{col}: 비교 기록 부족")
    changed = bool(set(win.astype(str)) - {str(prev.iloc[-1])})
    sup = 0.6 if changed else -0.3
    label = "표준사 Lot" if col == "sand_lot" else col
    text = (f"{label}: 직전 {prev.iloc[-1]} → 구간 {', '.join(sorted(set(win.astype(str))))} "
            f"({'변경됨' if changed else '변경 없음'})")
    return Evidence(check, label, sup, _status(sup), text)


def evaluate_hypothesis(h: Hypothesis, event: AlertEvent, store: DataStore, registry: SpecRegistry,
                        settings: dict) -> HypothesisResult:
    # 이벤트 항목 자신을 증거로 쓰면 순환논리가 되므로 제외한다.
    evs = [evaluate_check(c, event, store, registry, settings) for c in h.checks if c.item != event.item_key]
    usable = [(e.support, e.check.weight) for e in evs if e.support is not None]
    if usable:
        w = sum(wt for _, wt in usable)
        S = sum(s * wt for s, wt in usable) / w
        score = max(h.prior * (1 + 1.5 * S), 0.05)
        if S >= 0.4:
            verdict = "데이터 지지"
        elif S >= 0.1:
            verdict = "부분 확인"
        elif S > -0.4:
            verdict = "근거 약함"
        else:
            verdict = "반증(가능성 낮음)"
    else:
        S, score, verdict = None, h.prior * 0.6, "데이터 없음(추정)"
    return HypothesisResult(h, evs, S, score, verdict)


def _quantify(event: AlertEvent, store: DataStore, registry: SpecRegistry, settings: dict) -> dict:
    item = registry[event.item_key]
    s = store.series(event.item_key, registry, event.product)
    win = s[(s.index >= event.start) & (s.index <= event.end)]
    base = _baseline(s, event.start, int(settings.get("evidence_baseline_days", 14)))
    nd = item.decimals
    lim = item.limits_for(event.product)
    q = {"item": item.name, "unit": item.unit, "decimals": nd, "product": event.product, "start": event.start,
         "end": event.end, "duration_h": (event.end - event.start).total_seconds() / 3600,
         "n": int(len(win)), "mean": float(win.mean()) if len(win) else np.nan,
         "min": float(win.min()) if len(win) else np.nan, "max": float(win.max()) if len(win) else np.nan,
         "base_mean": float(base.mean()) if len(base) else np.nan,
         "base_std": float(base.std(ddof=1)) if len(base) > 2 else np.nan,
         "limit": event.limit_value, "rule": event.rule_desc, "severity": event.severity,
         "target": lim.target, "patterns": list(event.patterns)}
    q["delta"] = q["mean"] - q["base_mean"]
    q["delta_pct"] = q["delta"] / q["base_mean"] * 100 if q["base_mean"] else np.nan
    q["effect"] = q["delta"] / q["base_std"] if q["base_std"] and np.isfinite(q["base_std"]) else np.nan
    n_ex = 0
    if len(win):
        if event.direction == "high" and event.limit_value is not None:
            n_ex = int((win > event.limit_value).sum())
        elif event.direction == "low" and event.limit_value is not None:
            n_ex = int((win < event.limit_value).sum())
    q["n_exceed"] = n_ex
    dur = q["duration_h"]
    dur_txt = f"{dur / 24:.1f}일" if dur >= 48 else f"{dur:.0f}시간" if dur > 0 else "단일 시점"
    prod = f"[{event.product}] " if event.product else ""
    ks_word = "KS 기준" if item.ks_label == "KS" else item.ks_label
    limit_word = "관리한계" if event.rule.startswith("R") else (ks_word if event.rule == "KS" else "사내 관리기준")
    q["limit_word"] = limit_word
    q["text"] = (
        f"{prod}{item.name}이(가) {event.start:%Y-%m-%d %H:%M} ~ {event.end:%Y-%m-%d %H:%M} ({dur_txt}) 동안 "
        f"{event.rule_desc}. 구간 {q['n']}점 중 {n_ex}점이 {limit_word}({_f(event.limit_value, nd)} {item.unit})을 벗어났고, "
        f"구간 평균 {_f(q['mean'], nd)} {item.unit} (직전 기준기간 {_f(q['base_mean'], nd)}, "
        f"Δ {q['delta']:+,.{nd}f} / {q['delta_pct']:+.1f}% / {q['effect']:+.1f}σ), "
        f"{'최대' if event.direction == 'high' else '최소'} {_f(event.worst_value, nd)} {item.unit}.")
    return q


def _f(v, nd):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v:,.{nd}f}"


def _ks_evaluation(event: AlertEvent, ph: Phenomenon, store: DataStore, registry: SpecRegistry) -> list[dict]:
    rows = []
    ev_item = registry[event.item_key]
    keys = [event.item_key] + [k for k in ph.related_products if k != event.item_key]
    for key in keys:
        item = registry.get(key)
        if item is None:
            continue
        if key == event.item_key:
            ws, we = event.start, event.end
        else:
            ws, we = _window(event, DOWNSTREAM_LAG.get(ev_item.table, (-60, -12)))
        products = ([event.product] if (event.product and TABLES[item.table]["by_product"])
                    else registry.products_for(key))
        for product in products:
            lim = item.limits_for(product)
            s = store.series(key, registry, product)
            win = s[(s.index >= ws) & (s.index <= we)]
            nd = item.decimals
            row = {"항목": item.name, "품종": product or "-", "평가 구간": f"{ws:%m/%d %H:%M} ~ {we:%m/%d %H:%M}",
                   "시료 수": len(win), "평균": _f(float(win.mean()), nd) if len(win) else "-",
                   "최소~최대": f"{_f(float(win.min()), nd)} ~ {_f(float(win.max()), nd)}" if len(win) else "-",
                   "KS 기준": ("" if item.ks_label == "KS" or (lim.ks_min is None and lim.ks_max is None)
                              else f"{item.ks_label} ") + _limit_text(lim.ks_min, lim.ks_max, nd),
                   "사내 기준": _limit_text(lim.lsl, lim.usl, nd),
                   "근거": item.ks_ref or item.basis}
            if len(win) == 0:
                pred_note = ""
                if key == "phy_s28":
                    p = store.series("pred_s28", registry, product)
                    pw = p[(p.index >= ws) & (p.index <= we)]
                    if len(pw):
                        pred_note = f" — 예측 평균 {pw.mean():.1f} MPa (최소 {pw.min():.1f})"
                row["KS 판정"] = "결과 미도래" + pred_note
                row["사내기준 판정"] = "-"
                rows.append(row)
                continue
            n_ks = int(((win < lim.ks_min).sum() if lim.ks_min is not None else 0)
                       + ((win > lim.ks_max).sum() if lim.ks_max is not None else 0))
            n_sp = int(((win < lim.lsl).sum() if lim.lsl is not None else 0)
                       + ((win > lim.usl).sum() if lim.usl is not None else 0))
            if lim.ks_min is None and lim.ks_max is None:
                ks_txt = "해당 없음(중간 공정 항목)"
            elif n_ks:
                ks_txt = f"부적합 {n_ks}건 — 출하 판정·고객 영향 검토 필요"
            else:
                margin = []
                if lim.ks_min is not None:
                    margin.append(f"하한 여유 {win.min() - lim.ks_min:+,.{nd}f}")
                if lim.ks_max is not None:
                    margin.append(f"상한 여유 {lim.ks_max - win.max():+,.{nd}f}")
                ks_txt = "적합 (" + ", ".join(margin) + f" {item.unit})"
            row["KS 판정"] = ks_txt
            row["사내기준 판정"] = (f"이탈 {n_sp}건" if n_sp else "적합") if (lim.lsl is not None or lim.usl is not None) else "-"
            rows.append(row)
    return rows


def _limit_text(lo, hi, nd) -> str:
    if lo is None and hi is None:
        return "-"
    if lo is not None and hi is not None:
        return f"{lo:,.{nd}f} ~ {hi:,.{nd}f}"
    return f"{lo:,.{nd}f} 이상" if lo is not None else f"{hi:,.{nd}f} 이하"


def _summary(event: AlertEvent, results: list[HypothesisResult], quant: dict, registered: bool) -> str:
    sup = [r for r in results if r.supported]
    if not registered:
        return ("이 항목은 지식베이스에 상세 원인 가설이 등록되어 있지 않아 5축 기본 점검 항목을 제시합니다(추정). "
                "현장 확인 결과를 지식베이스에 등록하면 다음부터 자동 진단됩니다.")
    if sup:
        top = sup[0]
        ev_txt = "; ".join(e.text for e in top.evidences if e.support is not None and e.support >= 0.4)[:400]
        msg = (f"가장 유력한 원인은 [{top.hyp.axis}] {top.hyp.title}입니다(근거 점수 {top.evidence_score}, "
               f"{top.verdict}). 근거: {ev_txt or '연관 지표 변화'}.")
        others = [f"[{r.hyp.axis}] {r.hyp.title}" for r in sup[1:3]]
        if others:
            msg += " 함께 데이터로 확인된 요인: " + ", ".join(others) + "."
        if any(r.hyp.axis == "시험오차" for r in sup):
            msg += " ※ 시험오차 가설이 지지되므로 재시험으로 결과를 확정한 뒤 공정 조치를 판단하십시오."
        return msg
    cands = [f"[{r.hyp.axis}] {r.hyp.title}" for r in results[:3]]
    return ("데이터로 뒷받침되는 원인이 없습니다. 경험상 빈도가 높은 " + ", ".join(cands)
            + " 순으로 현장 확인이 필요합니다(추정 — 측정 데이터가 없는 설비·원료 요인일 가능성).")


def _actions(results: list[HypothesisResult]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    chosen = [r for r in results if r.supported][:3] or results[:2]
    st, rc, seen_s, seen_r = [], [], set(), set()
    for r in chosen:
        tag = f"[{r.hyp.axis}] {r.hyp.title}"
        for a in r.hyp.short_term:
            if a not in seen_s:
                st.append((a, tag))
                seen_s.add(a)
        for a in r.hyp.root_cause:
            if a not in seen_r:
                rc.append((a, tag))
                seen_r.add(a)
    return st, rc


def diagnose(event: AlertEvent, store: DataStore, registry: SpecRegistry, settings: dict) -> Diagnosis:
    ph, registered = lookup(event.item_key, event.direction, event.item_name)
    results = [evaluate_hypothesis(h, event, store, registry, settings) for h in ph.hypotheses]
    # 정렬: 판정 등급(데이터 지지 > 부분 확인 > 데이터 없음 > 근거 약함 > 반증) → 같은 등급 안에서 점수 순.
    # 데이터로 뒷받침된 가설이 경험상 빈도만 높은 가설보다 항상 먼저 오도록 해 설명 가능성을 높인다.
    results.sort(key=lambda r: (-VERDICT_ORDER.index(r.verdict), r.score), reverse=True)
    quant = _quantify(event, store, registry, settings)
    ks_eval = _ks_evaluation(event, ph, store, registry)
    summary = _summary(event, results, quant, registered)
    st, rc = _actions(results)
    return Diagnosis(event, ph, registered, quant, results, ks_eval, summary, st, rc)


def diagnosis_markdown(dx: Diagnosis) -> str:
    """진단 결과를 마크다운 텍스트로(메일·회의록 붙여넣기용)."""
    e, q = dx.event, dx.quant
    lines = [f"# 품질 이상 분석 — {dx.phenomenon.title}", "",
             f"- 심각도: {e.severity} / 판정규칙: {e.rule_desc}" + (f" / 동반 패턴: {', '.join(e.patterns)}" if e.patterns else ""),
             f"- 영향: {dx.phenomenon.impact}", "", "## ① 현상 정의와 정량화", q["text"], "",
             "## 종합 판단", dx.summary, "", "## ② 원인 가설 우선순위 (5축)",
             "| 순위 | 축 | 원인 가설 | 판정 | 근거 점수 |", "|---|---|---|---|---|"]
    for i, r in enumerate(dx.results, 1):
        lines.append(f"| {i} | {AXIS_ICON.get(r.hyp.axis, '')} {r.hyp.axis} | {r.hyp.title} | {r.verdict} | "
                     f"{r.evidence_score if r.evidence_score is not None else '-'} |")
    lines += ["", "## ③ 가설별 확인 방법"]
    for i, r in enumerate(dx.results, 1):
        lines.append(f"**{i}. [{r.hyp.axis}] {r.hyp.title}** — {r.hyp.mechanism} (근거: {r.hyp.basis})")
        for ev in r.evidences:
            lines.append(f"  - 데이터: {ev.text} → {ev.status}")
        for v in r.hyp.verify:
            lines.append(f"  - 확인: {v}")
    lines += ["", "## ④ 조치", "**단기 조치**"] + [f"- {a}  ({t})" for a, t in dx.short_term]
    lines += ["", "**근본 대책**"] + [f"- {a}  ({t})" for a, t in dx.root_cause]
    lines += ["", "## ⑤ KS 규격·관리기준 대비 평가", "| 항목 | 품종 | 구간 | 평균 | 최소~최대 | KS 기준 | KS 판정 | 사내 기준 | 사내 판정 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in dx.ks_eval:
        lines.append(f"| {r['항목']} | {r['품종']} | {r['평가 구간']} | {r['평균']} | {r['최소~최대']} | {r['KS 기준']} | "
                     f"{r['KS 판정']} | {r['사내 기준']} | {r['사내기준 판정']} |")
    lines += ["", "※ " + VERDICT_LEGEND]
    return "\n".join(lines)
