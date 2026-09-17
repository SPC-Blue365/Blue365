"""대시보드용 집계 [Synthesis-Agent].

`make_dashboard.py` 가 화면에 뿌릴 값을 **한곳에서** 만든다. 화면 코드와 집계 코드를 섞지 않으면
숫자의 출처를 따라가기 쉽고(§2-3), 같은 집계를 다른 산출물에서도 재사용할 수 있다.

⭐️ 설계 원칙 — **브라우저로 넘기는 것은 '이미 집계된 값'뿐이다.**
   야드 원시 측정이 51,000행이라 그대로 실으면 파일이 수 MB가 된다. 일별·시간별로 미리 줄여
   보내면 수십 KB 로 끝나고, 기간 필터도 브라우저에서 즉시 돈다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S

TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol

#: 대시보드 기본 관찰 창(일). 상단 버튼으로 바꿀 수 있다.
DEFAULT_WINDOW_DAYS = 30


def _note(v) -> str:
    """비고 정리 — NaN 은 truthy 라 `or ""` 로는 걸러지지 않는다(화면에 'nan' 이 찍혔다)."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s[:40]


def _f(v) -> float | None:
    """JSON 으로 나갈 수 있게 NaN·inf 를 None 으로 바꾼다."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def yard_daily(yards: dict) -> dict:
    """라인별 **일별** 야드 품위 — 평균·최소·최대·규격내 비율·측정 건수."""
    out = {}
    for ln, y in yards.items():
        d = y.dropna(subset=["cao", "datetime"]).copy()
        if not len(d):
            continue
        d["day"] = d["datetime"].dt.floor("D")
        d["ok"] = (d["cao"] >= TARGET - TOL) & (d["cao"] <= TARGET + TOL)
        g = d.groupby("day").agg(
            cao=("cao", "mean"), lo=("cao", "min"), hi=("cao", "max"),
            mgo=("mgo", "mean"), ok=("ok", "mean"), n=("cao", "size"))
        out[ln] = [dict(d=k.strftime("%Y-%m-%d"), cao=_f(r.cao), lo=_f(r.lo), hi=_f(r.hi),
                        mgo=_f(r.mgo), ok=_f(r.ok * 100), n=int(r.n))
                   for k, r in g.iterrows()]
    return out


def yard_hist(yards: dict, lo: float = 39.0, hi: float = 51.0, step: float = 0.25) -> dict:
    """라인별 품위 분포 — 규격 폭을 눈으로 보기 위한 히스토그램(비율 %)."""
    edges = np.arange(lo, hi + 1e-9, step)
    out = {"edges": [round(float(e), 3) for e in edges], "lines": {}}
    for ln, y in yards.items():
        d = y.dropna(subset=["cao"])
        if not len(d):
            continue
        cnt, _ = np.histogram(d["cao"], bins=edges)
        tot = max(cnt.sum(), 1)
        out["lines"][ln] = [round(float(c) / tot * 100, 3) for c in cnt]
    return out


def stock_daily(stock: pd.DataFrame) -> dict:
    """라인별 **일별 마지막 실사 재고** — 재고 추이와 현재 수위."""
    out = {}
    for ln in S.YARD_PAIR:
        g = stock[stock["line"] == ln].dropna(subset=["stock_ton"]).sort_values("datetime")
        if not len(g):
            continue
        g = g.assign(day=g["datetime"].dt.floor("D")).groupby("day")["stock_ton"].last()
        out[ln] = [dict(d=k.strftime("%Y-%m-%d"), t=_f(v)) for k, v in g.items()]
    return out


def flow_daily(mine: pd.DataFrame, osp: pd.DataFrame) -> dict:
    """라인별 **일별 적재·인출 톤** — 재고가 왜 늘고 줄었는지."""
    out = {}
    for ln in S.YARD_PAIR:
        m = mine[mine["line"] == ln].dropna(subset=["datetime"])
        o = osp[osp["line"] == ln].dropna(subset=["datetime"])
        mi = (m.assign(day=m["datetime"].dt.floor("D")).groupby("day")["tonnage"].sum()
              if len(m) else pd.Series(dtype=float))
        oo = (o.assign(day=o["datetime"].dt.floor("D")).groupby("day")["withdrawn_ton"].sum()
              if len(o) else pd.Series(dtype=float))
        days = sorted(set(mi.index) | set(oo.index))
        out[ln] = [dict(d=k.strftime("%Y-%m-%d"), i=_f(mi.get(k, 0.0)), o=_f(oo.get(k, 0.0)))
                   for k in days]
    return out


def zone_stock(inv_by_line: dict) -> dict:
    """구역별 재고 추정치 + 그 구역의 현재 품위 — '어디에 무엇이 있나'."""
    out = {}
    for ln, inv in inv_by_line.items():
        if inv is None:
            continue
        d = inv.zones.sort_values("zone")
        out[ln] = dict(
            total=_f(inv.line_total), at=inv.at.strftime("%Y-%m-%d %H:%M"),
            notes=list(inv.notes),
            zones=[dict(z=int(r.zone), t=_f(r.ton), cao=_f(r.cao), mgo=_f(r.mgo),
                        n=int(r.n_loads),
                        last=(r.last_load.strftime("%m-%d") if pd.notna(r.last_load) else None))
                   for r in d.itertuples() if _f(r.ton) and r.ton > 0])
    return out


def cross_flow(raw_file_frames: dict) -> dict:
    """⭐️ 교차인출 현황 — **기존 OSP 에서 뽑아 신설 라인으로 보낸 물량**.

    2026-09-17 갱신본에서 현장이 `공정구분` 을 목적지 라인으로 명시하기 시작했다.
    기존 시트의 절반이 넘는 물량이 여기 해당하고 최근에는 대부분이므로, 재고·품질을
    읽을 때 **반드시 함께 봐야 하는 지표**다(§6-0-20).

    입력: {시트라인: 원본 DataFrame}
    """
    out = {}
    for ln, d in raw_file_frames.items():
        if d is None or not len(d) or "공정구분" not in d.columns:
            continue
        x = d.copy()
        x["일자"] = pd.to_datetime(x["일자"], errors="coerce")
        x["ton"] = pd.to_numeric(x["인출량"], errors="coerce")
        x = x.dropna(subset=["일자"])
        other = S.LINE_NEW if ln == S.LINE_OLD else S.LINE_OLD
        x["cross"] = x["공정구분"].astype(str).str.strip() == other
        g = x.assign(day=x["일자"].dt.floor("D")).groupby("day").agg(
            tot=("ton", "sum"), cr=("ton", lambda s: s[x.loc[s.index, "cross"]].sum()))
        tot = float(x["ton"].sum())
        cr = float(x.loc[x["cross"], "ton"].sum())
        out[ln] = dict(
            dest=other, total=_f(tot), cross=_f(cr),
            pct=_f(cr / tot * 100 if tot else np.nan),
            n_rows=int(x["cross"].sum()),
            daily=[dict(d=k.strftime("%Y-%m-%d"), t=_f(r.tot), c=_f(r.cr))
                   for k, r in g.iterrows()])
    return out


def recent_records(osp: pd.DataFrame, mine: pd.DataFrame, limit: int = 300) -> list:
    """최근 기록 표 — 화면에서 검색·정렬할 수 있게 납작한 행으로 만든다."""
    rows = []
    o = osp.dropna(subset=["datetime"]).sort_values("datetime", ascending=False).head(limit)
    for r in o.itertuples():
        rows.append(dict(t=r.datetime.strftime("%m-%d %H:%M"), kind="인출", line=r.line,
                         zone=(int(r.zone) if pd.notna(r.zone) else None),
                         ton=_f(r.withdrawn_ton),
                         cao=_f(getattr(r, "expected_cao", np.nan)),
                         note=_note(getattr(r, "note", None))))
    m = mine.dropna(subset=["datetime"]).sort_values("datetime", ascending=False).head(limit)
    for r in m.itertuples():
        rows.append(dict(t=r.datetime.strftime("%m-%d %H:%M"), kind="적재", line=r.line,
                         zone=(int(r.zone) if pd.notna(r.zone) else None),
                         ton=_f(r.tonnage), cao=_f(r.cao),
                         note=_note(getattr(r, "note", None))))
    rows.sort(key=lambda x: x["t"], reverse=True)
    return rows[:limit]


def headline(yards: dict, stock: pd.DataFrame, window_days: int = 7) -> dict:
    """상단 요약 — 라인별 '지금' 상태."""
    out = {}
    for ln in S.YARD_PAIR:
        y = yards.get(ln)
        card = dict(line=ln, alias=S.YARD_PAIR[ln][1])
        if y is not None and len(y.dropna(subset=["cao"])):
            d = y.dropna(subset=["cao"]).sort_values("datetime")
            hi = d["datetime"].max()
            w = d[d["datetime"] >= hi - pd.Timedelta(days=window_days)]
            ok = ((w["cao"] >= TARGET - TOL) & (w["cao"] <= TARGET + TOL)).mean() * 100
            card.update(last_cao=_f(d["cao"].iloc[-1]), last_at=hi.strftime("%m-%d %H:%M"),
                        age_h=_f((pd.Timestamp.now() - hi).total_seconds() / 3600),
                        w_mean=_f(w["cao"].mean()), w_std=_f(w["cao"].std()), w_ok=_f(ok),
                        w_n=int(len(w)))
        g = stock[stock["line"] == ln].dropna(subset=["stock_ton"]).sort_values("datetime")
        if len(g):
            cur = float(g["stock_ton"].iloc[-1])
            prev = g[g["datetime"] <= g["datetime"].max() - pd.Timedelta(days=7)]
            card.update(stock=_f(cur), stock_at=g["datetime"].iloc[-1].strftime("%m-%d"),
                        stock_pct=_f(cur / S.OSP_CAPACITY_TON * 100),
                        stock_chg=_f(cur - float(prev["stock_ton"].iloc[-1]) if len(prev) else np.nan))
        out[ln] = card
    return out
