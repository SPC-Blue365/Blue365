"""월간 '평균은 맞췄지만 고·저품위를 번갈아 쌓았다' 비교용 데이터 [Synthesis-Agent].

입력 (전부 실데이터, `data/raw/` 원본 → `src/data/clean.py` 정제):
  · 광산 49Q XRF(암분)   — 시트 `광산(49Q)_XRF` → `clean_mine_49Q` (교대 단위로 다시 묶음)
  · 야드 CNA 분석기(신설) — 시트 `CNA data`      → `clean_yard` (2분 간격)
  · 야드변경(기존·신설)   — 시트 `기존라인/신설라인 야드변경` → `load_yard_change`

⭐️ 야드변경 행의 CaO 는 **그 시각에 끝난(직전) 파일의 평균 품위**로 읽는다.
   근거(2026-11-24, 신설 75행): 행 CaO 와 CNA 구간 평균의 일치도가
   '그 시각부터 쌓은 파일' 로 읽으면 r=0.26 · MAE 0.47%p, '그 시각까지 쌓은 파일' 로 읽으면
   r=0.97 · MAE 0.07%p 다. 기준 판정은 `alignment_check()` 로 매번 다시 계산한다.
   (현장 확인 전까지는 데이터 근거에 의한 해석이다 — docs/field_questions.md 6차)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import schema as S

TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol
HI, LO = TARGET + TOL, TARGET - TOL


def mine_shifts(mine: pd.DataFrame, line: str, start, end) -> pd.DataFrame:
    """49Q 구역 전개 행 → **교대 1건 = 1행** (같은 교대는 CaO 가 같고 물량만 나뉜다)."""
    m = mine[(mine["source"] == "49Q") & (mine["line"] == line)
             & (mine["datetime"] >= start) & (mine["datetime"] < end)].dropna(subset=["cao"])
    if not len(m):
        return pd.DataFrame(columns=["datetime", "shift", "cao", "tonnage"])
    g = (m.groupby(["date", "shift"], as_index=False)
          .agg(datetime=("datetime", "first"), cao=("cao", "first"),
               tonnage=("tonnage", "sum")))
    return g.sort_values("datetime").reset_index(drop=True)[["datetime", "shift", "cao", "tonnage"]]


def hourly(analyzer: pd.DataFrame, start, end) -> pd.Series:
    """분석기 원측정 → 1시간 평균 (측정 없는 시간은 빠진다)."""
    a = analyzer[(analyzer["datetime"] >= start) & (analyzer["datetime"] < end)].dropna(subset=["cao"])
    if not len(a):
        return pd.Series(dtype=float)
    return a.set_index("datetime")["cao"].resample("1h").mean().dropna()


BANDS = ("lo", "in", "hi")


def band_parts(h: pd.Series) -> dict[str, pd.Series]:
    """값을 저품위(<LO) · 목표(LO~HI) · 고품위(>HI) 로 나눈다 — 경계값은 목표에 넣는다."""
    return {"lo": h[h < LO], "in": h[(h >= LO) & (h <= HI)], "hi": h[h > HI]}


def _segments(yc_line: pd.DataFrame, until) -> pd.DataFrame:
    """야드변경 시각 사이 = 파일 1개. 파일 i 의 확정 품위 = **다음** 변경 행의 CaO·물량."""
    y = yc_line.sort_values("datetime").reset_index(drop=True)
    seg = pd.DataFrame({"start": y["datetime"],
                        "end": y["datetime"].shift(-1),
                        "sheet_cao": y["cao"].shift(-1),
                        "sheet_ton": y["tonnage"].shift(-1),
                        "yard_next": y["yard"].shift(-1)})
    seg["closed"] = seg["end"].notna()
    seg["end"] = seg["end"].fillna(pd.Timestamp(until))
    return seg


def alignment_check(yc_line: pd.DataFrame, analyzer: pd.DataFrame) -> dict:
    """야드변경 CaO 를 '앞 파일' 로 읽을지 '뒤 파일' 로 읽을지 — 분석기와의 일치도로 판정."""
    y = yc_line.sort_values("datetime").reset_index(drop=True)
    a = analyzer.dropna(subset=["cao"])
    seg = []
    for i in range(len(y)):
        s = y["datetime"].iat[i]
        e = y["datetime"].iat[i + 1] if i + 1 < len(y) else a["datetime"].max()
        seg.append(a.loc[(a["datetime"] >= s) & (a["datetime"] < e), "cao"].mean())
    fwd = pd.Series(seg)
    prev = fwd.shift(1)
    ok = y["cao"].notna() & fwd.notna() & prev.notna()
    out = {"n": int(ok.sum())}
    for k, v in (("forward", fwd), ("previous", prev)):
        out[k] = dict(r=float(np.corrcoef(y.loc[ok, "cao"], v[ok])[0, 1]) if ok.sum() > 2 else np.nan,
                      mae=float(np.mean(np.abs(y.loc[ok, "cao"] - v[ok]))) if ok.any() else np.nan)
    out["reading"] = "previous" if out["previous"]["mae"] <= out["forward"]["mae"] else "forward"
    return out


def piles(yc_line: pd.DataFrame, analyzer: pd.DataFrame | None, start, end, until) -> pd.DataFrame:
    """기간과 겹치는 파일별 — 시트 확정 품위 + (있으면) 분석기 1시간 값의 고/목표/저 비율."""
    seg = _segments(yc_line, until)
    seg = seg[(seg["end"] > pd.Timestamp(start)) & (seg["start"] < pd.Timestamp(end))].copy()
    rows = []
    for _, r in seg.iterrows():
        d = dict(r)
        h = hourly(analyzer, r["start"], r["end"]) if analyzer is not None else pd.Series(dtype=float)
        d.update(n_hours=len(h),
                 cna_mean=float(h.mean()) if len(h) else np.nan,
                 cna_sd=float(h.std()) if len(h) > 1 else np.nan,
                 p10=float(h.quantile(.1)) if len(h) else np.nan,
                 p90=float(h.quantile(.9)) if len(h) else np.nan,
                 hi=float((h > HI).mean()) if len(h) else np.nan,
                 lo=float((h < LO).mean()) if len(h) else np.nan)
        d["inb"] = 1 - d["hi"] - d["lo"] if len(h) else np.nan
        # 구간(저품위/목표/고품위) 안의 1시간 값 평균·표준편차 — '얼마나 높고 낮았나'
        for k, part in band_parts(h).items():
            d[f"{k}_n"] = len(part)
            d[f"{k}_mean"] = float(part.mean()) if len(part) else np.nan
            d[f"{k}_sd"] = float(part.std()) if len(part) > 1 else np.nan
        rows.append(d)
    cols = (list(seg.columns) + ["n_hours", "cna_mean", "cna_sd", "p10", "p90", "hi", "lo", "inb"]
            + [f"{k}_{m}" for k in BANDS for m in ("n", "mean", "sd")])
    return pd.DataFrame(rows, columns=cols).reset_index(drop=True)


@dataclass
class LineSwing:
    line: str
    shifts: pd.DataFrame          # 49Q 교대
    hourly: pd.Series             # 야드 분석기 1시간 평균 (없으면 빈 Series)
    piles: pd.DataFrame           # 파일별
    done: pd.DataFrame            # 기간 안에 '끝난' 파일 (월 평균 산정 대상)

    @property
    def pile_mean(self) -> float:
        d = self.done.dropna(subset=["sheet_cao", "sheet_ton"])
        return float(np.average(d["sheet_cao"], weights=d["sheet_ton"])) if len(d) else np.nan

    @property
    def pile_sd(self) -> float:
        return float(self.done["sheet_cao"].std()) if len(self.done) > 1 else np.nan


def month_swing(month: str, mine: pd.DataFrame, yc: pd.DataFrame,
                analyzers: dict[str, pd.DataFrame | None]) -> dict[str, LineSwing]:
    """month='2026-11' → 라인별 LineSwing. analyzers 는 라인→분석기(없으면 None)."""
    start = pd.Timestamp(f"{month}-01")
    end = start + pd.offsets.MonthBegin(1)
    out = {}
    for line, an in analyzers.items():
        y = yc[yc["line"] == line]
        if an is not None and len(an):
            until = an["datetime"].max()
        else:                                   # 분석기 없는 라인 — 광산·야드변경 중 마지막 기록
            cand = [y["datetime"].max(), mine.loc[mine["line"] == line, "datetime"].max()]
            cand = [pd.Timestamp(c) for c in cand if pd.notna(c)]
            until = max(cand) if cand else end
        until = min(pd.Timestamp(until), end)
        p = piles(y, an, start, end, until)
        done = p[p["closed"] & (p["end"] >= start) & (p["end"] < end)] if len(p) else p
        out[line] = LineSwing(line, mine_shifts(mine, line, start, end),
                              hourly(an, start, end) if an is not None else pd.Series(dtype=float),
                              p, done.reset_index(drop=True))
    return out
