"""원시 시트 → tidy(long) 정제 [Data-Analyst → Matching-Agent].

data_v1.xlsx 각 시트를 매칭 가능한 정돈된 형태로 변환한다.
모든 변환은 '문서화된 규칙'을 따르며, 값을 지어내지 않는다(결측은 결측으로 유지, 정제 규칙만 적용).

핵심 규칙 (docs/data_schema.md, config/schema.py):
  - 복합 구역코드("50/55","55-45","100-0" 등)는 구분자 [/ - ~] 로 분리해 구역 리스트로 전개.
  - OSP 인출량(총톤)은 그 회차 구역 수로 '균등 배분'.
  - 시각 문자열 + 일자 → datetime 결합.
"""

from __future__ import annotations

import warnings

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
def shift_midpoint(date, shift, handover: bool | None = None):
    """교대(1/2/3차) → 그 교대의 **대표 시각(중점)**.

    광산 물량을 시간축에 놓으려면 대표 시각이 하나 필요하다. 교대 시작을 쓰면
    구간 경계에서 8시간을 통째로 앞당기게 되므로 **중점**을 쓴다(경계 오차 최소).
      1차 08~16 → 12:00 · 2차 16~24 → 20:00 · 3차 00~08 → 04:00
    handover=True 면 인수인계(기본 30분)만큼 시작을 늦춰 중점을 계산한다.
    (기본값은 config.schema.HANDOVER_APPLIED — 현재 False, §데이터스키마 참조)
    """
    d = pd.to_datetime(date, errors="coerce")
    win = S.SHIFT_HOURS.get(str(shift).strip()) if shift is not None else None
    if pd.isna(d) or win is None:
        return pd.NaT
    use_ho = S.HANDOVER_APPLIED if handover is None else handover
    start_h, end_h = win
    start = d.normalize() + pd.Timedelta(hours=start_h)
    end = d.normalize() + pd.Timedelta(hours=end_h)
    if use_ho:
        start = start + pd.Timedelta(minutes=S.HANDOVER_MINUTES)
    return start + (end - start) / 2


def _time_midpoint(date, t_start, t_end):
    """47Q 처럼 시작·종료 시각이 있는 경우의 대표 시각(중점).

    종료가 시작보다 이르면 자정을 넘긴 것으로 보고 하루를 더한다.
    """
    d = pd.to_datetime(date, errors="coerce")
    if pd.isna(d):
        return pd.NaT
    s = _combine(d, t_start)
    e = _combine(d, t_end)
    if pd.isna(s):
        return e if pd.notna(e) else pd.NaT
    if pd.isna(e):
        return s
    if e < s:
        e += pd.Timedelta(days=1)
    return s + (e - s) / 2


def _combine(day, t):
    """날짜 + datetime.time → Timestamp (시각이 없으면 NaT)."""
    if t is None or (isinstance(t, float) and np.isnan(t)) or pd.isna(t):
        return pd.NaT
    if isinstance(t, str):
        parsed = pd.to_datetime(t, errors="coerce")
        if pd.isna(parsed):
            return pd.NaT
        t = parsed.time()
    if hasattr(t, "hour"):
        return day.normalize() + pd.Timedelta(hours=t.hour, minutes=getattr(t, "minute", 0))
    return pd.NaT


def split_line_label(raw) -> list[str]:
    """복합 `공정구분` 라벨 → 실제 라인 리스트 (§S.LINE_SPLIT_DELIM 규칙).

    "기존" -> ["기존"] · "운휴/기존" -> ["기존"] · "기존/신설" -> ["기존","신설"]
    "운휴" -> []  (가동 안 함 — 실물량 없음)
    알 수 없는 라벨은 그대로 돌려보내 검증 게이트가 잡도록 둔다(조용히 버리지 않는다).
    """
    if raw is None or (isinstance(raw, float) and np.isnan(raw)) or pd.isna(raw):
        return []
    parts = [p.strip() for p in str(raw).split(S.LINE_SPLIT_DELIM) if p.strip()]
    real = [p for p in parts if p != S.LINE_IDLE]
    if not real:
        return []                      # 전부 운휴
    known = [p for p in real if p in (S.LINE_OLD, S.LINE_NEW)]
    return known if known else real    # 미상 라벨은 남겨 검증 게이트가 보고하게 한다



