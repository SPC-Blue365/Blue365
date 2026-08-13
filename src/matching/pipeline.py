"""매칭 파이프라인 [Matching-Agent].

광산(구역 품위) → OSP(인출) → 야드(CNA) 를 연결해 ML용 통합 데이터셋을 만든다.

흐름:
  1) 구역-품위 테이블로 OSP 인출에 '예상 CaO' 부여 (라인+구역, 없으면 전역 fallback)
  2) OSP 인출을 시간창(기본 1시간)으로 집계 — 톤가중 예상 CaO + 라인/총 인출톤
  3) 야드 CNA를 같은 시간창으로 집계 — 평균/표준편차 CaO (목표 변수)
  4) Time-Lag 추정 — OSP 집계 시계열을 지연시키며 야드와 상관 최대가 되는 지연 탐색
  5) 최적 지연으로 OSP 피처와 야드 목표를 정렬한 통합 데이터셋 반환

⭐️ Time-Lag 은 상수 가정이 아니라 '데이터로 추정'한다(사용자 확인). 추정 근거(상관곡선)를 함께 반환.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import schema as S


# --------------------------------------------------------------------------- #
# 1) OSP 인출 → 예상 CaO 부여 (광산 구역-품위 매칭)
# --------------------------------------------------------------------------- #
def assign_expected_cao(
    osp: pd.DataFrame, by_line: pd.DataFrame, by_zone: pd.DataFrame
) -> pd.DataFrame:
    """OSP 인출 각 행(라인·구역)에 광산 구역-품위로 예상 CaO를 매칭.

    우선 라인+구역 평균, 없으면 전역 구역 평균으로 fallback.
    """
    out = osp.merge(by_line[["line", "zone", "cao_zone"]], on=["line", "zone"], how="left")
    out = out.merge(by_zone[["zone", "cao_zone_global"]], on="zone", how="left")
    out["expected_cao"] = out["cao_zone"].fillna(out["cao_zone_global"])
    out["cao_source"] = np.where(
        out["cao_zone"].notna(), "line", np.where(out["cao_zone_global"].notna(), "global", "none")
    )
    return out


# --------------------------------------------------------------------------- #
# 2) OSP 시간창 집계 (톤가중 예상 CaO + 인출톤 피처)
# --------------------------------------------------------------------------- #
def _wmean(values: pd.Series, weights: pd.Series) -> float:
    m = values.notna() & weights.notna()
    if m.sum() == 0 or weights[m].sum() == 0:
        return np.nan
    return float(np.average(values[m], weights=weights[m]))


def aggregate_osp_hourly(osp_exp: pd.DataFrame, freq: str = "1h") -> pd.DataFrame:
    """OSP 인출(예상 CaO 포함)을 시간창으로 집계."""
    df = osp_exp.dropna(subset=["datetime"]).copy()
    df["tbin"] = df["datetime"].dt.floor(freq)

    def agg(g: pd.DataFrame) -> pd.Series:
        total = g["withdrawn_ton"].sum(min_count=1)
        old = g.loc[g["line"] == S.LINE_OLD, "withdrawn_ton"].sum(min_count=1)
        new = g.loc[g["line"] == S.LINE_NEW, "withdrawn_ton"].sum(min_count=1)
        return pd.Series(
            dict(
                osp_expected_cao=_wmean(g["expected_cao"], g["withdrawn_ton"]),
                osp_expected_mgo=(
                    _wmean(g["expected_mgo"], g["withdrawn_ton"])
                    if "expected_mgo" in g
                    else np.nan
                ),
                osp_total_ton=total,
                osp_old_ton=old,
                osp_new_ton=new,
                osp_n_events=len(g),
                osp_n_zones=g["zone"].nunique(),
                osp_cao_spread=g["expected_cao"].std(),
            )
        )

    out = df.groupby("tbin").apply(agg, include_groups=False).reset_index()
    return out.rename(columns={"tbin": "datetime"})


# --------------------------------------------------------------------------- #
# 3) 야드 CNA 시간창 집계 (목표 변수)
# --------------------------------------------------------------------------- #
def aggregate_yard_hourly(yard: pd.DataFrame, freq: str = "1h") -> pd.DataFrame:
    """야드 CNA를 시간창으로 집계 — 평균/표준편차 CaO (목표)."""
    df = yard.dropna(subset=["datetime"]).copy()
    if "load" not in df.columns:
        df["load"] = df["tph"] if "tph" in df.columns else np.nan
    df["tbin"] = df["datetime"].dt.floor(freq)
    out = (
        df.groupby("tbin")
        .agg(
            yard_cao=("cao", "mean"),
            yard_cao_std=("cao", "std"),
            yard_mgo=("mgo", "mean"),
            yard_load=("load", "mean"),
            yard_n=("cao", "size"),
        )
        .reset_index()
        .rename(columns={"tbin": "datetime"})
    )
    return out


# --------------------------------------------------------------------------- #
# 4) Time-Lag 추정 (상관 최대 지연)
# --------------------------------------------------------------------------- #
@dataclass
class LagResult:
    best_lag_hours: int
    best_corr: float
    curve: pd.DataFrame  # lag별 상관


def estimate_time_lag(
    osp_h: pd.DataFrame, yard_h: pd.DataFrame, max_lag_hours: int = 24, freq_hours: int = 1
) -> LagResult:
    """OSP 예상 CaO를 지연시키며 야드 CaO와 피어슨 상관이 최대인 지연을 찾는다.

    lag>0 : OSP가 야드보다 lag 시간 앞선다(= 인출 후 lag 뒤 야드 적재).
    """
    a = osp_h.set_index("datetime")["osp_expected_cao"].asfreq(f"{freq_hours}h")
    b = yard_h.set_index("datetime")["yard_cao"].asfreq(f"{freq_hours}h")
    idx = a.index.union(b.index)
    a = a.reindex(idx)
    b = b.reindex(idx)

    records = []
    for lag in range(0, max_lag_hours + 1):
        shifted = a.shift(lag)  # OSP를 lag만큼 뒤로 → 미래 야드와 정렬
        m = shifted.notna() & b.notna()
        n = int(m.sum())
        corr = float(shifted[m].corr(b[m])) if n >= 10 else np.nan
        records.append(dict(lag_hours=lag, corr=corr, n=n))
    curve = pd.DataFrame(records)
    valid = curve.dropna(subset=["corr"])
    if valid.empty:
        return LagResult(best_lag_hours=0, best_corr=np.nan, curve=curve)
    best = valid.loc[valid["corr"].idxmax()]
    return LagResult(int(best["lag_hours"]), float(best["corr"]), curve)


# --------------------------------------------------------------------------- #
# 5) 통합 데이터셋 (최적 지연 정렬)
# --------------------------------------------------------------------------- #
def build_matched_dataset(
    osp_h: pd.DataFrame, yard_h: pd.DataFrame, lag_hours: int
) -> pd.DataFrame:
    """OSP 피처를 lag만큼 미뤄 야드(목표)와 같은 시각에 정렬한 통합 데이터셋."""
    osp_shift = osp_h.copy()
    osp_shift["datetime"] = osp_shift["datetime"] + pd.Timedelta(hours=lag_hours)
    merged = yard_h.merge(osp_shift, on="datetime", how="inner")
    merged["lag_hours"] = lag_hours
    return merged.sort_values("datetime").reset_index(drop=True)


#: 인출에 시간인지 매칭할 성분 — {광산 컬럼: OSP 인출 컬럼}
GRADE_COLS = {"cao": "expected_cao", "mgo": "expected_mgo"}

#: 부여된 품위의 출처 — 실측 기반인지 대체값인지 구별한다 (§6-0-13)
GRADE_SOURCE = "grade_source"
SRC_ZONE = "zone_history"      # 그 구역의 실제 적재 이력에서 가져옴 (신뢰)
SRC_LINE_MEAN = "line_mean"    # 구역 적재 이력이 아직 없어 라인 평균으로 대체 (미상)
SRC_NO_ZONE = "no_zone"        # 인출 구역 자체가 미기재 (미상)

#: 실측 기반으로 볼 수 있는 출처 (나머지는 '미상' 물량으로 집계)
TRUSTED_SOURCES = (SRC_ZONE,)


def assign_expected_cao_timeaware(
    osp: pd.DataFrame, mine_long: pd.DataFrame
) -> pd.DataFrame:
    """OSP 인출(라인·지점·시각)에 '인출시각 이전 최근 적재 품위'를 매칭 (시간인지).

    P/W 지점은 위치 식별자이며 품위는 시간에 따라 변하므로, 정적 평균이 아니라
    해당 (line, 지점)에 가장 최근 적재된 광산 품위를 쓴다. 없으면 라인 전역 평균 fallback.

    ⭐️ CaO 와 MgO 를 **같은 규칙으로 함께** 부여한다(`GRADE_COLS`). 예전엔 CaO 만
    부여해 MgO 품위 수지를 아예 검증할 수 없었다. 두 성분은 같은 광산 행에서 나오므로
    같은 asof 매칭을 공유해야 서로 정합한다.
    """
    mine = mine_long[mine_long["line"].isin([S.LINE_OLD, S.LINE_NEW])].dropna(
        subset=["zone", "cao", "date"]
    )
    have = [c for c in GRADE_COLS if c in mine.columns]
    mine_daily = (
        mine.groupby(["line", "zone", "date"], as_index=False)[have].mean().sort_values("date")
    )
    line_glob = mine.groupby("line")[have].mean()

    o = osp.dropna(subset=["datetime"]).copy()
    o["date"] = o["datetime"].dt.floor("D")
    # ⭐️ 인출지점(zone)이 비어도 **물량은 버리지 않는다**. 지점별 품위 매칭만 불가하므로
    #    아래 fillna 에서 라인 전역 평균으로 대체된다.
    #    (예전엔 zone 결측 행을 통째로 버려 인출 2,000톤이 사라졌다)
    nan_cols = {GRADE_COLS[c]: np.nan for c in have}
    no_zone = o[o["zone"].isna()].assign(**nan_cols)
    o = o.dropna(subset=["zone"])
    parts = [no_zone] if len(no_zone) else []
    for (ln, zn), g in o.groupby(["line", "zone"]):
        mm = mine_daily[(mine_daily["line"] == ln) & (mine_daily["zone"] == zn)][["date"] + have]
        g = g.sort_values("date")
        if mm.empty:
            g = g.assign(**nan_cols)
        else:
            g = pd.merge_asof(g, mm, on="date", direction="backward").rename(
                columns={c: GRADE_COLS[c] for c in have}
            )
        parts.append(g)
    out = pd.concat(parts, ignore_index=True)
    # ⭐️ 대체값을 채우기 **전에** 출처를 기록한다. 채운 뒤에는 실측 기반인지
    #    라인 평균으로 때운 것인지 구별할 방법이 없어, 12.9% 의 물량에 가짜 정밀도가 붙는다.
    ref = GRADE_COLS[have[0]] if have else None
    if ref:
        out[GRADE_SOURCE] = np.where(
            out[ref].notna(), SRC_ZONE,
            np.where(out["zone"].isna(), SRC_NO_ZONE, SRC_LINE_MEAN))
    for c in have:
        out[GRADE_COLS[c]] = out[GRADE_COLS[c]].fillna(out["line"].map(line_glob[c]))
    return out


def build_line_dataset(
    osp_exp: pd.DataFrame, yard: pd.DataFrame, line: str, lag_hours: int, freq: str = "1h"
) -> pd.DataFrame:
    """한 라인(기존/신설)의 OSP 피처를 해당 야드(목표)와 lag 정렬한 통합셋."""
    osp_h = aggregate_osp_hourly(osp_exp[osp_exp["line"] == line], freq=freq)
    yard_h = aggregate_yard_hourly(yard, freq=freq)
    osp_h["datetime"] = osp_h["datetime"] + pd.Timedelta(hours=lag_hours)
    merged = yard_h.merge(osp_h, on="datetime", how="inner")
    merged["line"] = line
    merged["lag_hours"] = lag_hours
    return merged.sort_values("datetime").reset_index(drop=True)


def run_full_pipeline(
    mine_long: pd.DataFrame,
    osp: pd.DataFrame,
    yard: pd.DataFrame,
    by_line: pd.DataFrame,
    by_zone: pd.DataFrame,
    freq: str = "1h",
    max_lag_hours: int = 24,
):
    """전체 매칭 파이프라인 실행. (matched_df, lag_result, osp_exp) 반환."""
    osp_exp = assign_expected_cao(osp, by_line, by_zone)
    osp_h = aggregate_osp_hourly(osp_exp, freq=freq)
    yard_h = aggregate_yard_hourly(yard, freq=freq)
    lag = estimate_time_lag(osp_h, yard_h, max_lag_hours=max_lag_hours)
    matched = build_matched_dataset(osp_h, yard_h, lag.best_lag_hours)
    return matched, lag, osp_exp
