"""품위 수지 검증 [Matching-Agent] — 물량뿐 아니라 CaO·MgO 성분량까지 닫히는지 본다.

물량 수지(적재−인출=재고증감)만으로는 **매칭이 맞는지** 알 수 없다. 같은 물량이라도
엉뚱한 품위를 붙였다면 물량 수지는 그대로 통과한다. 그래서 성분량까지 함께 닫는다.

    유입 성분량 = Σ(적재톤 × 적재품위)
    유출 성분량 = Σ(인출톤 × 인출에 부여한 품위)
    기말 함의 품위 = (기초 성분량 + 유입 − 유출) ÷ 기말 재고톤

기말 함의 품위가 석회석의 물리적 범위를 벗어나면 어딘가 틀린 것이다.

⭐️ 두 가지 함정을 피한다.
  1) **물량 결손을 먼저 닫는다.** 물량이 안 맞으면 품위 수지는 그 오차를 그대로 물려받아
     음수 품위 같은 헛된 결론이 나온다. 결손을 '미기록 물량'으로 보고 양방향 보정한 뒤 판정한다.
  2) **민감도(지렛대)를 함께 보고한다.** 기말재고가 처리량보다 훨씬 작으면 작은 물량 오차가
     함의 품위를 크게 흔든다. 지렛대가 크면 이 검사는 무딘 도구이므로 그 사실을 밝힌다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S
from src.matching.pipeline import GRADE_COLS

#: 석회석의 물리적으로 가능한 품위 범위 (%) — 이 밖이면 수지가 깨진 것
PLAUSIBLE_GRADE = {"cao": (38.0, 52.0), "mgo": (0.0, 12.0)}


def _wmean(v: pd.Series, w: pd.Series) -> float:
    m = v.notna() & w.notna() & (w > 0)
    if not m.any() or w[m].sum() <= 0:
        return float("nan")
    return float(np.average(v[m], weights=w[m]))


def _wstd(v: pd.Series, w: pd.Series) -> float:
    m = v.notna() & w.notna() & (w > 0)
    if m.sum() < 2 or w[m].sum() <= 0:
        return float("nan")
    mu = np.average(v[m], weights=w[m])
    return float(np.sqrt(np.average((v[m] - mu) ** 2, weights=w[m])))


def _common_window(stock, mine, osp, line):
    """세 소스가 모두 존재하는 겹치는 기간만 잘라낸다 (기간 불일치로 인한 허위 격차 방지)."""
    g = stock[stock["line"] == line].dropna(subset=["stock_ton"]).sort_values("datetime")
    m = mine[mine["line"] == line].dropna(subset=["datetime"])
    o = osp[osp["line"] == line].dropna(subset=["datetime"])
    if not len(g) or not len(m) or not len(o):
        return None
    lo = max(g["datetime"].min(), m["datetime"].min(), o["datetime"].min())
    hi = min(g["datetime"].max(), m["datetime"].max(), o["datetime"].max())
    if pd.isna(lo) or pd.isna(hi) or lo >= hi:
        return None
    gg = g[(g["datetime"] >= lo) & (g["datetime"] <= hi)]
    if len(gg) < 2:
        return None
    return (gg,
            m[(m["datetime"] > lo) & (m["datetime"] <= hi)],
            o[(o["datetime"] > lo) & (o["datetime"] <= hi)], lo, hi)


def grade_balance(stock, mine, osp_exp, line: str) -> dict | None:
    """한 라인의 물량·품위 수지를 함께 계산한다.

    반환 dict:
      period/s0/s1/loaded/withdrawn — 기간과 물량
      mass_gap   : 적재−인출−재고증감. >0 이면 적재 초과(=인출 미기록), <0 이면 그 반대
      leverage   : 처리량÷기말재고. 클수록 함의 품위 검사가 물량 오차에 민감
      grades[c]  : 성분별 {in_grade, out_grade, delta, end_grade, ok, spread_kept, coverage}
    """
    w = _common_window(stock, mine, osp_exp, line)
    if w is None:
        return None
    gg, mm, oo, lo, hi = w
    s0, s1 = float(gg["stock_ton"].iloc[0]), float(gg["stock_ton"].iloc[-1])
    loaded = float(pd.to_numeric(mm["tonnage"], errors="coerce").sum())
    withdrawn = float(pd.to_numeric(oo["withdrawn_ton"], errors="coerce").sum())
    if loaded <= 0 or withdrawn <= 0 or s1 <= 0:
        return None
    mass_gap = loaded - withdrawn - (s1 - s0)
    # 결손을 '미기록 물량'으로 양방향 보정 — 부족한 쪽에 더한다
    loaded_adj = loaded + max(-mass_gap, 0.0)
    withdrawn_adj = withdrawn + max(mass_gap, 0.0)

    grades: dict[str, dict] = {}
    for comp, (r0, r1) in PLAUSIBLE_GRADE.items():
        ec = GRADE_COLS.get(comp)
        if comp not in mm.columns or ec not in oo.columns:
            continue
        in_g = _wmean(mm[comp], mm["tonnage"])
        out_g = _wmean(oo[ec], oo["withdrawn_ton"])
        if not np.isfinite(in_g) or not np.isfinite(out_g):
            continue
        end_g = (s0 * in_g + loaded_adj * in_g - withdrawn_adj * out_g) / s1
        sd_in, sd_out = _wstd(mm[comp], mm["tonnage"]), _wstd(oo[ec], oo["withdrawn_ton"])
        cov_ton = float(pd.to_numeric(
            oo.loc[oo[ec].notna(), "withdrawn_ton"], errors="coerce").sum())
        grades[comp] = dict(
            in_grade=in_g, out_grade=out_g, delta=out_g - in_g,
            end_grade=end_g, ok=bool(r0 <= end_g <= r1),
            spread_kept=(sd_out / sd_in) if (np.isfinite(sd_in) and sd_in > 0) else float("nan"),
            coverage=cov_ton / withdrawn if withdrawn > 0 else float("nan"),
        )
    if not grades:
        return None
    return dict(line=line, start=lo, end=hi, s0=s0, s1=s1,
                loaded=loaded, withdrawn=withdrawn, mass_gap=mass_gap,
                leverage=loaded / s1, grades=grades)


def combined_mass_gap(stock, mine, osp_exp) -> dict | None:
    """라인 귀속을 지운 **합산** 물량 수지.

    '교차인출' 때문에 라인별 결손이 생겼다는 설명이 맞다면, 두 라인을 합쳤을 때
    결손은 사라져야 한다. 합쳐도 남는다면 원인은 라인 귀속이 아니라 계량 자체다.
    """
    s0 = s1 = loaded = withdrawn = 0.0
    n = 0
    for ln in S.YARD_PAIR:
        w = _common_window(stock, mine, osp_exp, ln)
        if w is None:
            continue
        gg, mm, oo, _, _ = w
        s0 += float(gg["stock_ton"].iloc[0]); s1 += float(gg["stock_ton"].iloc[-1])
        loaded += float(pd.to_numeric(mm["tonnage"], errors="coerce").sum())
        withdrawn += float(pd.to_numeric(oo["withdrawn_ton"], errors="coerce").sum())
        n += 1
    if n < 2 or loaded <= 0:
        return None
    gap = loaded - withdrawn - (s1 - s0)
    return dict(n_lines=n, loaded=loaded, withdrawn=withdrawn, stock_delta=s1 - s0,
                gap=gap, gap_pct=abs(gap) / loaded * 100, beta=withdrawn / loaded)


def component_coherence(mine, osp_exp, line: str) -> dict | None:
    """CaO~MgO 상관이 매칭 후에도 보존되는가.

    인출에 부여되는 값은 '구역-일별 평균'이므로 기준선도 같은 단위로 잡아야 한다
    (원본 행 단위 상관과 비교하면 집계에 의한 감쇠를 매칭 오류로 오인한다).
    """
    m = mine[mine["line"] == line].dropna(subset=["zone", "cao", "mgo", "date"])
    o = osp_exp[osp_exp["line"] == line]
    if len(m) < 3 or "expected_mgo" not in o.columns or o["expected_mgo"].notna().sum() < 3:
        return None
    zd = m.groupby(["zone", "date"], as_index=False)[["cao", "mgo"]].mean()
    ref = float(zd["cao"].corr(zd["mgo"])) if len(zd) >= 3 else float("nan")
    got = float(o["expected_cao"].corr(o["expected_mgo"]))
    return dict(line=line, raw=float(m["cao"].corr(m["mgo"])), ref=ref, assigned=got,
                drift=got - ref)