def clean_mine_49Q(df: pd.DataFrame) -> pd.DataFrame:
    """49Q XRF: 교대 단위 → (일자, 라인, 구역, CaO, MgO, 톤) 구역 전개 long."""
    rows = []
    for _, r in df.iterrows():
        zones = parse_zone_codes(r.get("OSP적재구역"))
        tonnage = _to_numeric(pd.Series([r.get("이송물량(톤)")])).iloc[0]
        # ⭐️ 구역코드가 비어도 **물량이 있으면 버리지 않는다**(zone=NaN 으로 남긴다).
        #    예전엔 통째로 건너뛰어 실제 채굴 물량 10,337톤이 사라졌다.
        #    구역 기반 매칭은 zone 결측 행을 알아서 제외하므로 안전하다.
        if not zones:
            if pd.isna(tonnage) or tonnage <= 0:
                continue          # 운휴 등 실물량 없는 행만 건너뛴다
            zones = [np.nan]
        lines = split_line_label(r.get("공정구분"))
        if not lines:                   # 전부 운휴 → 실물량 없음
            continue
        per_ton = tonnage / (len(zones) * len(lines)) if pd.notna(tonnage) else np.nan
        for z in zones:
          for _ln in lines:
            rows.append(
                dict(
                    date=pd.to_datetime(r.get("채굴일자"), errors="coerce"),
                    line=_ln,
                    zone=z,
                    cao=pd.to_numeric(r.get("CaO품위"), errors="coerce"),
                    mgo=pd.to_numeric(r.get("MgO품위"), errors="coerce"),
                    tonnage=per_ton,
                    source="49Q",
                    shift=r.get("채굴시간(교대)"),
                    # 교대 시간대로 실제 시각 부여 (일 단위였을 때의 경계 오차 제거)
                    datetime=shift_midpoint(r.get("채굴일자"), r.get("채굴시간(교대)")),
                )
            )
    return pd.DataFrame(rows)


