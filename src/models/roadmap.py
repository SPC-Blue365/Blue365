"""배합 최적화 로드맵 준비도 [ML-Engineer].

"데이터가 얼마나 더 모이면 배합 최적화를 할 수 있나?" 에 **데이터로** 답한다.

요건은 두 갈래이고, 성격이 전혀 다르다.

  A. **검증 사례** — "이렇게 뽑았더니 야드가 이랬다" 사례(야드변경 구간) 수.
     구역 조합 → 야드품위 관계를 회귀로 확인하려면 사례가 주요 구역 수의 10배는 필요하다.
     → **시간이 해결한다.** 현재 속도로 몇 개월 뒤 충족되는지 계산할 수 있다.

  B. **구역 품위 정밀도** — 배합은 "각 구역이 몇 % 인지" 를 알아야 계산된다.
     지금은 구역 평균의 표준오차가 목표 허용폭(±0.5%p)보다 크다.
     → **시간이 해결하지 못한다.** 같은 구역 안에서도 품위 산포가 커서,
       표본을 늘리면 '평균'만 정밀해질 뿐 인출 시점의 실제 품위는 여전히 흔들린다.
       인출 지점 실측(분석기) 같은 **새 계측**이 있어야 한다.

지어내지 않고, 두 갈래를 나눠 현재 위치와 남은 거리를 그대로 보고한다(CLAUDE.md §2-1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import schema as S

#: 회귀로 관계를 확인하려면 사례 수가 설명변수 수의 몇 배여야 하는지 (통상 권장치)
CASES_PER_ZONE = 10
#: 물량 기준 이 비율 이상인 구역만 '주요 구역'으로 본다 (꼬리 구역은 배합에서 미미)
MAJOR_ZONE_TON_SHARE = 0.01
#: 구역 평균을 이 정밀도(표준오차)로 알아야 ±0.5%p 배합이 의미를 갖는다
TARGET_ZONE_SE = 0.1


def zone_precision(mine: pd.DataFrame) -> dict:
    """구역별 품위 표본 현황과 평균의 불확실성 (갈래 B)."""
    empty = dict(n_zones=0, n_major=0, n_obs=0, se_median=np.nan, se_max=np.nan,
                 need_per_zone=np.nan, obs_median=np.nan, ratio=np.nan)
    if mine is None or not len(mine):
        return empty
    z = mine.dropna(subset=["zone", "cao"])
    if not len(z):
        return empty
    g = z.groupby("zone").agg(n=("cao", "size"), sd=("cao", "std"),
                              ton=("tonnage", "sum"))
    g = g[g["n"] >= 2]
    if not len(g):
        return empty
    major = g[g["ton"] > g["ton"].sum() * MAJOR_ZONE_TON_SHARE]
    if not len(major):
        major = g
    se = major["sd"] / np.sqrt(major["n"])
    need = float((major["sd"].median() / TARGET_ZONE_SE) ** 2)
    return dict(
        n_zones=int(len(g)), n_major=int(len(major)), n_obs=int(len(z)),
        se_median=float(se.median()), se_max=float(se.max()),
        need_per_zone=need, obs_median=float(major["n"].median()),
        ratio=float(need / max(major["n"].median(), 1)),
    )


def case_readiness(yc: pd.DataFrame, n_major: int) -> dict:
    """검증 사례(야드변경 구간) 축적 현황과 충족 시점 (갈래 A)."""
    empty = dict(have=0, need=0, remain=0, per_month=np.nan, months=np.nan, ready=False)
    if yc is None or not len(yc) or n_major <= 0:
        return empty
    t = pd.to_datetime(yc["datetime"], errors="coerce").dropna()
    if len(t) < 2:
        return empty
    days = max((t.max() - t.min()).days, 1)
    per_month = len(t) / days * 30
    need = n_major * CASES_PER_ZONE
    remain = max(need - len(t), 0)
    return dict(
        have=int(len(t)), need=int(need), remain=int(remain),
        per_month=float(per_month),
        months=float(remain / per_month) if per_month > 0 else np.nan,
        ready=bool(remain == 0),
        since=t.min(), until=t.max(),
    )


def readiness(mine: pd.DataFrame, yc: pd.DataFrame) -> dict:
    """로드맵 준비도 종합. `ready` 가 True 가 되면 알림 대상이다."""
    zp = zone_precision(mine)
    cr = case_readiness(yc, zp.get("n_major", 0))
    # 갈래 B 는 표본을 늘려 닿을 수 있는 거리인지 함께 판정한다
    se_ok = bool(np.isfinite(zp.get("se_median", np.nan))
                 and zp["se_median"] <= S.TARGET.tol)
    return dict(zone=zp, cases=cr, se_ok=se_ok,
                ready=bool(cr.get("ready") and se_ok))


def summary_text(r: dict) -> str:
    """사람이 읽는 한 줄 요약 (콘솔·리포트 공용)."""
    c, z = r["cases"], r["zone"]
    if r["ready"]:
        return ("✅ 배합 최적화 착수 조건 충족 — 검증 사례 "
                f"{c['have']}/{c['need']}건, 구역 평균 오차 {z['se_median']:.2f}%p")
    def _ok(v):
        return v == v and np.isfinite(v)      # NaN·inf 방어

    if not z.get("n_obs"):
        return "⏳ 판정 불가 — 구역 품위 데이터가 없습니다."
    bits = []
    if not c.get("ready"):
        span = (f" (월 {c['per_month']:.0f}건 → 약 {c['months']:.1f}개월 남음)"
                if _ok(c.get("per_month", np.nan)) and _ok(c.get("months", np.nan)) else "")
        bits.append(f"검증 사례 {c['have']}/{c['need']}건{span}")
    if not r["se_ok"] and _ok(z.get("se_median", np.nan)):
        more = (f" (표본으로 낮추려면 구역당 {z['need_per_zone']:.0f}건, 현재 "
                f"{z['obs_median']:.0f}건 → {z['ratio']:.0f}배)"
                if _ok(z.get("need_per_zone", np.nan)) and _ok(z.get("obs_median", np.nan))
                else "")
        bits.append(f"구역 평균 오차 {z['se_median']:.2f}%p > 허용폭 {S.TARGET.tol}%p{more}")
    return "⏳ 아직 이릅니다 — " + (" / ".join(bits) if bits else "요건 확인 중")
