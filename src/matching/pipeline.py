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


#: 목적지 라인 컬럼 — `clean_osp` 가 `공정구분` 에서 뽑는다 (§6-0-21)
DEST_LINE = "dest_line"


def osp_to_yard(osp_exp: pd.DataFrame, line: str) -> pd.DataFrame:
    """그 야드 라인으로 **들어간** 인출만 고른다 (⭐️ 목적지 기준).

    출처(`line`)와 목적지(`dest_line`)는 다르다. 기존 OSP 에서 뽑아 신설 라인으로 보낸
    물량이 2026-08 이후 상당하므로, **야드 품위를 맞출 때는 목적지로 골라야 한다** —
    출처로 고르면 그 물량이 통째로 반대쪽 야드에 매칭된다(§6-0-21).

    재고·물량 수지는 반대다: 재고는 **출처**에서 빠지므로 `line` 으로 골라야 한다.
    구 버전 데이터(목적지 컬럼 없음)는 `line` 으로 자동 대체한다.
    """
    col = DEST_LINE if DEST_LINE in osp_exp.columns else "line"
    return osp_exp[osp_exp[col] == line]


def osp_from_source(osp_exp: pd.DataFrame, line: str) -> pd.DataFrame:
    """그 OSP 에서 **빠져나간** 인출만 고른다 (출처 기준 — 재고·수지용)."""
    return osp_exp[osp_exp["line"] == line]


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
    """OSP 인출(예상 CaO 포함)을 시간창으로 집계.

    ⭐️ **시각을 모르는 행은 뺀다.** 엑셀에 날짜 없는 시각 셀은 1900 epoch 로 읽혀 그날 00:00
    이 되는데, 그 가짜 자정 물량(인출의 약 6%)이 Time-Lag 추정을 뒤집는다(신설 2h ↔ 11h).
    이 함수는 **시간창 집계 전용**이므로 여기서 걸러 모든 호출부가 일관되게 동작한다.
    물량 수지·재고 계산은 원본 `osp` 를 그대로 쓰므로 톤 합계에는 영향이 없다(§6-0-18).
    """
    df = osp_exp.dropna(subset=["datetime"]).copy()
    if "time_known" in df.columns:
        df = df[df["time_known"].fillna(True)]
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
# 4-b) 경로별 Time-Lag — 출처×목적지 조합마다 운반 시간이 다르다 (§6-0-21)
# --------------------------------------------------------------------------- #
#: 경로 lag 을 따로 추정하려면 그 경로에 최소한 이만큼의 겹친 시간 표본이 있어야 한다.
#: 표본이 적으면 상관 최대점이 노이즈를 좇으므로 주 경로 lag 으로 물러선다(§2-1).
MIN_ROUTE_SAMPLES = 30


@dataclass
class RouteLags:
    """한 야드로 들어오는 **경로별** Time-Lag.

    `lags[출처]` = 그 출처 OSP 에서 뽑아 이 야드에 닿기까지의 시간(시간).
    `base` 는 물량이 가장 많은 주 경로이며, `base_lag` 이 그 라인의 대표 lag 이다.
    """
    dest: str
    base: str
    base_lag: int
    lags: dict
    corr: dict
    ton: dict
    n: dict
    fallback: tuple = ()      # 표본 부족으로 주 경로 lag 을 빌려 쓴 출처들

    @property
    def is_multi(self) -> bool:
        return len({v for v in self.lags.values()}) > 1

    def summary(self) -> str:
        parts = [f"{src}→{self.dest} {lag}h" + ("*" if src in self.fallback else "")
                 for src, lag in sorted(self.lags.items(), key=lambda kv: -self.ton[kv[0]])]
        return " / ".join(parts)


