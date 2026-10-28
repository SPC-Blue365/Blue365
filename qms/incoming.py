"""원료·부원료·석고·고령토 인수검사 결과 저장·요약 — 공정 데이터(store.py)와 분리된 독립 모듈.

LIMS '…인수검사'·'고령토' 내보내기 파일(제목 1행 + 머리글 3행)을 그대로 읽어
검사종류·거래처·품명·검사일·합부판정 + 성분값을 저장한다. 성분 항목이 품목마다 달라서
공통 메타 열 + 성분(JSON) 구조로 담는다. 화면은 합부 현황·거래처별·최근 목록을 보여 준다.
"""

from __future__ import annotations

import io
import json
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass, field

import pandas as pd

from .standards import DATA_DIR

INCOMING_DB_PATH = DATA_DIR / "incoming.db"
STD_PATH = DATA_DIR / "incoming_standards.json"

# 합부판정에 쓸 수 있는 항목(사용자가 이 중에서 골라 기준값 입력)
JUDGE_ITEMS = ["SiO2", "Al2O3", "Fe2O3", "MgO", "SO3", "K2O", "수분"]

# 제목(정규화) → 검사종류 이름
TITLE_KIND = [("조합원료", None), ("크링커", None), ("클링커", None), ("시멘트", None),   # 공정 파일은 여기서 제외
              ("고령토", "고령토"), ("석고", "석고"), ("rawmaterial", "원료·부원료"), ("인수검사", "원료·부원료")]

META = {"검사종류", "로트번호", "검사일", "채취일", "거래처", "품명", "합부판정", "비고", "성분"}
_ALIAS = {"로트번호": "로트번호", "검사일": "검사일", "채취일": "채취일", "거래처": "거래처", "품명": "품명",
          "합부판정": "합부판정", "판정": "합부판정", "합격여부": "합부판정", "비고": "비고"}
PASS, FAIL = "합격", "불합격"


