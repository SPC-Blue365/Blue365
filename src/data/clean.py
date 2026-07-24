"""원시 시트 → tidy(long) 정제 [Data-Analyst → Matching-Agent].

data_v1.xlsx 각 시트를 매칭 가능한 정돈된 형태로 변환한다.
모든 변환은 '문서화된 규칙'을 따르며, 값을 지어내지 않는다(결측은 결측으로 유지, 정제 규칙만 적용).

핵심 규칙 (docs/data_schema.md, config/schema.py):
  - 복합 구역코드("50/55","55-45","100-0" 등)는 구분자 [/ - ~] 로 분리해 구역 리스트로 전개.
  - OSP 인출량(총톤)은 그 회차 구역 수로 '균등 배분'.
  - 시각 문자열 + 일자 → datetime 결합.
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from config import schema as S


# --------------------------------------------------------------------------- #
# 공통 유틸
# --------------------------------------------------------------------------- #
def parse_zone_codes(raw) -> list[float]:
    """복합 구역코드 문자열을 숫자 구역 리스트로 전개.

    예: "50/55" -> [50, 55], "55-45" -> [55, 45], "100-0" -> [100, 0],
        "50" -> [50], "운휴"/NaN -> [].
    """
    if pd.isna(raw):
        return []
    s = str(raw).strip()
    if s in ("", S.LINE_IDLE):
        return []
    tokens = re.split(S.ZONE_DELIMITERS, s)
    zones = []
    for t in tokens:
        t = t.strip()
        if t == "":
            continue
        try:
            zones.append(float(t))
        except ValueError:
            # 숫자로 못 바꾸는 토큰(예: 빈값/기호)은 건너뜀
            continue
    return zones


def _combine_datetime(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    """일자(date) + 시각(time/str) → datetime. 파싱 실패는 NaT."""
    d = pd.to_datetime(date_series, errors="coerce")
    t = pd.to_datetime(time_series.astype(str), errors="coerce", format="mixed")
    # 시각의 시/분/초만 취해 날짜에 더함
    delta = pd.to_timedelta(
        t.dt.hour.fillna(0).astype(int).astype(str) + "h"
    ) + pd.to_timedelta(
        t.dt.minute.fillna(0).astype(int).astype(str) + "m"
    )
    return d + delta.where(t.notna(), pd.Timedelta(0))


def _to_numeric(series: pd.Series) -> pd.Series:
    """'-' 등 비수치 토큰을 NaN 처리하며 수치화."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip().replace({"-": np.nan, "": np.nan}),
        errors="coerce",
    )


# --------------------------------------------------------------------------- #
# ① 광산 (Mine) — 구역별 품위 이벤트로 전개
# --------------------------------------------------------------------------- #
def clean_mine_49Q(df: pd.DataFrame) -> pd.DataFrame:
    """49Q XRF: 교대 단위 → (일자, 라인, 구역, CaO, MgO, 톤) 구역 전개 long."""
    rows = []
    for _, r in df.iterrows():
        zones = parse_zone_codes(r.get("OSP적재구역"))
        if not zones:
            continue
        tonnage = _to_numeric(pd.Series([r.get("이송물량(톤)")])).iloc[0]
        per_ton = tonnage / len(zones) if pd.notna(tonnage) else np.nan
        for z in zones:
            rows.append(
                dict(
                    date=pd.to_datetime(r.get("채굴일자"), errors="coerce"),
                    line=str(r.get("공정구분")),
                    zone=z,
                    cao=pd.to_numeric(r.get("CaO품위"), errors="coerce"),
                    mgo=pd.to_numeric(r.get("MgO품위"), errors="coerce"),
                    tonnage=per_ton,
                    source="49Q",
                    shift=r.get("채굴시간(교대)"),
                )
            )
    return pd.DataFrame(rows)


def clean_mine_47Q(df: pd.DataFrame) -> pd.DataFrame:
    """47Q 감마레이: 구간(시작~종료) 단위 → 구역 전개 long."""
    rows = []
    for _, r in df.iterrows():
        zones = parse_zone_codes(r.get("OSP적재구역"))
        if not zones:
            continue
        tonnage = pd.to_numeric(r.get("이송물량(톤)"), errors="coerce")
        per_ton = tonnage / len(zones) if pd.notna(tonnage) else np.nan
        for z in zones:
            rows.append(
                dict(
                    date=pd.to_datetime(r.get("채굴일자"), errors="coerce"),
                    line=str(r.get("공정구분")),
                    zone=z,
                    cao=pd.to_numeric(r.get("CaO품위"), errors="coerce"),
                    mgo=pd.to_numeric(r.get("MgO품위"), errors="coerce"),
                    tonnage=per_ton,
                    source="47Q",
                    shift=None,
                )
            )
    return pd.DataFrame(rows)