def estimate_route_lags(osp_exp: pd.DataFrame, yard: pd.DataFrame, dest: str,
                        max_lag_hours: int = 24, freq: str = "1h") -> RouteLags:
    """이 야드로 들어오는 인출을 **출처별로 쪼개** 각각의 Time-Lag 을 추정한다.

    ⭐️ 왜 나눠야 하나: 같은 야드에 들어오는 물량이라도 **어느 OSP 에서 왔는지에 따라
       운반 시간이 다르다.** 실제로 신설 야드는 신설 OSP 에서 2시간, 기존 OSP(교차인출)에서
       10시간이 걸린다. 이 둘을 한 lag 으로 묶으면 서로를 흐려 상관이 +0.21 → +0.17 로
       떨어진다 — 경로를 나누면 교차인출 경로만은 상관이 +0.30 으로 가장 높다(§6-0-21).

    표본이 `MIN_ROUTE_SAMPLES` 미만인 경로는 추정하지 않고 주 경로 lag 을 쓴다.
    """
    yh = aggregate_yard_hourly(yard, freq=freq)
    d = osp_to_yard(osp_exp, dest)
    lags, corr, ton, nn = {}, {}, {}, {}
    for src in (S.LINE_OLD, S.LINE_NEW):
        part = d[d["line"] == src]
        t = float(pd.to_numeric(part["withdrawn_ton"], errors="coerce").sum())
        if not len(part) or t <= 0:
            continue
        oh = aggregate_osp_hourly(part, freq=freq)
        est = estimate_time_lag(oh, yh, max_lag_hours=max_lag_hours)
        n = int(est.curve.loc[est.curve["lag_hours"] == est.best_lag_hours, "n"].max())
        lags[src], corr[src], ton[src], nn[src] = est.best_lag_hours, est.best_corr, t, n
    if not lags:
        return RouteLags(dest, dest, 0, {}, {}, {}, {})
    base = max(ton, key=ton.get)                      # 물량이 가장 많은 경로가 그 라인의 대표
    fallback = tuple(s for s in lags if nn[s] < MIN_ROUTE_SAMPLES and s != base)
    for s in fallback:
        lags[s] = lags[base]
    return RouteLags(dest, base, int(lags[base]), lags, corr, ton, nn, fallback)


def align_routes(osp_exp: pd.DataFrame, dest: str, rl: RouteLags) -> pd.DataFrame:
    """경로별 lag 차이를 **인출 시각에 미리 반영**해 주 경로 기준으로 맞춘다.

    반환 프레임은 "주 경로에서 뽑았다면 언제였을 시각"으로 옮겨져 있으므로, 이후 단계는
    지금까지처럼 **단일 lag(`rl.base_lag`)** 만 다루면 된다 — 집계·피처·리포트의 계약이
    그대로 유지되면서 경로별 운반 시간차는 이미 보정된 상태가 된다.

    ⚠️ 옮기는 것은 `datetime` 뿐이다. 물량·품위·구역은 건드리지 않는다.
    """
    out = osp_to_yard(osp_exp, dest).copy()
    if not rl.lags or not rl.is_multi:
        return out
    shift = out["line"].map({s: rl.lags.get(s, rl.base_lag) - rl.base_lag for s in rl.lags})
    out["route_shift_h"] = shift.fillna(0).astype(float)
    out["datetime"] = out["datetime"] + pd.to_timedelta(out["route_shift_h"], unit="h")
    return out


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

def _weighted_daily(df: pd.DataFrame, keys: list[str], cols: list[str]) -> pd.DataFrame:
    """`cols` 를 `keys` 별 **톤가중 평균**으로 집계한다.

    물량이 없거나 합이 0 인 그룹은 단순평균으로 물러선다(가중치를 만들 수 없으므로).
    groupby.apply 대신 합계 연산으로 처리해 대용량에서도 빠르다.
    """
    d = df.copy()
    # 물량 컬럼이 아예 없는 입력(테스트·부분 데이터)에서는 균등 가중 = 단순평균으로 동작한다
    w = (pd.to_numeric(d["tonnage"], errors="coerce").fillna(0.0).clip(lower=0.0)
         if "tonnage" in d.columns else pd.Series(1.0, index=d.index))
    out = None
    for c in cols:
        v = pd.to_numeric(d[c], errors="coerce")
        ok = v.notna() & (w > 0)
        num = (v.where(ok, 0.0) * w.where(ok, 0.0)).groupby([d[k] for k in keys]).sum()
        den = w.where(ok, 0.0).groupby([d[k] for k in keys]).sum()
        plain = v.groupby([d[k] for k in keys]).mean()
        s = (num / den.replace(0, np.nan)).fillna(plain).rename(c)
        out = s.to_frame() if out is None else out.join(s, how="outer")
    return out.reset_index()


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
    # ⭐️ 톤가중 평균이어야 한다. 한 구역·하루에 여러 번 적재되면 인출 시 **톤 비율대로** 섞이므로,
    #    10,000톤 적재와 500톤 적재를 1:1 로 평균하면 소량 기록에 과도한 무게가 실린다.
    #    (실제로 구역-일 296건 중 26건이 0.3%p 이상, 최대 1.61%p 어긋났다 — §6-0-15)
    mine_daily = _weighted_daily(mine, ["line", "zone", "date"], have).sort_values("date")
    line_glob = _weighted_daily(mine, ["line"], have).set_index("line")

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
    """한 라인(기존/신설)의 OSP 피처를 해당 야드(목표)와 lag 정렬한 통합셋.

    ⭐️ 야드 목표에 맞추는 것이므로 **목적지 기준**으로 인출을 고른다(`osp_to_yard`).
    """
    osp_h = aggregate_osp_hourly(osp_to_yard(osp_exp, line), freq=freq)
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