def _s(v) -> str:
    """빈 값(None·NaN)을 빈 문자열로. (float('nan') 은 truthy 라 `v or ''` 로는 걸러지지 않음)"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _norm(s) -> str:
    if s is None:
        return ""
    import re

    t = unicodedata.normalize("NFKC", _s(s)).strip().lower().replace("μ", "u").replace("µ", "u")
    return re.sub(r"\s+", "", t)


def _kind_from_title(title: str) -> str | None:
    t = _norm(title)
    for key, kind in TITLE_KIND:
        if _norm(key) in t:
            return kind                                # None → 공정 파일(인수검사 아님)
    return None


def norm_judge(v) -> str:
    s = _norm(v)
    if not s:
        return ""
    if s in ("합격", "합", "ok", "pass", "p", "적합", "양호"):
        return PASS
    if s in ("불합격", "불", "ng", "fail", "f", "부적합", "불량", "반송"):
        return FAIL
    return str(v).strip()


@dataclass
class IncomingParse:
    rows: pd.DataFrame
    kind: str
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _find_header(raw: pd.DataFrame) -> int | None:
    for r in range(min(len(raw), 8)):
        cells = [_norm(v) for v in raw.iloc[r].tolist()]
        if sum(bool(c) for c in cells) >= 6 and ("채취일" in cells or "검사일" in cells):
            return r
    return None


def detect_incoming_title(file_bytes: bytes) -> str | None:
    """인수검사 파일이면 검사종류 이름, 아니면 None(공정 파일 포함)."""
    try:
        raw = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None)
    except Exception:  # noqa: BLE001
        return None
    hrow = _find_header(raw)
    if hrow is None:
        return None
    title = " ".join(_norm(v) for r in range(hrow) for v in raw.iloc[r].tolist() if _norm(v))
    return _kind_from_title(title)


def looks_like_incoming(file_bytes: bytes, filename: str = "") -> bool:
    return detect_incoming_title(file_bytes) is not None


def parse_incoming(file_bytes: bytes, filename: str = "") -> IncomingParse:
    try:
        raw = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None)
    except Exception as exc:  # noqa: BLE001
        return IncomingParse(pd.DataFrame(), "", [], [f"엑셀을 읽을 수 없습니다: {exc}"])
    return parse_incoming_df(raw)


def parse_incoming_df(raw: pd.DataFrame) -> IncomingParse:
    hrow = _find_header(raw)
    if hrow is None:
        return IncomingParse(pd.DataFrame(), "", [], ["머리글(채취일/검사일)을 찾지 못했습니다."])
    title = " ".join(_norm(v) for r in range(hrow) for v in raw.iloc[r].tolist() if _norm(v))
    kind = _kind_from_title(title)
    if kind is None:
        return IncomingParse(pd.DataFrame(), "", [], ["인수검사 파일이 아닙니다(원료·석고·고령토 인수검사만)."])
    headers = [str(v) if v is not None else "" for v in raw.iloc[hrow].tolist()]
    body = raw.iloc[hrow + 1:].copy()
    body.columns = headers
    nmap = {h: _ALIAS.get(_norm(h)) for h in headers}
    comp_cols = [h for h in headers if h and nmap.get(h) is None
                 and _norm(h) not in ("자료생성일", "최종수정일", "전송", "수량", "채취시간", "담당자")]
    out = []
    for _, row in body.iterrows():
        rec = {k: "" for k in ("로트번호", "검사일", "채취일", "거래처", "품명", "합부판정", "비고")}
        for h in headers:
            tgt = nmap.get(h)
            if tgt:
                rec[tgt] = row[h]
        date = pd.to_datetime(rec.get("채취일") or rec.get("검사일"), errors="coerce")
        if pd.isna(date):
            continue
        comp = {}
        for h in comp_cols:
            v = row[h]
            if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != "":
                comp[h] = v
        out.append({"검사종류": kind, "로트번호": _s(rec["로트번호"]),
                    "검사일": pd.to_datetime(rec.get("검사일"), errors="coerce"), "채취일": date,
                    "거래처": _s(rec["거래처"]), "품명": _s(rec["품명"]),
                    "합부판정": norm_judge(rec["합부판정"]), "비고": _s(rec["비고"]),
                    "성분": json.dumps(comp, ensure_ascii=False, default=str)})
    df = pd.DataFrame(out)
    if df.empty:
        return IncomingParse(df, kind, [], ["날짜가 있는 데이터 행이 없습니다."])
    from .store import fix_future_dates
    df, fixed, dropped = fix_future_dates(df, "채취일", ref_col="검사일")      # 연도 오타는 검사일 연도로
    future_msg = ([f"[{kind}] ⚠ 미래 채취일을 입력 오타로 보고 검사일 연도로 고쳐 읽었습니다: {fixed} — 원본도 고쳐 주세요."] if fixed else []) \
        + ([f"[{kind}] ⚠ 고쳐도 미래인 채취일 행은 제외했습니다: {dropped}"] if dropped else [])
    if df.empty:
        return IncomingParse(df, kind, future_msg, ["날짜가 있는 데이터 행이 없습니다."])
    n_pass = int((df["합부판정"] == PASS).sum())
    n_fail = int((df["합부판정"] == FAIL).sum())
    msg = [f"[{kind}] {len(df)}행 인식 ({df['채취일'].min():%Y-%m-%d} ~ {df['채취일'].max():%Y-%m-%d})",
           f"합격 {n_pass} · 불합격 {n_fail} · 판정없음 {len(df) - n_pass - n_fail} · 성분항목 {len(comp_cols)}개", *future_msg]
    return IncomingParse(df, kind, msg, [])


# ── 저장소 ───────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    INCOMING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(INCOMING_DB_PATH)


COLUMNS = ["검사종류", "로트번호", "검사일", "채취일", "거래처", "품명", "합부판정", "비고", "성분"]
KEYS = ["검사종류", "로트번호", "채취일"]


def load_incoming() -> pd.DataFrame:
    if not INCOMING_DB_PATH.exists():
        return pd.DataFrame(columns=COLUMNS)
    with closing(_connect()) as con:
        try:
            df = pd.read_sql("SELECT * FROM incoming", con, parse_dates=["검사일", "채취일"])
        except (pd.errors.DatabaseError, sqlite3.OperationalError):
            return pd.DataFrame(columns=COLUMNS)
    return df


def save_incoming(df: pd.DataFrame, replace: bool = False) -> int:
    if df.empty:
        return 0
    df = df.reindex(columns=COLUMNS).copy()
    with closing(_connect()) as con:
        old = None
        if not replace:
            try:
                old = pd.read_sql("SELECT * FROM incoming", con, parse_dates=["검사일", "채취일"])
            except (pd.errors.DatabaseError, sqlite3.OperationalError):
                old = None
        both = pd.concat([x for x in (old, df) if x is not None and len(x)], ignore_index=True)
        for k in ("검사일", "채취일"):
            both[k] = pd.to_datetime(both[k], errors="coerce")
        both["로트번호"] = both["로트번호"].fillna("").astype(str)
        merged = both.groupby(KEYS, as_index=False, sort=False, dropna=False).last()
        merged = merged.sort_values("채취일").reset_index(drop=True)
        save = merged.copy()
        for k in ("검사일", "채취일"):
            save[k] = pd.to_datetime(save[k]).dt.strftime("%Y-%m-%d")
        save.to_sql("incoming", con, if_exists="replace", index=False)
        con.commit()
        return len(merged)


def clear_incoming() -> None:
    if INCOMING_DB_PATH.exists():
        with closing(_connect()) as con:
            con.execute("DROP TABLE IF EXISTS incoming")
            con.commit()


def summary(df: pd.DataFrame | None = None) -> dict:
    df = load_incoming() if df is None else df
    if df.empty:
        return {"total": 0, "pass": 0, "fail": 0, "fail_rate": 0.0, "by_kind": pd.DataFrame(), "fails": pd.DataFrame()}
    total = len(df)
    npass = int((df["합부판정"] == PASS).sum())
    nfail = int((df["합부판정"] == FAIL).sum())
    by_kind = (df.assign(불합격=(df["합부판정"] == FAIL).astype(int))
               .groupby("검사종류").agg(건수=("합부판정", "size"), 불합격=("불합격", "sum")).reset_index())
    fails = df[df["합부판정"] == FAIL][["채취일", "검사종류", "거래처", "품명", "비고"]].sort_values("채취일", ascending=False)
    return {"total": total, "pass": npass, "fail": nfail,
            "fail_rate": round(100 * nfail / total, 1) if total else 0.0, "by_kind": by_kind, "fails": fails}


# ── 사내 인수검사 기준·자동 합부판정 ──────────────────────────────────────
def load_standards() -> list[dict]:
    """기준 규칙 목록: [{'대상': 품명 포함 키워드(빈값=전체), '항목': 'SiO2', 'min': 88, 'max': None}]."""
    if STD_PATH.exists():
        try:
            d = json.loads(STD_PATH.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else d.get("rules", [])
        except (OSError, json.JSONDecodeError):
            pass
    return []


def save_standards(rules: list[dict]) -> None:
    STD_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean = []
    for r in rules:
        item = (r.get("항목") or "").strip()
        if item not in JUDGE_ITEMS:
            continue
        lo, hi = r.get("min"), r.get("max")
        if lo is None and hi is None:
            continue
        clean.append({"대상": (r.get("대상") or "").strip(), "항목": item,
                      "min": None if lo is None else float(lo), "max": None if hi is None else float(hi)})
    STD_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def _comp_value(comp: dict, item: str):
    """성분(dict)에서 항목값 찾기 — 'SO3' 는 'SO3(XRF)' 같은 변형도 매칭."""
    target = _norm(item)
    for k, v in comp.items():
        nk = _norm(k)
        if nk == target or nk.startswith(target):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def judge_one(comp: dict, product: str, rules: list[dict]) -> tuple[str, list[str]]:
    """기준 대비 자동 판정 → ('합격'/'불합격'/'', 사유목록). 적용된 기준이 하나도 없으면 ''."""
    applied, fails = 0, []
    pn = _norm(product)
    for r in rules:
        tgt = _norm(r.get("대상", ""))
        if tgt and tgt not in pn:
            continue
        val = _comp_value(comp, r["항목"])
        if val is None:
            continue
        applied += 1
        lo, hi = r.get("min"), r.get("max")
        if lo is not None and val < lo:
            fails.append(f"{r['항목']} {val} < 최소 {lo}")
        if hi is not None and val > hi:
            fails.append(f"{r['항목']} {val} > 최대 {hi}")
    if applied == 0:
        return "", []
    return (FAIL if fails else PASS), fails


def judge_frame(df: pd.DataFrame, rules: list[dict] | None = None) -> pd.DataFrame:
    """자동판정·최종판정·판정사유 열을 더한다. 최종판정 = LIMS 합부판정 우선, 없으면 자동판정."""
    rules = load_standards() if rules is None else rules
    out = df.copy()
    autos, reasons = [], []
    for _, r in out.iterrows():
        try:
            comp = json.loads(r["성분"]) if isinstance(r.get("성분"), str) and r["성분"] else {}
        except (json.JSONDecodeError, TypeError):
            comp = {}
        j, why = judge_one(comp, str(r.get("품명", "")), rules)
        autos.append(j)
        reasons.append(" / ".join(why))
    out["자동판정"] = autos
    out["판정사유"] = reasons
    out["최종판정"] = out["합부판정"].where(out["합부판정"].isin([PASS, FAIL]), pd.Series(autos, index=out.index))
    return out
