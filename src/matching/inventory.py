"""구역별 OSP 재고 복원 [Matching-Agent].

현장 확인(§6-0-15 Q1): **구역별 재고는 측정하지 않는다.** 라인 합계만 실사로 존재한다.
그런데 "OSP 몇 번 위치에서 몇 톤" 을 처방하려면 구역별 재고가 반드시 필요하다.

없는 값을 지어내지 않으면서(§2-1) 쓸 수 있게 만드는 방법은 **흐름에서 복원**하는 것이다.

    구역 i 재고(t) = 기초_i + 누적적재_i(t) − 누적인출_i(t)

기초_i(구역별 기초 재고)는 알 수 없으므로, **라인 기초 재고를 구역별 적재 비중으로 배분**한다.
그리고 매 시점 **합계를 실사 재고에 맞춰 재정규화**한다 — 라인 합계는 신뢰할 수 있기 때문이다
(현장 제시값이 실사 기록과 정확히 일치, §6-0-15).

⚠️ **이 값은 추정치다.** 다음 한계를 항상 함께 보고한다.
  · 기초 배분 가정 — 초기에는 이 가정이 지배하고, 회전이 돌면서 영향이 줄어든다.
  · 칸 넘침(§6-0-15 Q2) — 구역 경계 자체가 근사라 구역 간 물량이 새어 나간다.
  · 계량 차이(§6-0-14 Q3) — 적재·인출 계량 기준이 달라 잔차가 남고, 재정규화가 이를 흡수한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import schema as S

#: 기초 재고 배분에 쓸 초기 관측 창(일). 이 기간의 구역별 적재 비중으로 기초를 나눈다.
OPENING_SPLIT_DAYS = 14


@dataclass
class ZoneInventory:
    line: str
    at: pd.Timestamp
    zones: pd.DataFrame          # zone, ton, cao, mgo, n_loads, last_load
    line_total: float            # 실사 기준 라인 합계(톤)
    anchored: bool               # 실사에 맞춰 재정규화했는가
    notes: list[str]

    def usable(self, min_ton: float = 0.0) -> pd.DataFrame:
        d = self.zones
        return d[(d["ton"] > min_ton) & d["cao"].notna()].sort_values("zone")


def _line_stock_at(stock: pd.DataFrame, line: str, at: pd.Timestamp) -> float:
    g = stock[(stock["line"] == line)].dropna(subset=["stock_ton"]).sort_values("datetime")
    g = g[g["datetime"] <= at]
    return float(g["stock_ton"].iloc[-1]) if len(g) else float("nan")


def zone_inventory(mine: pd.DataFrame, osp_exp: pd.DataFrame, stock: pd.DataFrame,
                   line: str, at: pd.Timestamp | None = None) -> ZoneInventory | None:
    """`at` 시점의 구역별 재고와 그 구역의 현재 품위를 복원한다."""
    # 빈/부분 입력에서도 예외 대신 None 을 낸다 (컬럼 자체가 없을 수 있다)
    need_m = {"line", "zone", "datetime", "tonnage", "cao"}
    need_o = {"line", "zone", "datetime", "withdrawn_ton"}
    if not need_m <= set(mine.columns) or not need_o <= set(osp_exp.columns):
        return None
    m = mine[(mine["line"] == line)].dropna(subset=["zone", "datetime"]).copy()
    o = osp_exp[(osp_exp["line"] == line)].dropna(subset=["zone", "datetime"]).copy()
    if not len(m) or not len(o):
        return None
    at = pd.Timestamp(at) if at is not None else max(m["datetime"].max(), o["datetime"].max())
    notes: list[str] = []

    m_to = m[m["datetime"] <= at]
    o_to = o[o["datetime"] <= at]
    loads = m_to.groupby("zone")["tonnage"].sum()
    draws = o_to.groupby("zone")["withdrawn_ton"].sum()

    # 기초 재고를 '초기 창의 구역별 적재 비중' 으로 배분한다
    open_tot = float(S.OSP_OPENING_STOCK.get(line, float("nan")))
    t0 = m["datetime"].min()
    early = m[m["datetime"] <= t0 + pd.Timedelta(days=OPENING_SPLIT_DAYS)]
    share = early.groupby("zone")["tonnage"].sum()
    if share.sum() > 0 and np.isfinite(open_tot):
        share = share / share.sum()
        notes.append(f"기초 재고 {open_tot:,.0f}톤을 초기 {OPENING_SPLIT_DAYS}일 적재 비중으로 배분")
    else:
        share = pd.Series(dtype=float)
        open_tot = 0.0
        notes.append("기초 재고 정보 없음 — 0에서 시작(초기 구간 신뢰도 낮음)")

    zones = sorted(set(loads.index) | set(draws.index) | set(share.index))
    ton = pd.Series(
        [float(share.get(z, 0.0)) * open_tot + float(loads.get(z, 0.0)) - float(draws.get(z, 0.0))
         for z in zones], index=zones, dtype=float)

    neg = ton[ton < 0]
    if len(neg):
        notes.append(f"음수로 계산된 구역 {len(neg)}개({float(neg.sum()):,.0f}톤) — "
                     "칸 넘침·귀속 오차로 보이며 0으로 절단")
        ton = ton.clip(lower=0.0)

    # 라인 합계를 실사에 맞춘다 (계량 기준 차이·누락을 여기서 흡수)
    line_total = _line_stock_at(stock, line, at)
    anchored = False
    if np.isfinite(line_total) and ton.sum() > 0:
        k = line_total / ton.sum()
        notes.append(f"실사 라인 재고 {line_total:,.0f}톤에 맞춰 ×{k:.2f} 재정규화 "
                     f"(복원 합계 {ton.sum():,.0f}톤)")
        ton = ton * k
        anchored = True

    # 각 구역의 '현재 품위' = 그 구역에 마지막으로 적재된 품위 (인출은 최근분부터 나간다는 가정)
    rows = []
    for z in zones:
        mz = m_to[m_to["zone"] == z].sort_values("datetime")
        cao = mgo = np.nan
        last = pd.NaT
        if len(mz):
            w = pd.to_numeric(mz["tonnage"], errors="coerce").fillna(0.0)
            recent = mz.tail(3)                      # 최근 3회 적재의 톤가중 — 단발 이상치 완화
            wr = pd.to_numeric(recent["tonnage"], errors="coerce").fillna(0.0)
            if wr.sum() > 0:
                cao = float(np.average(recent["cao"].astype(float), weights=wr))
                if "mgo" in recent:
                    mm = recent["mgo"].astype(float)
                    if mm.notna().any():
                        mgo = float(np.average(mm.fillna(mm.mean()), weights=wr))
            last = mz["datetime"].iloc[-1]
            _ = w
        rows.append(dict(zone=float(z), ton=float(ton.get(z, 0.0)), cao=cao, mgo=mgo,
                         n_loads=int(len(mz)), last_load=last))
    df = pd.DataFrame(rows)
    # 품위를 모르는 구역은 처방에서 제외한다 (라인 평균으로 때우면 가짜 정밀도가 된다)
    unknown = df[df["cao"].isna() & (df["ton"] > 0)]
    if len(unknown):
        notes.append(f"품위 미상 구역 {len(unknown)}개({float(unknown['ton'].sum()):,.0f}톤) "
                     "— 처방 후보에서 제외")
    return ZoneInventory(line=line, at=at, zones=df, line_total=line_total,
                         anchored=anchored, notes=notes)


def withdrawal_rate(osp_exp: pd.DataFrame, line: str, days: int = 14) -> float:
    """최근 인출 속도(톤/시간). '몇 시간 적재하면' 을 톤으로 바꾸는 데 쓴다."""
    if "line" not in osp_exp.columns or "withdrawn_ton" not in osp_exp.columns:
        return float("nan")
    o = osp_exp[(osp_exp["line"] == line)].dropna(subset=["datetime"])
    if not len(o):
        return float("nan")
    hi = o["datetime"].max()
    w = o[o["datetime"] > hi - pd.Timedelta(days=days)]
    if not len(w):
        return float("nan")
    span = max((w["datetime"].max() - w["datetime"].min()).total_seconds() / 3600.0, 1.0)
    return float(pd.to_numeric(w["withdrawn_ton"], errors="coerce").sum() / span)
