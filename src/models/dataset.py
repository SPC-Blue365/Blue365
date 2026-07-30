"""공용 데이터셋 로더 (정제→매칭→라인별 피처) [ML-Engineer].

여러 스크립트(학습·모니터·리포트)가 동일한 피처를 재사용하도록 한 곳에 모은다.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    lag = P.estimate_time_lag(
        oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
        ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}), 24
    ).best_lag_hours
    feats = F.build_features(ys, oh, lag)
    return LineData(line, alias, ys, oh, lag, feats)


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
