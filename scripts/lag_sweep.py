"""경로 운반 시간(Time-Lag) 민감도 분석 [ML-Engineer].

질문(2026-11-23 사용자): "현장확정시간을 얼마로 지연 적용해야 데이터상 상관계수가, 정확도가
증가할까?" — 한 경로(기본: 기존 OSP → 45Q 야드)에 대해 지연을 0~N 시간으로 바꿔 가며

  ① 상관(OSP 예상 CaO ↔ 야드 CaO)과 겹친 표본 수
  ② 상관의 95% 구간 — **날짜 블록 부트스트랩**(같은 날 시간끼리는 붙어 다니므로 날 단위로 뽑는다)
  ③ 안정성 — 기간을 앞·뒤 절반으로 나눠 **두 절반에서 모두** 같은 방향인지
  ④ ⭐️ 정확도 — 그 지연의 상류 피처를 넣은 예측 모델의 **시계열 교차검증 MAE**
     (현재 확정 모델 = 상류 없이 AR 만 쓰는 Ridge 와 비교)

를 표로 낸다. 상관이 가장 높은 지연이 곧 정확도를 올리는 지연은 아니다 — ④가 판정 기준이다.

실행: python scripts/lag_sweep.py [--src 기존 --dest 기존 --max 36 --boot 400]
산출: outputs/lag_sweep_<src>_<dest>.csv  (데이터 파생물 — git 커밋 금지, §6.1)
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from config import paths as P                       # noqa: E402
from config import schema as S                      # noqa: E402
from src.matching import pipeline as MP             # noqa: E402
from src.models import forecast as F                # noqa: E402
from src.models.dataset import load_sources         # noqa: E402


def _series(osp, yards, src, dest):
    """(야드 시간별 CaO, 그 경로 OSP 시간 집계[impl, ton])."""
    y = yards[dest].dropna(subset=["datetime"]).copy()
    ys = y.groupby(y["datetime"].dt.floor("1h"))["cao"].mean().asfreq("1h")
    o = MP.osp_to_yard(osp, dest)                         # 목적지 기준 — L-Slag 등은 이미 빠져 있다
    o = o[(o["line"] == src)].dropna(subset=["datetime"])
    if "time_known" in o.columns:                          # 시각 미상(가짜 자정) 행은 시간축에서 뺀다
        o = o[o["time_known"].fillna(True)]
    oh = o.groupby(o["datetime"].dt.floor("1h")).agg(
        impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))
    return ys, oh


def _corr(a, b):
    m = a.notna() & b.notna()
    return (float(a[m].corr(b[m])) if m.sum() >= 10 else np.nan), int(m.sum())


def sweep(src=S.LINE_OLD, dest=S.LINE_OLD, max_lag=36, n_boot=400, seed=0) -> pd.DataFrame:
    _, osp, yards = load_sources(verbose=False)
    ys, oh = _series(osp, yards, src, dest)
    idx = ys.index.union(oh.index)
    a, b = oh["impl"].reindex(idx), ys.reindex(idx)
    mid = idx.min() + (idx.max() - idx.min()) / 2
    rng = np.random.default_rng(seed)

    base = F.evaluate(F.build_features(ys, oh, 0), use_upstream=False)   # 현재 확정 모델(AR 만)
    rows = []
    for L in range(max_lag + 1):
        sa = a.shift(L)
        r, n = _corr(sa, b)
        m = sa.notna() & b.notna()
        pair = pd.DataFrame({"x": sa[m], "y": b[m]})
        days = pair.index.floor("D")
        ud = days.unique()
        bs = []
        if len(ud) >= 5:
            for _ in range(n_boot):
                pick = rng.choice(ud, len(ud), replace=True)
                s = pd.concat([pair[days == d] for d in pick])
                if len(s) >= 10 and s["x"].std() > 0 and s["y"].std() > 0:
                    bs.append(s["x"].corr(s["y"]))
        lo, hi = (np.percentile(bs, [2.5, 97.5]) if len(bs) >= 50 else (np.nan, np.nan))
        r1, n1 = _corr(sa[sa.index < mid], b[b.index < mid])
        r2, n2 = _corr(sa[sa.index >= mid], b[b.index >= mid])
        try:
            up = F.evaluate(F.build_features(ys, oh, L), use_upstream=True)
            mae, dmae = up.mae, up.mae - base.mae
        except Exception:                                   # 표본 부족 — 지어내지 않는다
            mae = dmae = np.nan
        rows.append(dict(lag_h=L, corr=r, n=n, ci_lo=lo, ci_hi=hi, n_days=len(ud),
                         corr_first=r1, n_first=n1, corr_second=r2, n_second=n2,
                         mae_with_upstream=mae, mae_ar_only=base.mae, d_mae=dmae))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=S.LINE_OLD)
    ap.add_argument("--dest", default=S.LINE_OLD)
    ap.add_argument("--max", type=int, default=36)
    ap.add_argument("--boot", type=int, default=400)
    a = ap.parse_args()
    df = sweep(a.src, a.dest, a.max, a.boot)
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = P.OUTPUTS_DIR / f"lag_sweep_{a.src}_{a.dest}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    fixed = S.ROUTE_LAG_FIXED.get((a.src, a.dest))
    pd.set_option("display.width", 200)
    print(df.round(3).to_string(index=False))
    print(f"\n[OK] {out}  (현장 확정값: {fixed}h)")


if __name__ == "__main__":
    main()
