"""보는용 현황판 — 관리용 앱(Streamlit)과 나눈 조회 전용 화면.

경영진·다른 부서·현장이 설치 없이 보는 한 파일짜리 HTML(인터넷 불필요). 6개 탭:
종합 현황 · 공정 모니터링(호기·밀별) · 강도 예측(재령·품종) · 원인 진단(분류별 5단계) · 출하시멘트(품종별 KS) · 데이터 현황.
매일 자동반영(qms_monitor --sync-file … --snapshot <폴더>) 때 공유 드라이브의 현황판 폴더에 새로 만든다.
화면 틀은 qms/viewer_template.html, 숫자는 여기서 만든 JSON 한 덩어리로 넣는다.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .alerts import EVENT_CATEGORIES, SEVERITY_ORDER, event_category, latest_status
from .spc import capability
from .store import line_label, line_sort_key

TEMPLATE = Path(__file__).with_name("viewer_template.html")
MONITOR_ITEMS = (("clk_fcao", None), ("clk_lsf", None), ("rm_lsf", None), ("cem_blaine", "1종"), ("cem_so3", "1종"),
                 ("cem_r45", "1종"))
SHIP_KEYS = ("s1", "s3", "s7", "s28", "blaine", "so3", "mgo", "loi")
STAGE_EN = {"원료": "Raw meal", "소성(킬른)": "Kiln", "클링커": "Clinker", "시멘트(분쇄)": "Cement mill", "제품 물성": "Product"}
DX_PER_CATEGORY = 12          # 분류마다 원인 진단(5단계)까지 미리 계산해 넣는 이벤트 수(최근·심각한 순)
LIST_PER_CATEGORY = 60        # 분류마다 목록에 넣는 이벤트 수


def _num(v, nd=3):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def _ms(ts) -> int:
    return int(pd.Timestamp(ts).value // 1_000_000)


def _ref_end(store) -> pd.Timestamp:
    p = store.period()
    end = p[1] if p else pd.Timestamp.now()
    return min(pd.Timestamp(end), pd.Timestamp.now())


# ── 종합 현황 ───────────────────────────────────────────────────────────
def _overview(ctx, end, pred28, ship) -> dict:
    store, reg = ctx.store, ctx.registry
    kpis = []
    phy = store.tables.get("physical", pd.DataFrame())
    s28 = phy[(phy.get("product") == "1종") & phy["phy_s28"].notna()].sort_values("timestamp").tail(30) if len(phy) and "phy_s28" in phy else pd.DataFrame()
    lim28 = reg["phy_s28"].limits_for("1종")
    if len(s28):
        kpis.append({"label": "28일 강도 평균(1종, 최근 30로트)", "value": _num(s28["phy_s28"].mean(), 1), "unit": "MPa", "en": "28-day strength",
                     "sub": f"KS ≥ {lim28.ks_min:g}" + (f" · 사내 하한 {lim28.lsl:g}" if lim28.lsl is not None else ""),
                     "tone": "bad" if lim28.ks_min is not None and s28["phy_s28"].min() < lim28.ks_min else "ok"})
    p = pred28.get("1종")
    if p and p["due"]:
        mn = min(d["p"] for d in p["due"])
        kpis.append({"label": f"28일 강도 예측 최저(결과 미도래 {len(p['due'])}로트)", "value": _num(mn, 1), "unit": "MPa", "en": "Predicted 28-day",
                     "sub": "앞 재령 강도로 회귀 예측(추정)", "tone": "warn" if lim28.lsl is not None and mn < lim28.lsl else "ok"})
    item = reg.get("clk_fcao")
    lines = store.item_lines("clk_fcao", reg) or [None]
    worst = None
    for ln in lines:
        s = store.series("clk_fcao", reg, None, line=ln)
        if len(s) and (worst is None or s.iloc[-1] > worst[1]):
            worst = (ln, float(s.iloc[-1]), s.index[-1])
    if worst and item:
        lim = item.limits_for(None)
        kpis.append({"label": f"클링커 f-CaO 최신 최고({worst[0] or '전체'})", "value": _num(worst[1], 2), "unit": "%", "en": "Free lime",
                     "sub": f"{worst[2]:%m/%d %H:%M} · 사내 상한 {lim.usl:g}" if lim.usl is not None else f"{worst[2]:%m/%d %H:%M}",
                     "tone": "warn" if lim.usl is not None and worst[1] > lim.usl else "ok"})
    sp = ship.get("products", {}).get("1종")
    if sp and sp["n"]:
        kpis.append({"label": "출하 KS 판정(1종, 최근 30로트)", "value": f"{sp['pass']}/{sp['n']}", "unit": "", "en": "KS conformity",
                     "ring": round(100 * sp["pass"] / sp["n"]),
                     "sub": "강도·화학·분말도 KS 적합 로트", "tone": "ok" if sp["pass"] == sp["n"] else "bad"})

    stat = latest_status(store, reg, ctx.settings, ctx.events)
    stages = []
    for stage in ("원료", "소성(킬른)", "클링커", "시멘트(분쇄)", "제품 물성"):
        sub = stat[stat["stage"] == stage] if len(stat) else stat
        if not len(sub):
            continue
        sub = sub.assign(_o=sub["status"].map(SEVERITY_ORDER)).sort_values("_o", ascending=False)
        w = sub.iloc[0]
        bad = sub[sub["status"] != "정상"]
        text = ", ".join(bad["item_name"].head(3)) + (f" 외 {len(bad) - 3}" if len(bad) > 3 else "") if len(bad) else "핵심 항목 관리 범위"
        stages.append({"stage": stage, "en": STAGE_EN.get(stage, ""), "status": w["status"], "text": text, "n": int(len(sub))})

    rec = [e for e in ctx.events if e.severity in ("위험", "경고") and e.end >= end - pd.Timedelta(days=14)]
    rec.sort(key=lambda e: (SEVERITY_ORDER[e.severity], e.end), reverse=True)
    alerts = [{"id": e.event_id, "sev": e.severity, "item": e.item_name + (f" [{e.product}]" if e.product else ""),
               "desc": e.rule_desc, "period": f"{e.start:%m/%d} ~ {e.end:%m/%d}", "cat": event_category(e)} for e in rec[:8]]
    sev = {k: sum(e.severity == k for e in ctx.events if e.end >= end - pd.Timedelta(days=14)) for k in ("위험", "경고", "주의")}
    return {"kpis": kpis, "stages": stages, "alerts": alerts, "n_recent": len(rec), "sev": sev}


# ── 공정 모니터링 ───────────────────────────────────────────────────────
def _monitor(ctx, end, days=60) -> dict:
    store, reg = ctx.store, ctx.registry
    start = end - pd.Timedelta(days=days)
    items = []
    for key, prod in MONITOR_ITEMS:
        it = reg.get(key)
        if it is None:
            continue
        lines = store.item_lines(key, reg, prod) or [None]
        lim = it.limits_for(prod)
        rows = []
        for ln in lines:
            s = store.series(key, reg, prod, start, end, line=ln)
            if len(s) < 3:
                continue
            r = s.resample("8h").mean().dropna()
            cap = capability(s, lim.lsl, lim.usl)
            out = int(((s < lim.lsl).sum() if lim.lsl is not None else 0) + ((s > lim.usl).sum() if lim.usl is not None else 0))
            rows.append({"line": ln or "전체", "label": line_label(ln) if ln else "구분 없음",
                         "pts": [[_ms(t), _num(v, 4)] for t, v in r.items()],
                         "st": {"n": int(len(s)), "last": _num(s.iloc[-1], 4), "last_t": f"{s.index[-1]:%m/%d %H:%M}",
                                "mean": _num(cap["mean"], 4), "sd": _num(cap["std"], 4), "out": out, "cpk": _num(cap["Cpk"], 2)}})
        if not rows:
            continue
        rows.sort(key=lambda r: line_sort_key(r["line"]))
        items.append({"key": key, "name": it.name, "unit": it.unit, "dec": it.decimals, "prod": prod,
                      "lsl": _num(lim.lsl), "usl": _num(lim.usl), "ks_min": _num(lim.ks_min), "ks_max": _num(lim.ks_max),
                      "lines": rows})
    return {"days": days, "items": items}


# ── 강도 예측 ───────────────────────────────────────────────────────────
def _predict(ctx) -> tuple[dict, dict]:
    from . import prediction as P
    store, reg = ctx.store, ctx.registry
    out, pred28 = {}, {}
    prods = P.products_with_strength(store)
    for prod in prods:
        df = P.age_feature_frame(store, prod)
        for age in P.AGES:
            models = P.fit_age_models(store, prod, age, df)
            if not models:
                continue
            p = P.predict_age(store, prod, age, models)
            best = models[0]
            item = reg.get(f"phy_s{age}")
            lim = item.limits_for(prod) if item else None
            last = df.dropna(subset=best.features).tail(1)
            feats = [{"key": f, "label": P.FEATURE_LABELS.get(f, f),
                      "v": _num(float(last[f].iloc[0]) if len(last) else float(df[f].median()), 2)} for f in best.features]
            ser = p.sort_values("timestamp").tail(150)
            due = p[p["status"] == "미도래"].sort_values("timestamp", ascending=False)
            entry = {
                "models": [{"label": m.label, "n": m.n, "r2": _num(m.r2, 2), "rmse": _num(m.rmse, 2)} for m in models[:4]],
                "best": {"label": best.label, "coef": [_num(c, 5) for c in best.coef], "feats": feats, "rmse": _num(best.rmse, 3),
                         "n": best.n, "r2": _num(best.r2, 2)},
                "series": [{"t": _ms(r.timestamp), "a": _num(r.actual, 2), "p": _num(r.pred, 2) if r.status == "미도래" else None}
                           for r in ser.itertuples()],
                "due": [{"t": f"{r.timestamp:%Y-%m-%d}", "p": _num(r.pred, 1), "lo": _num(r.pred_lo, 1), "hi": _num(r.pred_hi, 1),
                         "model": r.model} for r in due.itertuples() if np.isfinite(r.pred)],
                "ks": _num(lim.ks_min) if lim else None, "lsl": _num(lim.lsl) if lim else None,
            }
            out[f"{prod}|{age}"] = entry
            if age == 28:
                pred28[prod] = entry
    return {"products": prods, "ages": list(P.AGES), "data": out}, pred28


# ── 원인 진단 ───────────────────────────────────────────────────────────
def _dx_payload(dx) -> dict:
    q = dx.quant
    return {"title": dx.phenomenon.title, "impact": dx.phenomenon.impact, "quant": q.get("text", ""), "summary": dx.summary,
            "registered": bool(dx.registered),
            "hyp": [[r.hyp.axis, r.hyp.title, r.evidence_score, r.verdict] for r in dx.results[:6]],
            "verify": [f"[{r.hyp.axis}] " + " / ".join(r.hyp.verify) for r in dx.results[:4] if r.hyp.verify],
            "short": [a for a, _ in dx.short_term[:4]], "root": [a for a, _ in dx.root_cause[:4]],
            "ks": [{"item": k.get("항목"), "prod": k.get("품종"), "ks": k.get("KS 판정"), "plant": k.get("사내기준 판정")}
                   for k in dx.ks_eval[:5]]}


def _diagnosis(ctx, end, days=90) -> dict:
    from .diagnosis import diagnose
    store, reg = ctx.store, ctx.registry
    pool = [e for e in ctx.events if e.end >= end - pd.Timedelta(days=days)]
    cats, events = [], []
    for c in EVENT_CATEGORIES:
        evs = [e for e in pool if event_category(e) == c]
        if not evs:
            continue
        evs.sort(key=lambda e: (SEVERITY_ORDER[e.severity], e.end), reverse=True)
        cats.append({"name": c, "n": len(evs)})
        seen = set()
        for i, e in enumerate(evs[:LIST_PER_CATEGORY]):
            rec = {"id": e.event_id, "cat": c, "sev": e.severity, "item": e.item_name, "prod": e.product or "",
                   "desc": e.rule_desc, "end": f"{e.end:%Y-%m-%d}", "worst": _num(e.worst_value, e.decimals + 1), "unit": e.unit}
            k = (e.item_key, e.product, e.line)
            if len(seen) < DX_PER_CATEGORY and k not in seen:      # 같은 항목은 가장 최근·심각한 1건만 상세 진단
                seen.add(k)
                try:
                    rec["dx"] = _dx_payload(diagnose(e, store, reg, ctx.settings))
                except Exception:  # noqa: BLE001 - 진단 1건 실패가 현황판 전체를 막지 않게
                    pass
            events.append(rec)
    return {"days": days, "cats": cats, "events": events}


# ── 출하시멘트 ──────────────────────────────────────────────────────────
def _shipment() -> dict:
    from . import shipment as S
    df = S.load_shipment()
    std = S.load_ship_standards()
    out = {}
    if df.empty:
        return {"products": out}
    for prod in S.PRODUCTS:
        d = S.apply_filters(df, product=prod).sort_values("date").tail(30)
        if d.empty:
            continue
        rows, lot_ok = [], np.ones(len(d), bool)
        for k in SHIP_KEYS:
            if k not in d or d[k].notna().sum() == 0:
                continue
            it = S.BY_KEY[k]
            v = d[k].astype(float)
            lims = [S.effective_limits(std, k, int(t.year), prod) for t in d["date"]]
            ks_min = [lm.get("ks_min") for lm in lims]
            ks_max = [lm.get("ks_max") for lm in lims]
            bad = np.array([(mn is not None and pd.notna(x) and x < mn) or (mx is not None and pd.notna(x) and x > mx)
                            for x, mn, mx in zip(v, ks_min, ks_max)])
            lot_ok &= ~bad
            kmin, kmax = ks_min[-1], ks_max[-1]
            ks_txt = f"≥ {kmin:g}" if kmin is not None else (f"≤ {kmax:g}" if kmax is not None else "기준 미입력")
            rows.append({"name": it.name, "unit": it.unit, "dec": it.dec, "n": int(v.notna().sum()),
                         "mean": _num(v.mean(), it.dec + 1), "min": _num(v.min(), it.dec), "max": _num(v.max(), it.dec),
                         "ks": ks_txt, "judge": ("기준 없음" if kmin is None and kmax is None else ("부적합" if bad.any() else "적합")),
                         "n_bad": int(bad.sum())})
        recent = [{"d": f"{r.date:%Y-%m-%d}", **{k: _num(getattr(r, k, None), 1) for k in ("s3", "s7", "s28")},
                   "ok": bool(ok)} for r, ok in zip(d.iloc[::-1].head(10).itertuples(), lot_ok[::-1][:10])]
        out[prod] = {"n": int(len(d)), "pass": int(lot_ok.sum()), "rows": rows, "recent": recent,
                     "ks_set": prod not in S.KS_NOT_SET, "first": f"{d['date'].min():%Y-%m-%d}", "last": f"{d['date'].max():%Y-%m-%d}"}
    return {"products": out}


# ── 데이터 현황 ─────────────────────────────────────────────────────────
def _status(ctx) -> list[dict]:
    from . import incoming as INC
    from . import shipment as S
    from .standards import TABLES
    rows = []
    for name, meta in TABLES.items():
        df = ctx.store.tables.get(name, pd.DataFrame())
        rows.append({"name": meta["label"], "rows": int(len(df)),
                     "lines": ", ".join(ctx.store.lines(name)[:8]) + (" …" if len(ctx.store.lines(name)) > 8 else ""),
                     "first": f"{df['timestamp'].min():%Y-%m-%d}" if len(df) else "", "last": f"{df['timestamp'].max():%Y-%m-%d}" if len(df) else ""})
    sh = S.load_shipment()
    rows.append({"name": "출하시멘트", "rows": int(len(sh)), "lines": ", ".join(sorted(sh["product"].dropna().unique())) if len(sh) else "",
                 "first": f"{sh['date'].min():%Y-%m-%d}" if len(sh) else "", "last": f"{sh['date'].max():%Y-%m-%d}" if len(sh) else ""})
    inc = INC.load_incoming()
    rows.append({"name": "인수검사", "rows": int(len(inc)), "lines": ", ".join(sorted(inc["검사종류"].dropna().unique())) if len(inc) else "",
                 "first": f"{pd.to_datetime(inc['채취일']).min():%Y-%m-%d}" if len(inc) else "",
                 "last": f"{pd.to_datetime(inc['채취일']).max():%Y-%m-%d}" if len(inc) else ""})
    return rows


def build_payload(ctx=None) -> dict:
    from .snapshot import load_context
    ctx = ctx or load_context()
    end = _ref_end(ctx.store)
    pred, pred28 = _predict(ctx)
    ship = _shipment()
    p = ctx.store.period()
    return {
        "meta": {"generated": f"{datetime.now():%Y-%m-%d %H:%M}", "ref": f"{end:%Y-%m-%d}",
                 "period": [f"{p[0]:%Y-%m-%d}", f"{p[1]:%Y-%m-%d}"] if p else None, "demo": bool(ctx.demo)},
        "overview": _overview(ctx, end, pred28, ship),
        "monitor": _monitor(ctx, end),
        "predict": pred,
        "diagnosis": _diagnosis(ctx, end),
        "shipment": ship,
        "status": _status(ctx),
    }


def build_viewer(ctx=None) -> str:
    """보는용 현황판 HTML(한 파일)."""
    data = json.dumps(build_payload(ctx), ensure_ascii=False, separators=(",", ":"), default=str)
    data = data.replace("</", "<\\/")                      # 값 안의 '</script>' 가 문서를 끊지 않게
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data, 1)
