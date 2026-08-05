"""공용 데이터셋 로더 (정제→매칭→라인별 피처) [ML-Engineer].

여러 스크립트(학습·모니터·리포트)가 동일한 피처를 재사용하도록 한 곳에 모은다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import schema as S
from config.paths import RAW_DIR
from src.data import clean as C
from src.data import validation as V
from src.matching import pipeline as P
from src.models import forecast as F


@dataclass
class LineData:
    line: str
    alias: str
    yard_series: pd.Series      # 시간별 야드 CaO (asfreq 1h)
    osp_hourly: pd.DataFrame    # index=시간, [impl, ton]
    lag_hours: int
    features: pd.DataFrame      # 예측 피처 프레임
    lag_corr: float = float("nan")   # 그 lag 에서의 상류-야드 상관 (매칭 파이프라인과 동일 값)


def load_sources(raw_file: str | None = None, validate: bool = True, verbose: bool = True):
    """원시 엑셀 → (mine, osp_exp, yards dict). 재사용 기본 로더.

    validate=True 이면 매칭 전에 검증 게이트를 실행한다 (CLAUDE.md §3).
    결과는 last_validation_reports 로 조회 가능하며, 이상은 verbose 로 보고한다.
    """
    xls = pd.ExcelFile(RAW_DIR / (raw_file or S.DATA_FILE))
    mine = pd.concat(
        [C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q)),
         C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q))],
        ignore_index=True,
    )
    osp = pd.concat(
        [C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
         C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW)],
        ignore_index=True,
    )
    yards = {ln: C.clean_yard(pd.read_excel(xls, sh)) for ln, (sh, _) in S.YARD_PAIR.items()}

    # ⭐️ 검증 게이트: 매칭(조인) '전에' 무결성 검사 (CLAUDE.md §3)
    if validate:
        yc = None
        for sheet, line in [(S.SHEET_YC_OLD, S.LINE_OLD), (S.SHEET_YC_NEW, S.LINE_NEW)]:
            if sheet in xls.sheet_names:
                part = C.clean_yard_change(pd.read_excel(xls, sheet), line)
                yc = part if yc is None else pd.concat([yc, part], ignore_index=True)
        reports = V.validate_pipeline(mine, osp, yards, yc)
        # OSP 실사 재고: 값 범위·중복만 가볍게 점검 (품위 컬럼이 없어 기존 스펙과 별개)
        if S.SHEET_OSP_STOCK in xls.sheet_names:
            stk = C.clean_osp_stock(pd.read_excel(xls, S.SHEET_OSP_STOCK, header=None))
            issues = []
            neg = int((pd.to_numeric(stk["stock_ton"], errors="coerce") < 0).sum())
            if neg:
                issues.append(V.Issue("stock_negative", V.Severity.ERROR,
                                      "재고량이 음수입니다", neg))
            na = int(stk["stock_ton"].isna().sum())
            if na:
                issues.append(V.Issue("stock_missing", V.Severity.WARNING,
                                      "재고량 결측 (최근 실사 미입력 가능)", na))
            if stk.attrs.get("dup_dropped"):
                issues.append(V.Issue("stock_duplicate", V.Severity.WARNING,
                                      "날짜+차수 중복 — 마지막 기록을 채택했습니다",
                                      stk.attrs["dup_dropped"]))
            reports["OSP재고"] = V.ValidationReport(
                source="OSP재고", n_rows=len(stk), issues=issues)
        # ⭐️ 생산능력(C/R) 상한 감사 — 상한 초과 기록은 물리적으로 불가능하다.
        try:
            au = capacity_audit(mine)
            if len(au) and bool(au["over"].any()):
                bad = au[au["over"]]
                reports["광산"].issues.append(V.Issue(
                    "capacity_over", V.Severity.ERROR,
                    f"생산능력 상한 초과 — 최대 {bad['tph'].max():,.0f} t/h "
                    f"(상한 {bad['cap_hi'].max():,.0f}). 기록 오류 후보입니다", len(bad)))
        except Exception as exc:                      # 감사 실패가 파이프라인을 막지 않게
            reports["광산"].issues.append(V.Issue(
                "capacity_audit_failed", V.Severity.WARNING, f"능력 감사 실행 실패: {exc}"))
        globals()["last_validation_reports"] = reports
        if verbose:
            n_err = sum(len(r.errors) for r in reports.values())
            if n_err or any(r.warnings for r in reports.values()):
                print(V.summarize_reports(reports))

    osp_exp = P.assign_expected_cao_timeaware(osp, mine)
    return mine, osp_exp, yards


# 마지막 검증 결과 (load_sources 실행 후 조회용)
last_validation_reports: dict = {}


def build_line_data(osp_exp, yards, line: str) -> LineData:
    """한 라인의 야드 시계열·OSP집계·Time-Lag·피처를 구성."""
    alias = S.YARD_PAIR[line][1]
    y = yards[line].dropna(subset=["datetime"]).copy()
    y["h"] = y["datetime"].dt.floor("1h")
    ys = y.groupby("h")["cao"].mean().asfreq("1h")
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["datetime"]).copy()
    o["h"] = o["datetime"].dt.floor("1h")
    oh = o.groupby("h").agg(impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))
    est = P.estimate_time_lag(
        oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
        ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}), 24
    )
    lag = est.best_lag_hours
    feats = F.build_features(ys, oh, lag)
    return LineData(line, alias, ys, oh, lag, feats, float(est.best_corr))


def all_lines(raw_file: str | None = None) -> dict[str, LineData]:
    """모든 라인의 LineData 를 반환."""
    _, osp_exp, yards = load_sources(raw_file)
    return {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}


def filter_period(df: pd.DataFrame, start=None, end=None, col: str = "datetime") -> pd.DataFrame:
    """[start, end] 기간으로 필터 (양끝 포함). start/end None이면 무제한.

    ⭐️ end 가 '날짜만'(시각 00:00)이면 그 날 **하루 전체**를 포함한다.
       (예: end='2026-07-28' → 07/28 23:59:59 까지. 리포트 HTML의 JS 필터와 동일 규칙)
    인덱스가 시간이면 col='index'.
    """
    if df is None or len(df) == 0:
        return df
    s = pd.to_datetime(df.index if col == "index" else df[col], errors="coerce")
    m = pd.Series(True, index=df.index)
    if start is not None:
        m &= s >= pd.Timestamp(start)
    if end is not None:
        e = pd.Timestamp(end)
        if e == e.normalize():  # 시각 미지정 → 그 날 끝까지
            e = e + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        m &= s <= e
    return df[m.values]


def load_yard_change(raw_file: str | None = None) -> pd.DataFrame:
    """야드변경 시트(기존+신설) → tidy long (datetime,line,yard,cao,mgo,tonnage).

    시트가 없으면 빈 DataFrame 반환(구 버전 데이터 호환).
    """
    xls = pd.ExcelFile(RAW_DIR / (raw_file or S.DATA_FILE))
    frames = []
    for sheet, line in [(S.SHEET_YC_OLD, S.LINE_OLD), (S.SHEET_YC_NEW, S.LINE_NEW)]:
        if sheet in xls.sheet_names:
            frames.append(C.clean_yard_change(pd.read_excel(xls, sheet), line))
    cols = ["datetime", "line", "yard", "cao", "mgo", "tonnage"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)


def load_osp_stock(raw_file: str | None = None) -> pd.DataFrame:
    """OSP 실사 재고 시트 → tidy long (datetime, date, shift, line, stock_ton).

    시트가 없으면 빈 DataFrame 반환(구 버전 데이터 호환).
    """
    xls = pd.ExcelFile(RAW_DIR / (raw_file or S.DATA_FILE))
    cols = ["datetime", "date", "shift", "line", "stock_ton"]
    if S.SHEET_OSP_STOCK not in xls.sheet_names:
        return pd.DataFrame(columns=cols)
    raw = pd.read_excel(xls, S.SHEET_OSP_STOCK, header=None)
    return C.clean_osp_stock(raw)


def load_surge_fills(raw_file: str | None = None) -> pd.DataFrame:
    """비고에서 뽑은 **수항(사일로) 적재** 기록 → [datetime, date, shift, cao, mgo, ton, note].

    수항은 광산과 G/C 사이의 버퍼다(용량 10,000톤). 여기 채운 물량은 **그 시점의
    OSP 적재가 아니며**, 나중에 G/C 를 거쳐 나간다 — 재고 수지에서 분리해 다뤄야 한다.
    """
    xls = pd.ExcelFile(RAW_DIR / (raw_file or S.DATA_FILE))
    cols = ["datetime", "date", "shift", "cao", "mgo", "ton", "note"]
    raw = pd.read_excel(xls, S.SHEET_MINE_49Q)
    if S.COL_MINE_NOTE not in raw.columns:
        return pd.DataFrame(columns=cols)      # 구 버전 데이터 호환
    rows = []
    for _, r in raw.iterrows():
        f = C.parse_surge_fill(r.get(S.COL_MINE_NOTE))
        if not f:
            continue
        rows.append(dict(datetime=C.shift_midpoint(r.get("채굴일자"), r.get("채굴시간(교대)")),
                         date=pd.to_datetime(r.get("채굴일자"), errors="coerce"),
                         shift=r.get("채굴시간(교대)"), cao=f["cao"], mgo=f["mgo"],
                         ton=f["ton"], note=str(r.get(S.COL_MINE_NOTE))))
    out = pd.DataFrame(rows, columns=cols)
    # ⚠️ 서로 다른 날짜에 (CaO, MgO, 톤) 이 완전히 같으면 **붙여넣기 오류**로 본다.
    #    "같은 품위를 두 번 가질 수는 없다"는 사용자 판단(2026-08-05). 어느 쪽이 원본인지
    #    단정할 수 없으므로 지우지 않고 **의심 표시만** 하고, 품위 통계에서는 제외한다(§2-1).
    out["suspect"] = False
    if len(out):
        key = out.dropna(subset=["cao"]).groupby(["cao", "mgo", "ton"])["date"].transform("nunique")
        dup = key[key > 1].index
        out.loc[dup, "suspect"] = True
    return out


def capacity_audit(mine: pd.DataFrame) -> pd.DataFrame:
    """생산방법(C/R) 상한으로 교대별 적재 기록을 감사한다.

    시간당 = 물량 ÷ (8h × 가동비율). 상한을 넘는 기록은 **물리적으로 불가능**하므로
    기록 오류 후보다. 지어내지 않고 '발견해서 보고'만 한다(CLAUDE.md §2-1).
    """
    cols = ["datetime", "line", "crusher", "tonnage", "hours", "tph", "cap_hi", "over"]
    if mine is None or "crusher" not in mine:
        return pd.DataFrame(columns=cols)
    d = mine.dropna(subset=["crusher"]).copy()
    d = d[pd.to_numeric(d["tonnage"], errors="coerce") > 0]
    if d.empty:
        return pd.DataFrame(columns=cols)
    # 한 교대(=원본 한 행)가 구역·라인으로 쪼개져 있으므로 교대 단위로 되모은다
    g = (d.groupby(["datetime", "crusher", "active_ratio"], dropna=False)
           .agg(tonnage=("tonnage", "sum"), line=("line", lambda x: "/".join(sorted(set(x)))))
           .reset_index())
    g["hours"] = 8.0 * g["active_ratio"].fillna(1.0)
    g["tph"] = g["tonnage"] / g["hours"].replace(0, np.nan)
    g["cap_hi"] = g["crusher"].map(lambda c: C.crusher_capacity(c)[1])
    g["over"] = g["tph"] > g["cap_hi"]

    # 비고에서 실제 생산 구간을 뽑은 교대는 그 시간으로 다시 환산해 참고 컬럼으로 둔다.
    # ⚠️ 감사의 '판정'(over)은 계속 8h 기준을 쓴다 — 구간 채택 자체가 능력 상한을 조건으로
    #    삼기 때문에, 그 시간으로 다시 판정하면 순환논리가 된다.
    if {"op_start", "op_end"} <= set(mine.columns):
        w = (mine.dropna(subset=["op_start", "op_end"])
                 .groupby("datetime")[["op_start", "op_end"]].first())
        g = g.merge(w, left_on="datetime", right_index=True, how="left")
        oh = (g["op_end"] - g["op_start"]).dt.total_seconds() / 3600
        g["op_hours"] = oh
        g["op_tph"] = g["tonnage"] / oh.replace(0, np.nan)
    else:
        g["op_hours"] = np.nan
        g["op_tph"] = np.nan
    return g[cols + ["op_hours", "op_tph"]].sort_values("tph", ascending=False)



def stock_vs_flow(stock: pd.DataFrame, mine: pd.DataFrame, osp_exp: pd.DataFrame,
                  line: str) -> dict:
    """실사 재고 변화 vs 흐름계산(적재−인출) 대조 (한 라인).

    두 값이 어긋나면 '광산 기록에 안 잡힌 유입'이 있다는 뜻이다. 어느 한쪽을
    맞다고 단정하지 않고 **둘 다와 그 차이를 함께 보고**한다(CLAUDE.md §2-1).
    반환: dict(start,end,days,actual,calc,gap,gap_per_day,inflow,outflow,s0,s1) 또는 {}
    """
    if stock is None or len(stock) == 0:
        return {}
    g = stock[(stock["line"] == line)].dropna(subset=["stock_ton"]).sort_values("datetime")
    m = mine[mine["line"] == line] if mine is not None and len(mine) else None
    o = osp_exp[osp_exp["line"] == line] if osp_exp is not None and len(osp_exp) else None
    if len(g) < 2 or m is None or o is None or not len(m) or not len(o):
        return {}
    lo = max(g["datetime"].min(), m["datetime"].min(), o["datetime"].min())
    hi = min(g["datetime"].max(), m["datetime"].max(), o["datetime"].max())
    gg = g[(g["datetime"] >= lo) & (g["datetime"] <= hi)]
    if len(gg) < 2:
        return {}
    a, b = gg["datetime"].iloc[0], gg["datetime"].iloc[-1]
    days = max((b - a).total_seconds() / 86400, 1e-9)
    inflow = float(pd.to_numeric(
        m[(m["datetime"] > a) & (m["datetime"] <= b)]["tonnage"], errors="coerce").sum())
    outflow = float(pd.to_numeric(
        o[(o["datetime"] > a) & (o["datetime"] <= b)]["withdrawn_ton"], errors="coerce").sum())
    s0, s1 = float(gg["stock_ton"].iloc[0]), float(gg["stock_ton"].iloc[-1])
    actual, calc = s1 - s0, inflow - outflow
    return dict(start=a, end=b, days=days, actual=actual, calc=calc,
                gap=actual - calc, gap_per_day=(actual - calc) / days,
                inflow=inflow, outflow=outflow, s0=s0, s1=s1)


# ⭐️ 타당 범위 가드: 계량 배율이 이 범위를 벗어나면 채택하지 않는다.
#    증분 회귀는 육안 실사 노이즈에 눌려 α=0.28·β=0.25 같은 값을 내놓는데,
#    이는 '기록의 1/4만 실제'라는 뜻이라 현장 지식과 배치된다(감쇠 편향).
PLAUSIBLE = (0.7, 1.3)

# 한 구간에서 β 를 식별하려면 인출이 최소한 이만큼은 흘러야 한다.
# (라인이 멈춘 구간은 분모가 0에 가까워 β 가 몇 배로 튄다)
MIN_WINDOW_TON = 5_000.0


def calibrate_flow(stock: pd.DataFrame, mine: pd.DataFrame, osp_exp: pd.DataFrame,
                   line: str) -> dict:
    """실사 재고에 맞춰 흐름 계산을 보정하는 계수를 추정한다 (최소제곱).

    ⭐️ 왜 필요한가: 실사는 육안 측정이라 편차가 있지만, 무작위 오차는 평균 0이라
       장기간에 상쇄된다. 그런데 실제로는 **한 방향으로 계속 쌓이는 체계 편차**가
       있어(신설 R²=0.76) 흐름 계산만으로는 재고가 마이너스가 된다.
       → 기록 자체의 배율을 데이터로 추정해 보정한다.

    비교하는 세 모델 (s0 = 첫 실사값, In/Out = 누적 적재/인출):
      A) s0 + α·In − Out      적재가 과소 기록되었다는 가정
      B) s0 + In − β·Out      인출이 과대 기록되었다는 가정
      C) s0 + In − Out + c·t  원인 불문 하루당 가산 보정
    잔차 표준편차가 가장 작은 모델을 선택한다.

    ⚠️ 이는 **경험적 보정**이지 원인 규명이 아니다. 어느 기록이 틀렸는지는
       현장 확인이 필요하며, 보정 후에도 남는 잔차는 육안 실사의 한계다.
    반환: dict(method, coef, resid_std, resid_std_raw, improve, n, days) 또는 {}
    """
    if stock is None or len(stock) == 0:
        return {}
    g = stock[stock["line"] == line].dropna(subset=["stock_ton"]).sort_values("datetime")
    m = mine[mine["line"] == line] if mine is not None and len(mine) else None
    o = osp_exp[osp_exp["line"] == line] if osp_exp is not None and len(osp_exp) else None
    if len(g) < 5 or m is None or o is None or not len(m) or not len(o):
        return {}
    lo = max(g["datetime"].min(), m["datetime"].min(), o["datetime"].min())
    hi = min(g["datetime"].max(), m["datetime"].max(), o["datetime"].max())
    g = g[(g["datetime"] >= lo) & (g["datetime"] <= hi)].reset_index(drop=True)
    if len(g) < 5:
        return {}

    t0, s0 = g["datetime"].iloc[0], float(g["stock_ton"].iloc[0])
    mt = pd.to_datetime(m["datetime"]).values
    mv = pd.to_numeric(m["tonnage"], errors="coerce").fillna(0).values
    ot = pd.to_datetime(o["datetime"]).values
    ov = pd.to_numeric(o["withdrawn_ton"], errors="coerce").fillna(0).values
    times = pd.to_datetime(g["datetime"]).values
    In = np.array([mv[(mt > np.datetime64(t0)) & (mt <= t)].sum() for t in times])
    Out = np.array([ov[(ot > np.datetime64(t0)) & (ot <= t)].sum() for t in times])
    Sv = g["stock_ton"].values.astype(float)
    days = (g["datetime"] - t0).dt.total_seconds().values / 86400.0

    def _fit(x, y):
        den = float(np.dot(x, x))
        return float(np.dot(x, y) / den) if den > 0 else np.nan

    cands = []
    raw_resid = Sv - (s0 + In - Out)
    a = _fit(In, Sv - s0 + Out)
    if np.isfinite(a) and PLAUSIBLE[0] <= a <= PLAUSIBLE[1]:
        cands.append(("적재 × α", a, Sv - (s0 + a * In - Out)))
    b = _fit(Out, s0 + In - Sv)
    if np.isfinite(b) and PLAUSIBLE[0] <= b <= PLAUSIBLE[1]:
        cands.append(("인출 × β", b, Sv - (s0 + In - b * Out)))
    c = _fit(days, Sv - s0 - In + Out)
    if np.isfinite(c):
        cands.append(("하루당 가산", c, Sv - (s0 + In - Out + c * days)))
    if not cands:
        return {}
    name, coef, resid = min(cands, key=lambda t: float(np.std(t[2])))
    # 계수의 표준오차 (원점 통과 회귀) — 추세인지 노이즈인지 판단에 쓴다
    base = {"적재 × α": In, "인출 × β": Out}.get(name, days)
    den = float(np.dot(base, base))
    se = float(np.sqrt((resid ** 2).sum() / max(len(resid) - 1, 1) / den)) if den > 0 else float("nan")
    raw_std = float(np.std(raw_resid))
    new_std = float(np.std(resid))
    # 육안 실사 자체의 노이즈(교대 간 변동 표준편차) — 보정으로 줄일 수 없는 하한
    noise = float(np.std(np.diff(Sv))) if len(Sv) > 2 else float("nan")
    return dict(method=name, coef=coef, se=se, resid_std=new_std, resid_std_raw=raw_std,
                improve=(1 - new_std / raw_std) * 100 if raw_std else 0.0,
                n=len(g), days=float(days[-1]), s0=s0, noise_std=noise)


def apply_calibration(cal: dict, idx, cum_in, cum_out, s0: float):
    """calibrate_flow 결과를 시계열에 적용해 보정된 재고 곡선을 만든다."""
    if not cal:
        return s0 + (np.asarray(cum_in) - np.asarray(cum_out))
    ci, co = np.asarray(cum_in, dtype=float), np.asarray(cum_out, dtype=float)
    if cal["method"] == "적재 × α":
        return s0 + cal["coef"] * ci - co
    if cal["method"] == "인출 × β":
        return s0 + ci - cal["coef"] * co
    d = (pd.to_datetime(pd.Series(idx)) - pd.to_datetime(idx[0])).dt.total_seconds().values / 86400.0
    return s0 + ci - co + cal["coef"] * d


def calibration_windows(stock: pd.DataFrame, mine: pd.DataFrame, osp_exp: pd.DataFrame,
                        line: str, window_days: int = 10) -> list[dict]:
    """보정계수를 기간을 잘라 구간별로 추정한다 (계량기 지시값이 흘러가는지 확인).

    ⭐️ 인출은 **벨트스케일**로 계량하므로 오차가 통과 물량에 비례한다(사용자 확인).
       따라서 배율 β 로 표현하는 것이 물리적으로 맞고, β 가 시간에 따라 변하면
       계량기 지시가 흘러가고 있다는 뜻이다 → 교정 시점 판단 근거.

    ⚠️ 라인이 멈춘 구간에서는 β 를 **식별할 수 없다**. 인출이 거의 없는데 재고는 움직이면
       분모(Out)가 0에 가까워 β 가 몇 배로 튄다 — 실제로 2026-08-05 갱신본에서 기존 라인
       마지막 창이 β=6.98 로 나왔다. 이런 창은 계량 배율이 아니라 '식별 불가'이므로
       `ok=False` 로 표시해 그래프에서 빼고, 몇 개를 왜 뺐는지는 리포트가 밝힌다(§2-1).

    반환: [{start, end, beta, se, n, ok, reason}] — 구간별 β·표준오차와 식별 가능 여부.
    """
    out = []
    if stock is None or len(stock) == 0:
        return out
    g0 = stock[stock["line"] == line].dropna(subset=["stock_ton"]).sort_values("datetime")
    m = mine[mine["line"] == line] if mine is not None and len(mine) else None
    o = osp_exp[osp_exp["line"] == line] if osp_exp is not None and len(osp_exp) else None
    if len(g0) < 10 or m is None or o is None or not len(m) or not len(o):
        return out
    lo = max(g0["datetime"].min(), m["datetime"].min(), o["datetime"].min())
    hi = min(g0["datetime"].max(), m["datetime"].max(), o["datetime"].max())
    g0 = g0[(g0["datetime"] >= lo) & (g0["datetime"] <= hi)]
    edges = list(pd.date_range(lo, hi, freq=f"{window_days}D")) + [hi]
    mt = pd.to_datetime(m["datetime"]).values
    mv = pd.to_numeric(m["tonnage"], errors="coerce").fillna(0).values
    ot = pd.to_datetime(o["datetime"]).values
    ov = pd.to_numeric(o["withdrawn_ton"], errors="coerce").fillna(0).values
    for a, b in zip(edges, edges[1:]):
        gg = g0[(g0["datetime"] >= a) & (g0["datetime"] <= b)]
        if len(gg) < 5:
            continue
        t0, s0 = gg["datetime"].iloc[0], float(gg["stock_ton"].iloc[0])
        T = pd.to_datetime(gg["datetime"]).values
        In = np.array([mv[(mt > np.datetime64(t0)) & (mt <= t)].sum() for t in T])
        Out = np.array([ov[(ot > np.datetime64(t0)) & (ot <= t)].sum() for t in T])
        Sv = gg["stock_ton"].values.astype(float)
        yv = s0 + In - Sv
        den = float(np.dot(Out, Out))
        if den <= 0:
            continue
        beta = float(np.dot(Out, yv) / den)
        r = yv - beta * Out
        se = float(np.sqrt((r ** 2).sum() / max(len(r) - 1, 1) / den))
        ok, reason = True, ""
        if float(Out.max()) < MIN_WINDOW_TON:
            ok, reason = False, f"인출 {Out.max():,.0f}톤 — 계량 배율을 식별하기엔 너무 적음"
        elif not (PLAUSIBLE[0] <= beta <= PLAUSIBLE[1]):
            ok, reason = False, f"β {beta:.2f} — 타당범위({PLAUSIBLE[0]}~{PLAUSIBLE[1]}) 밖"
        out.append(dict(start=a, end=b, beta=beta, se=se, n=len(gg), ok=ok, reason=reason))
    return out