def build_zone_grade_table(mine_long: pd.DataFrame) -> pd.DataFrame:
    """구역(zone)별 대표 CaO 품위 테이블 생성.

    라인(기존/신설)별 + 구역별 평균 CaO. 광산 적재 품위가 곧 해당 구역의 품위라는 가정.
    (운휴·복합라인 등 비표준 라인 값은 제외)
    """
    m = mine_long.copy()
    m = m[m["line"].isin([S.LINE_OLD, S.LINE_NEW])]
    m = m.dropna(subset=["zone", "cao"])
    # 라인+구역별
    by_line = (
        m.groupby(["line", "zone"])
        .agg(cao_zone=("cao", "mean"), n=("cao", "size"))
        .reset_index()
    )
    # 구역만 (라인 무관 fallback)
    by_zone = (
        m.groupby("zone").agg(cao_zone_global=("cao", "mean"), n_global=("cao", "size")).reset_index()
    )
    return by_line, by_zone


# --------------------------------------------------------------------------- #
# ② OSP 인출 — 균등 배분으로 구역별 인출 long
# --------------------------------------------------------------------------- #
def clean_osp(df: pd.DataFrame, line: str, pw_cols: list[str]) -> pd.DataFrame:
    """OSP 인출 시트 → (datetime, 라인, 구역, 인출톤(균등배분)) long."""
    rows = []
    for _, r in df.iterrows():
        zones = [
            pd.to_numeric(r.get(c), errors="coerce")
            for c in pw_cols
            if pd.notna(r.get(c))
        ]
        zones = [z for z in zones if pd.notna(z)]
        if not zones:
            continue
        total = pd.to_numeric(r.get("인출량"), errors="coerce")
        per = total / len(zones) if pd.notna(total) else np.nan
        dt = _combine_datetime(
            pd.Series([r.get("일자")]), pd.Series([r.get("인출시간")])
        ).iloc[0]
        for z in zones:
            rows.append(
                dict(datetime=dt, line=line, zone=float(z), withdrawn_ton=per)
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# ③ 야드 CNA — 최종 목표 기준
# --------------------------------------------------------------------------- #
def clean_yard(df: pd.DataFrame, load_col: Optional[str] = None) -> pd.DataFrame:
    """야드 연속측정 → (datetime, cao, mgo, load). 시각+일자 결합.

    CNA data(적재물량(TPH))·45Q 감마레이(적재물량(B/S)) 등 구조가 같은 야드 스트림에 공용.
    load_col 미지정 시 '적재물량'을 포함하는 컬럼을 자동 탐색.
    """
    if load_col is None:
        cand = [c for c in df.columns if "적재물량" in str(c)]
        load_col = cand[0] if cand else None
    out = pd.DataFrame()
    out["datetime"] = _combine_datetime(df["일자"], df["시간"])
    out["cao"] = pd.to_numeric(df["CaO"], errors="coerce")
    out["mgo"] = pd.to_numeric(df["MgO"], errors="coerce")
    out["load"] = pd.to_numeric(df[load_col], errors="coerce") if load_col else np.nan
    return out.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)


def clean_yard_cna(df: pd.DataFrame) -> pd.DataFrame:
    """호환용 래퍼 (CNA). 반환 컬럼의 load 를 tph 로 별칭 제공."""
    out = clean_yard(df, load_col="적재물량(TPH)")
    out["tph"] = out["load"]
    return out


def clean_yard_change(df: pd.DataFrame, line: str) -> pd.DataFrame:
    """야드변경 시트 → (datetime, line, yard, cao, mgo, tonnage) tidy.

    각 행 = 야드 변경 이벤트(그 시점부터 해당 야드에 적재한 물량·품위).
    """
    out = pd.DataFrame()
    out["datetime"] = _combine_datetime(df["변경일"], df["변경시간"])
    out["line"] = line
    # 야드명 정규화: "-내수" 접미사 제거 (신설(Y1)-내수 → 신설(Y1))
    out["yard"] = df["Yard"].astype(str).str.strip().str.replace("-내수", "", regex=False)
    out["cao"] = pd.to_numeric(df["석회석CaO"], errors="coerce")
    out["mgo"] = pd.to_numeric(df["석회석MgO"], errors="coerce")
    out["tonnage"] = pd.to_numeric(df["야드물량"], errors="coerce")
    return out.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
