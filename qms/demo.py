"""데모 데이터 생성기.

실제 공장 데이터가 연결되기 전 시스템 시연·교육용으로 사용한다.
공정 간 인과관계(생료 → 소성 → 클링커 → 분쇄 → 강도)를 단순화한 모델로 시뮬레이션하며,
아래 이상 시나리오를 의도적으로 넣어 알림·원인진단 기능을 확인할 수 있게 했다.

| 코드 | 기간(일차)  | 시나리오 (원인 → 결과)                                                       |
|------|-------------|------------------------------------------------------------------------------|
| S1   | 40 ~ 46     | 석탄 발열량 저하 → 소성대 온도↓·CO↑ → f-CaO↑·C3S↓ → 28일 강도↓              |
| S6   | 50 ~ 56     | 석회석 백운석 혼입 → 생료·클링커 MgO↑ → 오토클레이브 팽창도↑                 |
| S2   | 62 ~ 67     | 석회석 품위 상승(채광 벤치 변경) + 조합 보정 지연 → 생료 LSF↑ → f-CaO↑        |
| S5   | 70 (1로트)  | 강도 양생수조 온도 이탈(17 ℃) → 해당 로트 28일 강도만 저하(시험오차)          |
| S4   | 88 ~ 90     | 석고 정량공급기 이상 → 시멘트 SO3↑(KS 3.5% 근접·초과) → 응결 지연·강도↓       |
| S3   | 100 ~ 105   | 세퍼레이터 회전수 저하 → 분말도↓·45μm 잔사↑ → 3·7일 강도↓ → 28일 예측 경보    |
| S7   | 108 ~ 112   | 철질원을 고Cr 제강슬래그 Lot로 대체 → 클링커 총Cr↑ → 시멘트 6가크롬 상승       |

XRD(일 1회 대표 시료)·크롬(클링커 총Cr·Cr⁶⁺, 시멘트 Cr⁶⁺)·생료 강열감량·석회석 혼합률은 별도 난수열(seed+101)로 생성해
기존 항목 값과 시나리오 재현성을 그대로 유지한다. XRD 광물량은 Bogue 계산값에 문헌상 경향
(알라이트는 Bogue보다 높고 벨라이트는 낮게 정량되는 경향)을 반영한 가정 오프셋을 더했다.

※ 모든 수치·계수는 시연용 가정값(추정)이며 실제 공장 특성과 다르다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import chemistry as chem

SCENARIOS = {
    "S1": {"days": (40, 46), "title": "석탄 발열량 저하 → 소성 부족(f-CaO↑, C3S↓) → 28일 강도 저하"},
    "S6": {"days": (50, 56), "title": "석회석 백운석 혼입 → MgO↑ → 오토클레이브 팽창도 상승"},
    "S2": {"days": (62, 67), "title": "석회석 품위 변화 + 조합 보정 지연 → 생료 LSF↑ → f-CaO↑"},
    "S5": {"days": (70, 70), "title": "양생수조 온도 이탈 → 단일 로트 28일 강도 저하(시험오차)"},
    "S4": {"days": (88, 90), "title": "석고 정량공급기 이상 → 시멘트 SO3 과다 → 응결 지연"},
    "S3": {"days": (100, 105), "title": "세퍼레이터 이상 → 분말도 저하 → 조기강도↓·28일 예측 경보"},
    "S7": {"days": (108, 112), "title": "철질원 대체(고Cr 제강슬래그 Lot) → 클링커 총Cr↑ → 시멘트 6가크롬 상승"},
}

ASH = {"sio2": 55.0, "al2o3": 25.0, "fe2o3": 7.0, "cao": 5.0, "mgo": 1.5}


def _ar1(n: int, phi: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """정상(stationary) AR(1) 잡음. 주변분포 표준편차 = sigma."""
    e = rng.normal(0.0, sigma * np.sqrt(1 - phi ** 2), n)
    x = np.empty(n)
    x[0] = rng.normal(0.0, sigma)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def _bump(t: np.ndarray, start: float, end: float, magnitude: float, ramp: float = 0.6) -> np.ndarray:
    """사다리꼴 형태의 이상 프로파일. t 단위 = 일(day)."""
    up = np.clip((t - start) / ramp, 0, 1)
    down = np.clip((end + 1 - t) / ramp, 0, 1)
    return magnitude * np.minimum(up, down)


def _scn(name: str) -> tuple[float, float]:
    return SCENARIOS[name]["days"]


def product_for_day(day: int) -> str:
    """시멘트밀 생산 품종 계획: 15일 주기 중 2일간 3종 캠페인."""
    return "3종" if day % 15 in (7, 8) else "1종"


def generate_demo_data(end: date | None = None, days: int = 120, seed: int = 7) -> dict[str, pd.DataFrame]:
    """공정·품질 데모 데이터 생성. 반환: {테이블명: DataFrame} (산화물 원값, 파생값은 store에서 계산)."""
    rng = np.random.default_rng(seed)
    end = end or date.today()
    start = datetime.combine(end - timedelta(days=days - 1), datetime.min.time())

    # ── 킬른 DCS (1시간) ────────────────────────────────────────────────
    th = np.arange(days * 24) / 24.0
    n = len(th)
    s1a, s1b = _scn("S1")
    kiln = pd.DataFrame({"timestamp": [start + timedelta(hours=h) for h in range(n)]})
    kiln["kiln_feed"] = 335 + _ar1(n, 0.7, 2.0, rng)
    kiln["coal_rate"] = 25.5 + _ar1(n, 0.7, 0.25, rng) + _bump(th, s1a, s1b, 0.8)
    kiln["kiln_bzt"] = 1420 + _ar1(n, 0.8, 5.0, rng) + _bump(th, s1a, s1b, -45)
    kiln["kiln_o2"] = 3.0 + _ar1(n, 0.7, 0.25, rng) + _bump(th, s1a, s1b, -0.8)
    co_spike = _bump(th, s1a, s1b, 0.22) * (1 + 0.6 * rng.random(n))
    kiln["kiln_co"] = np.clip(0.04 * np.exp(_ar1(n, 0.6, 0.35, rng)) + co_spike, 0.005, None)
    kiln["kiln_torque"] = 80 + _ar1(n, 0.85, 1.5, rng) + _bump(th, s1a, s1b, -5)
    kiln["kiln_calc_temp"] = 875 + _ar1(n, 0.7, 4.0, rng)
    kiln["kiln_sec_air"] = 1050 + _ar1(n, 0.8, 15.0, rng) + _bump(th, s1a, s1b, -60)

    # ── 생료 (2시간) ───────────────────────────────────────────────────
    t2 = np.arange(days * 12) / 12.0
    m = len(t2)
    ts2 = [start + timedelta(hours=2 * i) for i in range(m)]
    s2a, s2b = _scn("S2")
    s6a, s6b = _scn("S6")
    rm = pd.DataFrame({"timestamp": ts2})
    rm["rm_cao"] = 43.2 + _ar1(m, 0.6, 0.12, rng) + _bump(t2, s2a, s2b, 1.05, ramp=1.0)
    rm["rm_sio2"] = 13.7 + _ar1(m, 0.5, 0.06, rng)
    rm["rm_al2o3"] = 3.30 + _ar1(m, 0.5, 0.03, rng)
    rm["rm_fe2o3"] = 2.10 + _ar1(m, 0.5, 0.025, rng)
    rm["rm_mgo"] = 1.65 + _ar1(m, 0.6, 0.06, rng) + _bump(t2, s6a, s6b, 1.2, ramp=1.0)
    rm["rm_so3"] = 0.25 + _ar1(m, 0.4, 0.03, rng)
    rm["rm_k2o"] = 0.55 + _ar1(m, 0.4, 0.02, rng)
    rm["rm_na2o"] = 0.12 + _ar1(m, 0.4, 0.01, rng)
    rm["rm_r90"] = 13.0 + _ar1(m, 0.6, 0.8, rng)
    rm["rm_r200"] = np.clip(1.0 + _ar1(m, 0.5, 0.12, rng), 0.2, None)

    # ── 클링커 (2시간, 생료 2시간 지연 + 석탄회 흡수) ─────────────────────
    kiln2 = kiln.set_index("timestamp").resample("2h").mean().reindex(ts2).ffill()
    lag = rm.shift(1).bfill()
    loi = lag["rm_cao"] * 0.785 + lag["rm_mgo"] * 1.092 + 0.6
    factor = 1.0 / (1.0 - loi / 100.0)
    ash = 0.015 * (kiln2["coal_rate"].to_numpy() / 25.5)
    clk = pd.DataFrame({"timestamp": ts2})
    xrf_noise = {"cao": 0.10, "sio2": 0.05, "al2o3": 0.03, "fe2o3": 0.02, "mgo": 0.04}
    for ox in ("cao", "sio2", "al2o3", "fe2o3", "mgo"):
        burnt = lag[f"rm_{ox}"].to_numpy() * factor.to_numpy()
        clk[f"clk_{ox}"] = (1 - ash) * burnt + ash * ASH[ox] + rng.normal(0, xrf_noise[ox], m)
    clk["clk_so3"] = np.clip(lag["rm_so3"].to_numpy() * factor.to_numpy() * 0.6 + 0.45
                             + _ar1(m, 0.4, 0.06, rng) + _bump(t2, s1a, s1b, -0.12), 0.1, None)
    clk["clk_k2o"] = lag["rm_k2o"].to_numpy() * factor.to_numpy() * 0.93 + rng.normal(0, 0.02, m)
    clk["clk_na2o"] = lag["rm_na2o"].to_numpy() * factor.to_numpy() * 0.95 + rng.normal(0, 0.01, m)

    cao, sio2 = clk["clk_cao"], clk["clk_sio2"]
    al2o3, fe2o3 = clk["clk_al2o3"], clk["clk_fe2o3"]
    lsf_clk = 100 * cao / (2.8 * sio2 + 1.18 * al2o3 + 0.65 * fe2o3)
    sm_clk = sio2 / (al2o3 + fe2o3)
    bzt = kiln2["kiln_bzt"].to_numpy()
    co = kiln2["kiln_co"].to_numpy()
    r90 = lag["rm_r90"].to_numpy()
    fcao = (1.0 + 0.32 * (lsf_clk - 95.0) + 0.7 * (sm_clk - 2.5) + 0.07 * (r90 - 13.0)
            - 0.028 * (bzt - 1420) + 0.8 * np.clip(co - 0.1, 0, None) + _ar1(m, 0.4, 0.10, rng))
    clk["clk_fcao"] = np.clip(fcao, 0.25, 4.5)
    clk["clk_lw"] = 1300 + 1.8 * (bzt - 1420) - 12 * (lsf_clk - 95.0) + _ar1(m, 0.3, 14, rng)

    # 클링커 일평균(시멘트 강도 모델 입력, 클링커 사일로 체류 1~2일 가정)
    clk_tmp = clk.copy()
    clk_tmp["lsf"] = lsf_clk
    c3s = (4.071 * (cao - clk["clk_fcao"]) - 7.600 * sio2 - 6.718 * al2o3 - 1.430 * fe2o3
           - 2.852 * clk["clk_so3"])
    clk_tmp["c3s"] = c3s
    daily_clk = clk_tmp.set_index("timestamp").resample("1D").mean()
    used_clk = daily_clk.shift(1).rolling(2, min_periods=1).mean().bfill()

    # ── 시멘트 (2시간, 품종별) ─────────────────────────────────────────
    s3a, s3b = _scn("S3")
    s4a, s4b = _scn("S4")
    day_idx = (t2 // 1).astype(int)
    products = np.array([product_for_day(d) for d in day_idx])
    is3 = products == "3종"
    cem = pd.DataFrame({"timestamp": ts2, "product": products})
    blaine_dev = _ar1(m, 0.6, 35, rng)
    cem["cem_blaine"] = np.where(is3, 4600 + blaine_dev * 1.3, 3450 + blaine_dev + _bump(t2, s3a, s3b, -450, 0.8))
    cem["cem_r45"] = np.where(
        is3, 3.0 - 0.004 * (cem["cem_blaine"] - 4600) + _ar1(m, 0.5, 0.3, rng),
        9.5 - 0.008 * (cem["cem_blaine"] - 3450) + _ar1(m, 0.5, 0.5, rng) + _bump(t2, s3a, s3b, 1.5, 0.8))
    so3_noise = _ar1(m, 0.5, 0.07, rng)
    cem["cem_so3"] = np.where(is3, 3.20 + so3_noise, 2.60 + so3_noise + _bump(t2, s4a, s4b, 0.78, 0.4))
    loi_noise = _ar1(m, 0.5, 0.10, rng)
    cem["cem_loi"] = np.where(is3, 2.00 + 0.8 * loi_noise, 2.80 + loi_noise)
    clk_mgo_used = used_clk["clk_mgo"].reindex(pd.to_datetime([t.date() for t in ts2])).to_numpy()
    cem["cem_mgo"] = 0.93 * clk_mgo_used + 0.15 + rng.normal(0, 0.05, m)
    cem["cem_mill_feed"] = np.where(is3, 128 + _ar1(m, 0.7, 2.0, rng), 180 + _ar1(m, 0.7, 2.5, rng))
    cem["cem_mill_temp"] = 105 + _ar1(m, 0.7, 3.0, rng)

    # ── 물성·강도 (일 1로트, 품종별) ──────────────────────────────────
    daily_cem = cem.set_index("timestamp").resample("1D").agg(
        {"product": "first", "cem_blaine": "mean", "cem_so3": "mean", "cem_loi": "mean", "cem_mgo": "mean"})
    rows = []
    last_day = days - 1
    s5_day = _scn("S5")[0]
    for d, (day_ts, row) in enumerate(daily_cem.iterrows()):
        prod = row["product"]
        c3s_l = used_clk["c3s"].iloc[d]
        fcao_l = used_clk["clk_fcao"].iloc[d]
        blaine, so3, loi_c, mgo_c = row["cem_blaine"], row["cem_so3"], row["cem_loi"], row["cem_mgo"]
        lot = rng.normal(0, 0.5)
        if prod == "1종":
            fine = blaine - 3450
            so3d = so3 - 2.60
            s28 = (53.0 + 0.35 * (c3s_l - 57.5) + 0.010 * fine - 2.5 * so3d ** 2 - 0.9 * (loi_c - 2.8)
                   - 1.2 * max(fcao_l - 1.3, 0) + lot + rng.normal(0, 0.8))
            s7 = (40.0 + 0.26 * (c3s_l - 57.5) + 0.012 * fine - 2.0 * so3d ** 2 - 0.6 * (loi_c - 2.8)
                  - 0.9 * max(fcao_l - 1.3, 0) + 0.8 * lot + rng.normal(0, 0.7))
            s3 = (29.5 + 0.20 * (c3s_l - 57.5) + 0.013 * fine - 1.5 * so3d ** 2
                  - 0.7 * max(fcao_l - 1.3, 0) + 0.6 * lot + rng.normal(0, 0.6))
            s1 = np.nan
            ist = 220 + 55 * so3d - 0.06 * fine + rng.normal(0, 12)
            fst = ist + 80 + rng.normal(0, 10)
        else:
            fine = blaine - 4600
            so3d = so3 - 3.20
            s28 = (59.0 + 0.30 * (c3s_l - 57.5) + 0.006 * fine - 2.5 * so3d ** 2 - 0.9 * (loi_c - 2.0)
                   - 1.2 * max(fcao_l - 1.3, 0) + lot + rng.normal(0, 0.8))
            s7 = 46.0 + 0.24 * (c3s_l - 57.5) + 0.0075 * fine - 2.0 * so3d ** 2 + 0.8 * lot + rng.normal(0, 0.7)
            s3 = 37.0 + 0.18 * (c3s_l - 57.5) + 0.008 * fine - 1.5 * so3d ** 2 + 0.6 * lot + rng.normal(0, 0.7)
            s1 = 20.0 + 0.12 * (c3s_l - 57.5) + 0.006 * fine + 0.5 * lot + rng.normal(0, 0.6)
            ist = 180 + 50 * so3d - 0.05 * fine + rng.normal(0, 10)
            fst = ist + 70 + rng.normal(0, 9)
        cure = 20.0 + rng.normal(0, 0.25)
        if d == s5_day:
            cure = 17.0
            s28 -= 5.5
        autoclave = max(0.08 + 0.20 * max(mgo_c - 3.0, 0) + 0.04 * max(fcao_l - 1.5, 0) + rng.normal(0, 0.02), 0.01)
        rec = {
            "timestamp": day_ts + timedelta(hours=12), "product": prod,
            "phy_ist": ist, "phy_fst": fst, "phy_autoclave": autoclave,
            "phy_s1": s1, "phy_s3": s3, "phy_s7": s7, "phy_s28": s28,
            "lab_temp": 20 + rng.normal(0, 0.5), "lab_rh": 60 + rng.normal(0, 4), "lab_cure_temp": cure,
            "sand_lot": f"ISO-{day_ts.year}-{d // 30 + 1:02d}", "operator": "ABC"[d % 3] + "조",
        }
        # 시험 재령 미도래 → 결과 없음
        for age, col in ((1, "phy_s1"), (3, "phy_s3"), (7, "phy_s7"), (28, "phy_s28")):
            if d + age > last_day:
                rec[col] = np.nan
        if d + 1 > last_day:
            rec["phy_autoclave"] = np.nan
        rows.append(rec)
    phy = pd.DataFrame(rows)

    def _round(df: pd.DataFrame, nd: int = 3) -> pd.DataFrame:
        num = df.select_dtypes("number").columns
        df[num] = df[num].round(nd)
        return df

    # ── 추가 항목(별도 난수열: 위 항목 값은 바뀌지 않음) ────────────────
    rng2 = np.random.default_rng(seed + 101)
    rm["rm_loi"] = rm["rm_cao"] * 0.785 + rm["rm_mgo"] * 1.092 + 0.6 + rng2.normal(0, 0.08, m)
    ls_base = np.where(is3, 1.37, 1.10)     # 석고 결정수·클링커 강열감량분(가정)
    cem.insert(cem.columns.get_loc("cem_mgo") + 1, "cem_ls",
               np.clip((cem["cem_loi"] - ls_base) / 0.42 + rng2.normal(0, 0.12, m), 0.0, 6.0))
    xrd = _xrd_daily(clk, rng2, days)
    _add_chromium(xrd, phy, cem, kiln, clk, rng2, days)

    return {
        "raw_meal": _round(rm),
        "kiln": _round(kiln),
        "clinker": _round(clk),
        "cement": _round(cem),
        "physical": _round(phy),
        "xrd": _round(xrd),
    }


def _add_chromium(xrd: pd.DataFrame, phy: pd.DataFrame, cem: pd.DataFrame, kiln: pd.DataFrame, clk: pd.DataFrame,
                  rng: np.random.Generator, days: int) -> None:
    """크롬 데이터(가정 모델). 전환율 = 12% × (1 + 0.20·(O₂ − 3)) × (1 + 1.2·(Na₂Oeq − 0.70)) — 산화 분위기·알칼리↑ 시 증가.

    시멘트 제품 Cr⁶⁺ = (클링커 비율 × 사용 클링커 Cr⁶⁺ + 0.2) − 환원제 능력(약 3 mg/kg) + 오차.
    """
    n = len(xrd)
    t = np.arange(n, dtype=float)
    s7a, s7b = _scn("S7")
    total = 65 + _ar1(n, 0.6, 5.0, rng) + _bump(t, s7a, s7b, 150, ramp=0.8)
    day = pd.DatetimeIndex(xrd["timestamp"]).normalize()
    o2 = kiln.set_index("timestamp")["kiln_o2"].resample("1D").mean().reindex(day).to_numpy()
    na2oeq = (clk["clk_na2o"] + 0.658 * clk["clk_k2o"]).groupby(clk["timestamp"].dt.normalize()).mean().reindex(day).to_numpy()
    conv = 0.12 * (1 + 0.20 * (o2 - 3.0)) * (1 + 1.2 * (na2oeq - 0.70)) * np.exp(rng.normal(0, 0.08, n))
    xrd["clk_cr"] = np.clip(total, 10, None)
    xrd["clk_crvi"] = np.clip(xrd["clk_cr"] * conv + rng.normal(0, 0.3, n), 0.2, None)
    crvi_daily = pd.Series(xrd["clk_crvi"].to_numpy(), index=day)
    full = pd.date_range(day.min() - pd.Timedelta(days=2), day.max() + pd.Timedelta(days=2), freq="1D")
    used = crvi_daily.reindex(full).shift(1).rolling(2, min_periods=1).mean()
    ls_daily = cem.set_index("timestamp")["cem_ls"].resample("1D").mean()
    lot_day = phy["timestamp"].dt.normalize()
    cf = 1 - ls_daily.reindex(lot_day).to_numpy() / 100 - 0.05            # 클링커 비율(석고 약 5% 가정)
    before = cf * used.reindex(lot_day).to_numpy() + 0.2                 # 분쇄매체 기여 약 0.2(가정)
    after = np.clip(before - 3.0 + rng.normal(0, 0.6, len(phy)), 0.3, None)
    after = np.where(np.arange(len(phy)) + 1 > days - 1, np.nan, after)   # 결과 익일 확정
    phy.insert(phy.columns.get_loc("phy_s28") + 1, "phy_crvi", after)


def _xrd_daily(clk: pd.DataFrame, rng: np.random.Generator, days: int) -> pd.DataFrame:
    """일 대표 클링커 시료의 XRD-Rietveld 정량값(가정 모델). 당일 결과는 익일 확정 → 마지막 날 제외."""
    ph = chem.bogue(clk["clk_cao"], clk["clk_sio2"], clk["clk_al2o3"], clk["clk_fe2o3"], clk["clk_so3"],
                    clk["clk_fcao"])
    d = pd.DataFrame({"timestamp": clk["timestamp"], "c3s": ph["C3S"], "c2s": ph["C2S"], "c3a": ph["C3A"],
                      "c4af": ph["C4AF"], "fcao": clk["clk_fcao"], "mgo": clk["clk_mgo"]})
    daily = d.set_index("timestamp").resample("1D").mean().iloc[: max(days - 1, 0)]
    n = len(daily)
    return pd.DataFrame({
        "timestamp": daily.index + pd.Timedelta(hours=8),
        "xrd_alite": daily["c3s"].to_numpy() + 6.5 + rng.normal(0, 1.2, n),
        "xrd_belite": np.clip(daily["c2s"].to_numpy() - 5.5 + rng.normal(0, 1.0, n), 1.0, None),
        "xrd_c3a": np.clip(daily["c3a"].to_numpy() - 1.2 + rng.normal(0, 0.5, n), 0.5, None),
        "xrd_c4af": daily["c4af"].to_numpy() + 0.8 + rng.normal(0, 0.5, n),
        "xrd_fcao": np.clip(0.9 * daily["fcao"].to_numpy() + rng.normal(0, 0.12, n), 0.05, None),
        "xrd_periclase": np.clip(np.maximum(daily["mgo"].to_numpy() - 1.6, 0.1) + rng.normal(0, 0.15, n), 0.05, None),
    })


def scenario_table(start: date) -> pd.DataFrame:
    """시나리오 일정(실제 날짜)."""
    rows = []
    for code, info in SCENARIOS.items():
        a, b = info["days"]
        rows.append({"코드": code, "시작일": start + timedelta(days=a), "종료일": start + timedelta(days=b),
                     "내용": info["title"]})
    return pd.DataFrame(rows)
