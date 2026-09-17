"""적치장 더미 시뮬레이션 — 인출 물량이 **실제로 어디서 나왔는지** 재구성한다 [Matching-Agent].

⭐️ 왜 필요한가 — **구역 귀속 붕괴**(§6-0-16, §6-0-22)

인출 기록의 구역 번호를 액면 그대로 믿으면, 그 구역에 **쌓은 적도 없는 물량**을 뽑은 것이 된다.
기록을 시간 순서대로 재생해 보면 기존 라인 인출의 43%, 신설 32% 가 **그 시점 그 구역 재고로는
불가능**하다. 즉 인출 구역 번호는 '물량이 쌓인 곳' 이 아니라 **인출 설비가 서 있던 자리**다.

그렇다면 품위를 그 번호로 찾을 것이 아니라, **재고에서 무엇이 나왔는지** 재구성해야 한다.
다만 '어떤 순서로 뽑는가' 는 기록에 없으므로 **하나로 단정하지 않는다**(§2-2). 대신 서로 다른
가정을 나란히 돌리고, 결론이 가정에 좌우되는지 함께 본다(§2-1).

    label  기록된 구역에서만          — 현행 해석. 재고가 모자라 물리적으로 성립하지 않는다.
    near   기록된 구역 → 가까운 번호 순 — 라벨이 '설비 위치' 라는 해석. 이동을 최소화한다.
    mix    라인 전체에서 재고 비례     — 완전혼합(더미가 고르게 섞인다).
    fifo   먼저 쌓은 것부터            — 선입선출.
    lifo   나중에 쌓은 것부터          — 더미 위에서부터 긁어낸다.

**이 모듈은 품위를 더 정확하게 만들지 못한다.** 네 가정 중 어느 것도 야드 실측과의 일치를
유의하게 개선하지 못했다(§6-0-22). 이 모듈이 주는 것은 **정확도가 아니라 정직한 불확실성**이다 —
`attribution_sd()` 가 내는 값이 처방의 적중 확률에 그대로 들어간다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S

#: 인출 순서 가정. `label` 은 현행 해석이며 성립하지 않음을 **보이기 위한** 대조군이다.
DRAW_ORDERS = ("near", "mix", "fifo", "lifo")

#: 구역별 귀속 오차를 추정하려면 그 구역에서 최소한 이만큼은 뽑혔어야 한다(톤).
MIN_ZONE_TON = 500.0


class Pile:
    """한 라인의 적치장 — 구역마다 (톤, 품위, 적재시각) 파셀 목록을 들고 있다."""

    def __init__(self, opening: dict, open_cao: float, open_mgo: float, t0):
        self.z: dict[float, list[dict]] = {}
        for zone, ton in opening.items():
            if ton and ton > 0:
                self.z.setdefault(float(zone), []).append(
                    dict(ton=float(ton), cao=open_cao, mgo=open_mgo, t=t0))
        self.short = 0.0          # 재고보다 많이 뽑으라고 나온 물량 (기록 모순의 크기)

    def load(self, zone, ton, cao, mgo, t) -> None:
        if ton and ton > 0 and zone == zone:
            self.z.setdefault(float(zone), []).append(
                dict(ton=float(ton), cao=cao, mgo=mgo, t=t))

    def stock(self, zone=None) -> float:
        zs = self.z.values() if zone is None else [self.z.get(zone, [])]
        return sum(p["ton"] for ps in zs for p in ps)

    def _take(self, zone, want):
        """그 구역에서 먼저 쌓인 파셀부터 꺼낸다 → ([(톤, CaO, MgO)], 남은 요구량)"""
        out, ps = [], self.z.get(zone, [])
        while want > 1e-9 and ps:
            p = ps[0]
            take = min(p["ton"], want)
            out.append((take, p["cao"], p["mgo"]))
            p["ton"] -= take
            want -= take
            if p["ton"] <= 1e-9:
                ps.pop(0)
        return out, want

    def draw(self, zone, ton, order: str):
        """`ton` 톤을 뽑아 (CaO, MgO, 실제 뽑힌 톤, {출처구역: 톤}) 를 돌려준다."""
        want, got, src = float(ton) if ton == ton else float("nan"), [], {}
        # ⚠️ 결측 물량을 그대로 흘리면 `min(x, nan)` 이 x 를 돌려주어 더미를 통째로 비운다
        if not np.isfinite(want) or want <= 0:
            return np.nan, np.nan, 0.0, src

        if order in ("label", "near"):
            if order == "label":
                seq = [zone]
            else:
                # 라벨 구역을 먼저, 그 다음 번호가 가까운 순 (라벨 = 인출 설비 위치라는 해석)
                seq = sorted(self.z, key=lambda k: (abs(k - zone) if zone == zone else k, k))
                if zone == zone and zone not in seq:
                    seq = [zone] + seq
            for zz in seq:
                if want <= 1e-9:
                    break
                part, want = self._take(zz, want)
                if part:
                    got += part
                    src[zz] = src.get(zz, 0.0) + sum(p[0] for p in part)
        elif order == "mix":
            tot = self.stock()
            if tot > 1e-9:
                frac = min(want, tot) / tot
                for zz in list(self.z):
                    part, _ = self._take(zz, self.stock(zz) * frac)
                    if part:
                        got += part
                        src[zz] = src.get(zz, 0.0) + sum(p[0] for p in part)
                want = max(want - min(want, tot), 0.0)
        else:                                   # fifo / lifo — 라인 전체 파셀을 시각 순으로
            parcels = [(zz, p) for zz, ps in self.z.items() for p in ps]
            parcels.sort(key=lambda kp: kp[1]["t"], reverse=(order == "lifo"))
            for zz, p in parcels:
                if want <= 1e-9:
                    break
                take = min(p["ton"], want)
                got.append((take, p["cao"], p["mgo"]))
                src[zz] = src.get(zz, 0.0) + take
                p["ton"] -= take
                want -= take
            for zz in list(self.z):
                self.z[zz] = [p for p in self.z[zz] if p["ton"] > 1e-9]

        if want > 1e-9:
            self.short += want
        w = sum(g[0] for g in got)
        if w <= 1e-9:
            return np.nan, np.nan, 0.0, src
        return _wmean(got, 1), _wmean(got, 2), w, src


def _wmean(got, i) -> float:
    num = sum(g[0] * g[i] for g in got if g[i] == g[i])
    den = sum(g[0] for g in got if g[i] == g[i])
    return num / den if den > 0 else np.nan


def _opening(mine: pd.DataFrame, line: str):
    """기초 재고를 구역에 배분하고 그 품위를 가정한다 (inventory.py 와 같은 규칙).

    ⚠️ 구역별 기초 재고도, 그 품위도 **측정하지 않는다**(§6-0-15 Q1). 초기 14일 적재 비중으로
       나누고 품위는 그 기간의 톤가중 평균으로 둔다 — **가정이며, 그렇게 표시한다**(§2-1).
    """
    t0 = pd.Timestamp(S.OSP_OPENING_STOCK["date"])
    head = mine[mine["datetime"] <= t0 + pd.Timedelta(days=14)]
    share = head.groupby("zone")["tonnage"].sum()
    total = float(S.OSP_OPENING_STOCK.get(line, 0.0))
    if share.sum() > 0:
        opening = {float(z): total * float(v) / float(share.sum()) for z, v in share.items()}
    elif len(mine):
        opening = {float(mine["zone"].median()): total}
    else:
        opening = {}
    def _g(col):
        h = head.dropna(subset=[col])
        if not len(h):
            return np.nan
        return float(np.average(h[col], weights=h["tonnage"].clip(lower=0) + 1e-9))
    return opening, _g("cao"), _g("mgo"), t0


def simulate(mine: pd.DataFrame, osp: pd.DataFrame, line: str, order: str) -> pd.DataFrame:
    """한 라인을 이벤트 순서대로 재생해 **인출 행마다 실제 품위**를 추정한다.

    반환 프레임은 **원본 `osp` 의 인덱스를 유지**하므로 그대로 붙여 쓸 수 있다.
    컬럼: datetime · zone(기록된 라벨) · ask(요구 톤) · sim_cao · sim_mgo · sim_ton ·
         same_zone(라벨 구역에서 나온 비율)
    `attrs["short_ton"]` = 재고로 댈 수 없었던 물량, `attrs["opening_cao"]` = 기초 품위 가정.
    """
    cols = ["datetime", "zone", "ask", "sim_cao", "sim_mgo", "sim_ton", "same_zone"]
    # 빈 입력·부분 데이터(가동 중지 라인 등)에서 조용히 빈 프레임을 돌려준다
    need_m = {"line", "datetime", "zone", "tonnage", "cao", "mgo"}
    need_o = {"line", "datetime", "zone", "withdrawn_ton"}
    if mine is None or osp is None or not need_m <= set(mine.columns) \
            or not need_o <= set(osp.columns):
        return pd.DataFrame(columns=cols)
    m = mine[mine["line"] == line].dropna(subset=["datetime", "zone"])
    o = osp[osp["line"] == line].dropna(subset=["datetime"])
    if not len(m) or not len(o):
        return pd.DataFrame(columns=cols)

    opening, ocao, omgo, t0 = _opening(m, line)
    pile = Pile(opening, ocao, omgo, t0 - pd.Timedelta(days=1))
    ev = pd.concat([
        m.assign(kind="L")[["datetime", "zone", "tonnage", "cao", "mgo", "kind"]],
        o.assign(kind="W")[["datetime", "zone", "withdrawn_ton", "kind"]].rename(
            columns={"withdrawn_ton": "tonnage"}),
    ])                       # ⚠️ ignore_index 금지 — 인출 행의 원본 인덱스를 살려 돌려준다
    ev["ordk"] = (ev["kind"] == "W").astype(int)      # 같은 시각이면 적재를 먼저 반영
    ev = ev.sort_values(["datetime", "ordk"], kind="stable")

    rows, idx = [], []
    for r in ev.itertuples():
        if r.kind == "L":
            pile.load(r.zone, r.tonnage, r.cao, r.mgo, r.datetime)
            continue
        cao, mgo, w, src = pile.draw(r.zone, r.tonnage, order)
        idx.append(r.Index)
        rows.append(dict(datetime=r.datetime, zone=r.zone, ask=r.tonnage,
                         sim_cao=cao, sim_mgo=mgo, sim_ton=w,
                         same_zone=(src.get(r.zone, 0.0) / w if w > 0 else np.nan)))
    out = pd.DataFrame(rows, index=idx, columns=cols)
    out.attrs["short_ton"] = pile.short
    out.attrs["opening_cao"] = ocao
    return out


def label_feasibility(mine: pd.DataFrame, osp: pd.DataFrame, line: str) -> dict:
    """⭐️ **현행 해석이 물리적으로 성립하는가** — 기록된 구역 재고만으로 인출을 댈 수 있나.

    구역별 총량 비교(`prescribe.zone_balance_health`)보다 강한 검사다. 총량이 맞아도 **그 시점에**
    재고가 없었으면 불가능하기 때문이다. 반환하는 `short_share` 는 순수한 물량 수지이며
    품위 가정이 전혀 섞이지 않는다.
    """
    sim = simulate(mine, osp, line, "label")
    if not len(sim):
        return {}
    asked = float(pd.to_numeric(sim["ask"], errors="coerce").sum())
    short = float(sim.attrs.get("short_ton", 0.0))
    return dict(line=line, asked_ton=asked, short_ton=short,
                short_share=(short / asked * 100 if asked > 0 else float("nan")),
                n_events=len(sim))


def attribution_sd(mine: pd.DataFrame, osp: pd.DataFrame, line: str,
                   grade_col: str = "expected_cao") -> dict:
    """구역별 **귀속 오차**의 표준편차(%p) — 처방 불확실성에 더해야 할 몫.

    현행이 쓰는 품위(`expected_cao`, 구역 이력)와 더미에서 실제로 나온 품위의 차이를 잰다.
    ⭐️ **인출 순서 가정 네 가지를 모두 돌려 중앙값**을 쓴다 — 어느 하나에 결론을 걸지 않는다.
    치우침(bias)도 분산에 합산한다(평균이 틀린 것도 오차이므로).

    반환: dict(per_zone={구역: sd}, median, overall_sd, bias, band=(최소, 최대), same_zone_pct)
    """
    per: dict[float, list[float]] = {}
    overall, biases, sames = [], [], []
    for order in DRAW_ORDERS:
        sim = simulate(mine, osp, line, order)
        if not len(sim):
            continue
        nom = pd.to_numeric(osp.reindex(sim.index)[grade_col], errors="coerce")
        d = pd.DataFrame({"zone": sim["zone"].to_numpy(), "ton": sim["sim_ton"].to_numpy(),
                          "same": sim["same_zone"].to_numpy(),
                          "err": sim["sim_cao"].to_numpy() - nom.to_numpy()}
                         ).dropna(subset=["err"])
        if not len(d):
            continue
        w = d["ton"].clip(lower=0) + 1e-9
        b = float(np.average(d["err"], weights=w))
        overall.append(float(np.sqrt(np.average((d["err"] - b) ** 2, weights=w))))
        biases.append(b)
        sames.append(float(np.average(np.nan_to_num(d["same"]), weights=w)) * 100)
        for z, g in d.groupby("zone"):
            if g["ton"].sum() < MIN_ZONE_TON:
                continue
            ww = g["ton"].clip(lower=0) + 1e-9
            zb = float(np.average(g["err"], weights=ww))
            per.setdefault(float(z), []).append(
                float(np.sqrt(np.average((g["err"] - zb) ** 2, weights=ww) + zb ** 2)))
    if not overall:
        return {}
    pz = {z: float(np.median(v)) for z, v in per.items()}
    return dict(per_zone=pz, median=float(np.median(list(pz.values()))) if pz else float("nan"),
                overall_sd=float(np.median(overall)), bias=float(np.median(biases)),
                band=(float(min(overall)), float(max(overall))),
                same_zone_pct=float(np.median(sames)), orders=list(DRAW_ORDERS))
