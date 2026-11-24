"""광산 품위(49Q 암분 XRF + 47Q 감마레이) ↔ 야드 CNA 비교용 데이터 [Synthesis-Agent].

두 가지 비교를 만든다 (전부 실데이터, §2-1):
  ① **같은 날 비교** — 광산이 그날 캔 돌의 품위(물량 가중) vs 그날 CNA 평균.
     시간차·OSP 혼합을 무시한 단순 비교라 '수준(평균 차이)' 을 보는 용도다.
  ② **추적 비교** — 파이프라인이 만든 'OSP 인출 품위' (광산 적재 품위를 라인 더미 재고에
     비례해 섞은 값, `pipeline.assign_expected_cao_timeaware`) 를 경로별 Time-Lag 만큼
     밀어 야드 시각에 맞춘 값(`dataset.build_line_data` 와 같은 정렬) vs CNA.
     '야드에 적재되는 돌의 광산 측 품위' 에 가장 가까운 값이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SOURCES = (("49Q", "49Q 암분 XRF"), ("47Q", "47Q 감마레이"))


def _wavg(g: pd.DataFrame) -> float:
    g = g.dropna(subset=["cao", "tonnage"])
    g = g[g["tonnage"] > 0]
    return float(np.average(g["cao"], weights=g["tonnage"])) if len(g) else np.nan


def mine_period(mine: pd.DataFrame, line: str, start, end) -> pd.DataFrame:
    """기간 안 그 라인 광산 행 (구역 전개 행이라 물량은 합이 맞고, 품위는 물량 가중으로 쓴다)."""
    m = mine[(mine["line"] == line) & (mine["datetime"] >= start) & (mine["datetime"] < end)]
    return m.dropna(subset=["cao"])


def mine_summary(m: pd.DataFrame) -> dict:
    """출처별·합계 물량 가중 CaO 와 물량."""
    out = {}
    for src, _ in SOURCES:
        g = m[m["source"] == src]
        out[src] = dict(cao=_wavg(g), ton=float(g["tonnage"].sum()))
    out["all"] = dict(cao=_wavg(m), ton=float(m["tonnage"].sum()))
    return out


def mine_daily(m: pd.DataFrame) -> pd.DataFrame:
    """일별 물량 가중 CaO — 열: 49Q, 47Q, all (그날 해당 출처가 없으면 NaN)."""
    if not len(m):
        return pd.DataFrame(columns=["49Q", "47Q", "all"])
    d = m.assign(day=m["datetime"].dt.floor("D"))
    cols = {src: d[d["source"] == src].groupby("day").apply(_wavg) for src, _ in SOURCES}
    cols["all"] = d.groupby("day").apply(_wavg)
    return pd.DataFrame(cols)


def traced_hourly(line_data) -> pd.Series:
    """OSP 인출 품위(광산 49Q+47Q 를 더미 재고로 섞은 값)를 야드 시각으로 민 1시간 값."""
    oh = line_data.osp_hourly
    if oh is None or not len(oh):
        return pd.Series(dtype=float)
    s = oh["impl"].dropna().copy()
    s.index = s.index + pd.Timedelta(hours=int(line_data.lag_hours))
    return s


def agreement(a: pd.Series, b: pd.Series) -> dict:
    """두 시계열(같은 인덱스 단위)의 평균 차이·상관·편차(각자 평균을 뺀 값) 상관."""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(j) < 3:
        return dict(n=len(j), bias=np.nan, r=np.nan, mae=np.nan)
    return dict(n=len(j), bias=float((j["a"] - j["b"]).mean()),
                r=float(j["a"].corr(j["b"])),
                mae=float((j["a"] - j["b"]).abs().mean()))


def pile_compare(piles: pd.DataFrame, traced: pd.Series, cna: pd.Series) -> pd.DataFrame:
    """파일(야드변경 구간)별 — 추적 광산 품위 평균 vs CNA 평균 vs 시트 확정 품위."""
    rows = []
    for _, r in piles.iterrows():
        t = traced[(traced.index >= r["start"]) & (traced.index < r["end"])]
        c = cna[(cna.index >= r["start"]) & (cna.index < r["end"])]
        rows.append(dict(start=r["start"], end=r["end"], closed=r["closed"], sheet_cao=r["sheet_cao"],
                         traced=float(t.mean()) if len(t) else np.nan, traced_n=len(t),
                         cna=float(c.mean()) if len(c) else np.nan, cna_n=len(c)))
    return pd.DataFrame(rows, columns=["start", "end", "closed", "sheet_cao", "traced", "traced_n",
                                       "cna", "cna_n"])
