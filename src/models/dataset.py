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
