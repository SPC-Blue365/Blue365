"""배합 처방 [ML-Engineer] — "어느 구역에서 몇 톤을, 몇 시간 동안 뽑으면 기준에 드는가".

이 모듈이 프로젝트의 **최종 산출 형태**다. 앞선 추적·매칭·검증은 전부 이 답을 만들기 위한 것이다.

    입력: 라인, 앞으로 몇 시간, (선택) 인출 속도
    출력: 구역별 인출톤 · 예상 CaO/MgO · **규격 적중 확률** · 달성 불가 시 병목

⭐️ **확률까지 함께 내는 것이 이 모듈의 핵심**이다. 배합 계산 자체는 선형계획으로 쉽게 풀리지만,
   들어가는 구역 품위가 부정확하면 "계산상 44.6%" 는 아무 의미가 없다. 그래서 구역 품위의
   불확실성을 배합 비중으로 전파해 **이 처방이 규격 안에 들 확률**을 함께 보고한다(§2-1).

달성 불가 시 억지 답을 만들지 않는다 — 가장 근접한 배합 + 경고 + 병목을 낸다(CLAUDE.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import schema as S
from src.matching.inventory import ZoneInventory, withdrawal_rate, zone_inventory
from src.optimization.blend import BlendSource, recommend_blend

#: 구역 품위 추정의 기본 불확실성(%p). 실제 구역별 산포에서 계산하되, 표본이 없을 때의 하한.
MIN_ZONE_SE = 0.2


@dataclass
class Prescription:
    line: str
    at: pd.Timestamp
    hours: float
    rate_tph: float
    demand_ton: float
    allocation: pd.DataFrame          # zone, ton, share, cao, mgo, se
    achieved_cao: float
    achieved_mgo: float
    blend_se: float                   # 배합 품위의 표준오차(%p)
    p_in_spec: float                  # 규격(target±tol) 적중 확률
    feasible: bool
    reliable: bool                    # 처방을 실제 운전에 쓸 수 있는 수준인가
    message: str = ""
    bottleneck: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def sentence(self) -> str:
        """사람이 읽는 한 문장 — 사용자가 원한 바로 그 형식."""
        if self.allocation.empty:
            return "처방할 수 있는 재고가 없습니다."
        parts = " + ".join(f"{int(r.zone)}번에서 {r.ton:,.0f}톤"
                           for r in self.allocation.itertuples() if r.ton >= 1)
        # '톤' 은 받침이 있으므로 조사는 '을'. 앞에 공백을 두면 어색해진다.
        return (f"지금부터 {self.hours:.0f}시간 동안 {parts}을 뽑아 야드로 보내면 "
                f"CaO 약 {self.achieved_cao:.2f}% (MgO {self.achieved_mgo:.2f}%) 가 됩니다.")


def _zone_se(mine: pd.DataFrame, line: str) -> dict[float, float]:
    """구역별 품위의 표준오차 — 같은 구역 안에서도 품위가 흔들리는 정도."""
    m = mine[(mine["line"] == line)].dropna(subset=["zone", "cao"])
    out: dict[float, float] = {}
    for z, g in m.groupby("zone"):
        n = len(g)
        sd = float(g["cao"].std()) if n > 1 else float("nan")
        out[float(z)] = max(sd / np.sqrt(n), MIN_ZONE_SE) if np.isfinite(sd) else float("nan")
    return out


def prescribe(mine: pd.DataFrame, osp_exp: pd.DataFrame, stock: pd.DataFrame, line: str,
              hours: float = 8.0, rate_tph: float | None = None,
              target: float | None = None, tol: float | None = None,
              at: pd.Timestamp | None = None,
              inv: ZoneInventory | None = None) -> Prescription | None:
    """`hours` 시간 동안 어느 구역에서 몇 톤을 뽑을지 처방한다."""
    target = S.TARGET.cao_mean if target is None else target
    tol = S.TARGET.tol if tol is None else tol
    inv = inv if inv is not None else zone_inventory(mine, osp_exp, stock, line, at)
    if inv is None:
        return None
    rate = withdrawal_rate(osp_exp, line) if rate_tph is None else rate_tph
    if not np.isfinite(rate) or rate <= 0:
        return None
    demand = rate * hours

    cand = inv.usable(min_ton=1.0)
    caveats = list(inv.notes)
    if cand.empty:
        return Prescription(line, inv.at, hours, rate, demand, cand, float("nan"), float("nan"),
                            float("nan"), float("nan"), False, False,
                            "품위를 아는 구역 재고가 없습니다", ["구역 품위 미상"], caveats)

    ses = _zone_se(mine, line)
    sources = [BlendSource(name=str(int(r.zone)), grade_cao=float(r.cao),
                           available_ton=float(r.ton)) for r in cand.itertuples()]
    res = recommend_blend(sources, demand_ton=demand, target_cao=target, tol=tol)

    alloc = cand.assign(ton_take=[res.allocation.get(str(int(z)), 0.0) for z in cand["zone"]])
    alloc = alloc[alloc["ton_take"] > 1e-6].copy()
    if alloc.empty or not np.isfinite(res.achieved_cao):
        return Prescription(line, inv.at, hours, rate, demand, alloc, res.achieved_cao,
                            float("nan"), float("nan"), float("nan"), res.feasible, False,
                            res.message or "배합 해를 찾지 못했습니다", res.bottleneck, caveats)

    w = alloc["ton_take"].to_numpy() / demand
    mgo = float(np.nansum(w * alloc["mgo"].to_numpy())) if alloc["mgo"].notna().any() else float("nan")
    se_i = np.array([ses.get(float(z), np.nan) for z in alloc["zone"]], dtype=float)
    se_i = np.where(np.isfinite(se_i), se_i, MIN_ZONE_SE)
    blend_se = float(np.sqrt(np.sum((w * se_i) ** 2)))
    # 규격 적중 확률 — 배합 추정치를 중심으로 한 정규 근사
    if blend_se > 0:
        p = float(norm.cdf((target + tol - res.achieved_cao) / blend_se)
                  - norm.cdf((target - tol - res.achieved_cao) / blend_se))
    else:
        p = 1.0 if abs(res.achieved_cao - target) <= tol else 0.0

    out = alloc.rename(columns={"ton_take": "ton_take"})[
        ["zone", "ton_take", "cao", "mgo", "ton"]].rename(
        columns={"ton_take": "ton", "ton": "available"})
    out["share"] = out["ton"] / demand * 100
    out["se"] = se_i
    out = out.sort_values("ton", ascending=False).reset_index(drop=True)

    return Prescription(line, inv.at, hours, rate, demand, out, res.achieved_cao, mgo,
                        blend_se, p, res.feasible, False, res.message, res.bottleneck, caveats)


def zone_balance_health(mine: pd.DataFrame, osp_exp: pd.DataFrame, line: str) -> dict:
    """구역별 수지가 얼마나 맞는가 — 처방을 믿어도 되는지 판정하는 근거.

    적재 대비 인출이 몇 배인지 본다. 1.0 근처여야 '그 구역에서 뽑았다' 는 기록이 물리와 맞는다.
    크게 벗어나면 **인출 기록의 구역 번호가 적재 위치를 가리키지 않는다**는 뜻이다.
    """
    m = mine[mine["line"] == line].dropna(subset=["zone"])
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["zone"])
    if not len(m) or not len(o):
        return {}
    L = m.groupby("zone")["tonnage"].sum()
    D = o.groupby("zone")["withdrawn_ton"].sum()
    zones = sorted(set(L.index) | set(D.index))
    rows = [dict(zone=float(z), loaded=float(L.get(z, 0.0)), drawn=float(D.get(z, 0.0)))
            for z in zones]
    df = pd.DataFrame(rows)
    df["ratio"] = df["drawn"] / df["loaded"].replace(0, np.nan)
    tot = df["drawn"].sum()
    bad = df[(df["ratio"] > 2) | (df["ratio"] < 0.5) | df["ratio"].isna()]
    return dict(table=df, n_zones=len(df), n_bad=len(bad),
                bad_ton=float(bad["drawn"].sum()),
                bad_share=float(bad["drawn"].sum()) / tot * 100 if tot else float("nan"),
                worst=float(df["ratio"].max(skipna=True)))