def apply_line_overrides(df: pd.DataFrame, raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """사용자 확정 라인 귀속 정정을 적용한다 (`S.MINE_LINE_OVERRIDES`).

    원본 시트의 `공정구분` 이 실사 재고와 배치되어 사용자가 바로잡은 건만 담긴다.
    정정은 **라인 라벨만** 바꾼다 — 물량·품위·시각은 원본 그대로다.

    ⚠️ 규칙이 한 건도 맞지 않으면(원본이 바뀌었다는 뜻) 조용히 넘어가지 않고 경고한다.
       원본이 현장에서 바로잡히면 `S.MINE_LINE_OVERRIDES` 를 비워야 한다.
    """
    rules = [r for r in getattr(S, "MINE_LINE_OVERRIDES", []) if r["source"] == source]
    if not rules or df.empty:
        return df
    key = (pd.to_datetime(raw.get("채굴일자"), errors="coerce").dt.strftime("%Y-%m-%d")
           + "|" + _hhmm(raw.get("시작시간")) + "|" + _hhmm(raw.get("종료시간")))
    applied = 0
    for r in rules:
        want = f"{r['date']}|{r['start']}|{r['end']}"
        hit = key[key == want].index
        if len(hit) == 0:
            warnings.warn(
                f"[라인 귀속 정정] {source} {want} 에 해당하는 원본 행이 없습니다 — "
                "원본이 갱신되었다면 config/schema.MINE_LINE_OVERRIDES 를 재검토하세요.",
                stacklevel=2)
            continue
        m = df["_raw_idx"].isin(hit)
        applied += int(m.sum())
        df.loc[m, "line"] = r["line"]
    df.attrs["line_overrides_applied"] = applied
    return df


def _hhmm(series) -> pd.Series:
    """시각 컬럼을 'HH:MM' 문자열로 (정정 규칙 대조용)."""
    t = pd.to_timedelta(pd.Series(series).astype(str), errors="coerce")
    h = (t.dt.total_seconds() // 3600).astype("Int64")
    m = ((t.dt.total_seconds() % 3600) // 60).astype("Int64")
    return h.astype(str).str.zfill(2) + ":" + m.astype(str).str.zfill(2)



def clean_mine_47Q(df: pd.DataFrame) -> pd.DataFrame:
    """47Q 감마레이: 구간(시작~종료) 단위 → 구역 전개 long."""
    rows = []
    for idx, r in df.iterrows():
        zones = parse_zone_codes(r.get("OSP적재구역"))
        tonnage = pd.to_numeric(r.get("이송물량(톤)"), errors="coerce")
        if not zones:                       # 49Q 와 동일 규칙 (물량 보존)
            if pd.isna(tonnage) or tonnage <= 0:
                continue
            zones = [np.nan]
        lines = split_line_label(r.get("공정구분"))
        if not lines:
            continue
        per_ton = tonnage / (len(zones) * len(lines)) if pd.notna(tonnage) else np.nan
        for z in zones:
          for _ln in lines:
            rows.append(
                dict(
                    _raw_idx=idx,
                    date=pd.to_datetime(r.get("채굴일자"), errors="coerce"),
                    line=_ln,
                    zone=z,
                    cao=pd.to_numeric(r.get("CaO품위"), errors="coerce"),
                    mgo=pd.to_numeric(r.get("MgO품위"), errors="coerce"),
                    tonnage=per_ton,
                    source="47Q",
                    shift=None,
                    # 47Q 는 실제 시작·종료 시각이 있다 → 그 중점을 대표 시각으로
                    datetime=_time_midpoint(r.get("채굴일자"), r.get("시작시간"), r.get("종료시간")),
                )
            )
    out = apply_line_overrides(pd.DataFrame(rows), df, "47Q")
    return out.drop(columns=["_raw_idx"], errors="ignore")


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
        total = pd.to_numeric(r.get("인출량"), errors="coerce")
        # ⭐️ 인출지점(P/W)이 비어도 **인출량이 있으면 버리지 않는다**(zone=NaN).
        #    야드변경 잔량처럼 지점 없이 기록되는 행이 있어, 예전엔 2,000톤이 사라졌다.
        if not zones:
            if pd.isna(total) or total <= 0:
                continue
            zones = [np.nan]
        per = total / len(zones) if pd.notna(total) else np.nan
        dt = _combine_datetime(
            pd.Series([r.get("일자")]), pd.Series([r.get("인출시간")])
        ).iloc[0]
        for z in zones:
            rows.append(
                dict(datetime=dt, line=line, zone=float(z) if pd.notna(z) else np.nan,
                     withdrawn_ton=per)
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


# --------------------------------------------------------------------------- #
# ⑤ OSP 실사 재고 — 좌우 2블록(OSP1/OSP2) → tidy long
# --------------------------------------------------------------------------- #
def clean_osp_stock(raw: pd.DataFrame) -> pd.DataFrame:
    """'OSP 재고' 시트(header=None 로 읽은 원시 프레임) → tidy long.

    시트는 좌우 두 블록이 나란히 있다(가운데 열은 빈 칸).
      0~3열 = OSP1(기존 라인) · 5~8열 = OSP2(신설 라인), 헤더는 3번째 행.
    각 블록: 날짜 · 차수(1/2/3) · OSP 구분 · 재고량(톤)

    ⭐️ 실사 시각은 교대 중간의 1시간 파악 시간대 중점을 쓴다(사용자 확정).
       1차 12:30 · 2차 20:30 · 3차 04:30 — 채굴 교대 중점과는 별개다.
    ⭐️ 같은 (라인·날짜·차수)가 두 번 기록된 행이 있다(전 기간 28행).
       조용히 버리지 않고 **마지막 기록을 채택**하며, 몇 건이었는지 남긴다.

    반환 컬럼: datetime, date, shift, line, stock_ton, dup_dropped(attrs)
    """
    frames = []
    for name, cols in S.STOCK_BLOCKS.items():
        if raw.shape[1] <= max(cols):
            continue
        d = raw.iloc[S.STOCK_HEADER_ROW + 1:, cols].copy()
        d.columns = ["date", "shift", "osp", "stock_ton"]
        d = d.dropna(how="all")
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d["shift"] = pd.to_numeric(d["shift"], errors="coerce")
        d["stock_ton"] = _to_numeric(d["stock_ton"])
        d = d.dropna(subset=["date", "shift"])
        d["shift"] = d["shift"].astype(int)
        d["line"] = S.OSP_TO_LINE.get(name, name)
        d["datetime"] = d["date"] + pd.to_timedelta(
            d["shift"].map(S.STOCK_TAKE_HOURS).astype(float), unit="h")
        frames.append(d[["datetime", "date", "shift", "line", "stock_ton"]])

    cols = ["datetime", "date", "shift", "line", "stock_ton"]
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True).sort_values("datetime")
    before = len(out)
    out = out.drop_duplicates(subset=["line", "date", "shift"], keep="last")
    out = out.reset_index(drop=True)
    out.attrs["dup_dropped"] = before - len(out)
    return out
