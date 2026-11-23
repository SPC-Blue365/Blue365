"""3D 공정 지도 자료 [Synthesis-Agent] — 광산 → 크러셔·수항 → OSP → 야드, 장치별 **실측 집계**.

⭐️ 원칙 (§2-1 가상 데이터 금지)
  · 레퍼런스(시멘트 공정 지도)는 '가상 데이터' 로 움직이는 화면이다. 이 지도는 **그렇게 하지 않는다.**
    화면에 보이는 숫자·색·벨트 위 물량 입자는 전부 이 파일이 원본에서 계산한 값이다.
  · '최근 7일' 은 지금 시계가 아니라 **자료의 마지막 시각**에서 거꾸로 센다 — 자료가 늦게 들어와도
    빈 화면이 되지 않고, 어느 기간인지 화면에 함께 적힌다.
  · 측정하지 않는 것은 측정한 척하지 않는다: 수항 재고는 '열린 사이클의 채움 합(하한)', 구역 재고는
    '흐름에서 복원한 추정', 크러셔별 물량은 교대 단위 기록이라 **나누지 않고** 교대 수만 센다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S
from src.matching import pipeline as MP
from src.matching.chain import build_chain
from src.matching.inventory import zone_inventory
from src.models.dataset import (load_osp_stock, load_sources, load_yard_change,
                                surge_cycles, surge_events)
from src.visualization import dashboard_data as D

TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol


def _f(v, nd=2):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(v) else round(v, nd)


def _ts(t, fmt="%m-%d %H:%M"):
    return None if t is None or pd.isna(t) else pd.Timestamp(t).strftime(fmt)


def _wmean(df, col, w="tonnage"):
    d = df.dropna(subset=[col])
    d = d[pd.to_numeric(d[w], errors="coerce") > 0]
    if not len(d):
        return None
    return _f(np.average(d[col], weights=d[w]))


def _daily_grade(df, tcol, ccol, wcol, days, end):
    """하루 단위 물량 가중 CaO — 스파크라인용 [{d, v}]."""
    x = df[(df[tcol] > end - pd.Timedelta(days=days))].dropna(subset=[ccol]).copy()
    x = x[pd.to_numeric(x[wcol], errors="coerce") > 0]
    if not len(x):
        return []
    x["d"] = x[tcol].dt.floor("D")
    g = x.groupby("d").apply(lambda q: np.average(q[ccol], weights=q[wcol]), include_groups=False)
    return [dict(d=k.strftime("%Y-%m-%d"), v=_f(v)) for k, v in g.items()]


def _status_cao(v):
    """야드·구역 품위 상태: 규격(±tol) 안 = ok · 2배 안 = warn · 그 밖 = bad."""
    if v is None:
        return "none"
    dev = abs(v - TARGET)
    return "ok" if dev <= TOL else "warn" if dev <= 2 * TOL else "bad"


def build_payload() -> dict:
    mine, osp, yards = load_sources(verbose=False)
    stock = load_osp_stock()
    yc = load_yard_change()

    ends = [y["datetime"].max() for y in yards.values() if len(y)]
    ends += [mine["datetime"].max(), osp["datetime"].max()]
    end = max(t for t in ends if pd.notna(t))
    w7 = end - pd.Timedelta(days=7)

    # ── 광산 (원본 시트 = 출처 광구) ─────────────────────────────────
    quarries = {}
    for src, q in mine.dropna(subset=["datetime"]).groupby("source"):
        r7 = q[q["datetime"] > w7]
        quarries[src] = dict(
            id=src, ton7=_f(r7["tonnage"].sum(), 0), cao7=_wmean(r7, "cao"), mgo7=_wmean(r7, "mgo"),
            lines={ln: _f(r7.loc[r7["line"] == ln, "tonnage"].sum(), 0) for ln in S.YARD_PAIR},
            last=_ts(q["datetime"].max()), n7=int(len(r7)),
            daily=_daily_grade(q, "datetime", "cao", "tonnage", 45, end))

    # ── 크러셔 — 교대 단위 기록이라 물량을 나누지 않고 '교대 수' 만 센다 ─────
    m7 = mine[mine["datetime"] > w7]
    lab = m7["crusher"].astype(str).str.replace(" ", "")
    crushers = dict(
        gc_only=int((lab == "G/C").sum()), hc_only=int((lab == "H/C").sum()),
        both=int((lab.str.contains("G/C") & lab.str.contains("H/C")).sum()))

    # ── 수항(사일로) — 재고는 측정하지 않는다: 열린 사이클의 '채움 합' 은 재고의 하한 ──
    cyc = surge_cycles()
    ev = surge_events()
    last_cyc = None
    if len(cyc):
        c = cyc.iloc[-1]
        last_cyc = dict(start=_ts(c["start"]), end=_ts(c["end"]), fill=_f(c["fill_ton"], 0),
                        peak=_f(c["peak_ton"], 0), ok=bool(c["plausible"]),
                        reason=str(c.get("reason", "") or ""))
    open_fill, open_n, last_empty = 0.0, 0, None
    if len(ev):
        emp = ev[ev["kind"] == "고갈"]
        last_empty = emp["datetime"].max() if len(emp) else None
        f = ev[(ev["kind"] == "채움") & ((ev["datetime"] > last_empty) if last_empty is not None else True)]
        open_fill, open_n = float(f["ton"].fillna(0).sum()), int(len(f))
    surge = dict(cap=S.SURGE_BIN_CAPACITY_TON, last_cycle=last_cyc, open_fill=_f(open_fill, 0),
                 open_n=open_n, last_empty=_ts(last_empty))

    # ── OSP (출처 기준 — 재고에서 빠진 것은 L-Slag 포함 전부) ─────────────
    invs = {ln: zone_inventory(mine, osp, stock, ln) for ln in S.YARD_PAIR}
    zones = D.zone_stock(invs)
    stk = D.stock_daily(stock)
    ospd = {}
    for ln in S.YARD_PAIR:
        s = stk.get(ln) or []
        cur = s[-1] if s else {}
        prev = [r for r in s if r["d"] <= (pd.Timestamp(cur.get("d", end)) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")]
        o = osp[osp["line"] == ln]
        o7 = o[o["datetime"] > w7]
        last_w = o["datetime"].max() if len(o) else None
        z = zones.get(ln, {})
        zl = [dict(z=int(x["z"]), t=_f(x["t"], 0), cao=_f(x.get("cao")),
                   st=_status_cao(_f(x.get("cao")))) for x in z.get("zones", [])]
        ospd[ln] = dict(
            stock=_f(cur.get("t"), 0), stock_at=cur.get("d"), cap=S.OSP_CAPACITY_TON,
            pct=_f((cur.get("t") or 0) / S.OSP_CAPACITY_TON * 100, 0) if cur else None,
            chg7=_f((cur.get("t") or 0) - prev[-1]["t"], 0) if prev and cur else None,
            in7=_f(mine.loc[(mine["line"] == ln) & (mine["datetime"] > w7), "tonnage"].sum(), 0),
            out7=_f(o7["withdrawn_ton"].sum(), 0), last_out=_ts(last_w),
            pw_active=bool(last_w is not None and last_w > end - pd.Timedelta(hours=24)),
            zone_total=_f(z.get("total"), 0), zone_at=z.get("at"), zones=zl,
            stock_daily=[dict(d=r["d"], v=r["t"]) for r in s[-60:]])

    # ── 경로(벨트) — 최근 7일 물량 · 운반 시간(현장 확정/데이터 추정) ─────────
    routes = []
    for dest in S.YARD_PAIR:
        rl = MP.estimate_route_lags(osp, yards[dest], dest)
        d = MP.osp_to_yard(osp, dest)
        for src in rl.lags:
            part = d[d["line"] == src]
            routes.append(dict(src=src, dest=dest, lag=int(rl.lags[src]), field=src in rl.field,
                               corr=_f(rl.corr.get(src)), ton7=_f(part.loc[part["datetime"] > w7, "withdrawn_ton"].sum(), 0),
                               ton=_f(part["withdrawn_ton"].sum(), 0)))
    ns = osp[osp.get("dest_line", osp["line"]) == S.DEST_NONYARD] if "dest_line" in osp.columns else osp.iloc[0:0]
    lslag = dict(name=S.DEST_NONYARD, ton=_f(ns["withdrawn_ton"].sum(), 0),
                 ton7=_f(ns.loc[ns["datetime"] > w7, "withdrawn_ton"].sum(), 0),
                 n=int(ns["row_ton"].notna().sum()) if "row_ton" in ns.columns else int(len(ns)),
                 first=_ts(ns["datetime"].min(), "%Y-%m-%d") if len(ns) else None,
                 last=_ts(ns["datetime"].max()) if len(ns) else None)

    # ── 야드 (분석기 실측) ────────────────────────────────────────────
    head = D.headline(yards, stock)
    yd = D.yard_daily(yards)
    yardd = {}
    for ln, (_, alias) in S.YARD_PAIR.items():
        h = head.get(ln, {})
        yardd[ln] = dict(alias=alias, analyzer=("45Q 감마레이" if ln == S.LINE_OLD else "CNA"),
                         last_cao=_f(h.get("last_cao")), last_at=h.get("last_at"),
                         w_mean=_f(h.get("w_mean")), w_std=_f(h.get("w_std")), w_ok=_f(h.get("w_ok"), 0),
                         age_h=_f(h.get("age_h"), 1), st=_status_cao(_f(h.get("last_cao"))),
                         daily=[dict(d=r["d"], v=_f(r.get("cao")), ok=_f(r.get("ok"), 0)) for r in (yd.get(ln) or [])[-45:]])

    chain = build_chain(mine, osp, stock, yc)
    return dict(
        target=TARGET, tol=TOL, built=S.now_local().strftime("%Y-%m-%d %H:%M"),
        data_end=_ts(end, "%Y-%m-%d %H:%M"), win_from=_ts(w7, "%m-%d %H:%M"),
        lines=list(S.YARD_PAIR), quarries=quarries, crushers=crushers, surge=surge,
        osp=ospd, routes=routes, lslag=lslag, yards=yardd, cross=D.cross_flow(osp),
        chain=dict(pct=_f(chain.linked_pct, 1), ton=_f(chain.linked_ton, 0), total=_f(chain.total_ton, 0),
                   weakest=(chain.weakest.key if chain.weakest else None),
                   joints=[dict(key=j.key, name=j.name, label=j.label, tone=j.tone, why=j.why, gap=j.gap)
                           for j in chain.joints]),
        recent=D.recent_records(osp, mine, limit=80))
