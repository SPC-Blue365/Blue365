"""선박별 양하지(하역지) 자동 연결.

출하시멘트 기록(1행 = 채취일, 비고 = 그날 출항한 선박)의 각 선박에 양하지를 자동으로 붙인다.
값을 추정하지 않고, 기록된 정보만 아래 우선순위로 쓴다.
  1) 운항(양하지) 기록 — 사용자가 올린 [일자·선박·양하지] 표. 같은 날짜, 없으면 앞뒤 1일 이내 기록
  2) LIMS 비고의 괄호 주석 — 예: '리나호(부산)'
  3) 선박 기본 양하지 — 화면에서 선박별로 입력한 값(늘 같은 곳으로 가는 배)
양하지 기록·기본값을 바꾸면 저장된 모든 출하 기록에 자동으로 다시 연결된다(저장값이 아니라 불러올 때 계산).
한 날짜에 양하지가 다른 배가 섞이면 '복수 양하지'로 두고 양하지별로 나누지 않는다(평균값이라 분해 불가).
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from . import shipment as S
from .standards import DATA_DIR

DEST_DB_PATH = DATA_DIR / "ship_dest.db"
MIXED, UNKNOWN, PARTIAL = "복수 양하지", "미상", "일부 미상"
SOURCES = ("운항기록", "비고", "기본값")

ALIASES = {
    "date": ("출항일", "출항일자", "출항일시", "출항", "선적일", "선적일자", "적재일", "적재일자", "적하일", "출하일", "출하일자",
             "일자", "날짜", "기준일", "채취일", "date"),
    "ship": ("선박", "선박명", "선명", "모선", "모선명", "본선", "본선명", "배", "배이름", "운반선", "vessel", "ship", "shipname"),
    "dest": ("양하지", "양하항", "양하항구", "양하장소", "하역지", "하역항", "도착지", "도착항", "도착항구", "목적지", "목적항",
             "입항지", "착항", "착지", "출하기지", "기지", "port", "destination", "dest"),
}


def _connect():
    DEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DEST_DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS ship_master (ship TEXT PRIMARY KEY, dest TEXT, note TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS ship_voyage (date TEXT, ship TEXT, dest TEXT, source TEXT, updated_at TEXT,"
                " PRIMARY KEY (date, ship))")
    return con


def dest_mtime() -> float:
    return DEST_DB_PATH.stat().st_mtime if DEST_DB_PATH.exists() else 0.0


# ── 이름 정리 ───────────────────────────────────────────────────────────
def clean_ship(name, known: set[str] | None = None) -> str:
    """선박명 표기 통일: 공백·마침표·괄호 제거, '수성3' → '수성3호'(알려진 이름이 있으면 그 이름)."""
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return ""
    s = re.sub(r"[(（][^)）]*[)）]", "", str(name))
    s = re.sub(r"[\s.·]+", "", s)
    if not s:
        return ""
    known = known or set()
    if s in known:
        return s
    if not s.endswith("호") and s + "호" in known:
        return s + "호"
    if re.fullmatch(r"[가-힣]+\d+", s):
        return s + "호"
    return s


def clean_dest(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = re.sub(r"\s+", "", str(v)).strip(".·,")
    s = re.sub(r"(항|항구)$", "", s) if len(s) > 2 else s       # '부산항' → '부산'
    return s


# ── 저장소 ──────────────────────────────────────────────────────────────
def load_master() -> pd.DataFrame:
    if not DEST_DB_PATH.exists():
        return pd.DataFrame(columns=["ship", "dest", "note", "updated_at"])
    with closing(_connect()) as con:
        return pd.read_sql_query("SELECT * FROM ship_master ORDER BY ship", con)


def save_master(df: pd.DataFrame) -> int:
    """선박 기본 양하지 표 전체 저장(빈 양하지는 삭제)."""
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for _, r in df.iterrows():
        ship, dest = clean_ship(r.get("ship")), clean_dest(r.get("dest"))
        if ship and dest:
            note = r.get("note")
            rows.append((ship, dest, "" if note is None or (isinstance(note, float) and np.isnan(note)) else str(note), now))
    with closing(_connect()) as con:
        con.execute("DELETE FROM ship_master")
        con.executemany("INSERT OR REPLACE INTO ship_master VALUES (?,?,?,?)", rows)
        con.commit()
    return len(rows)


def load_voyages() -> pd.DataFrame:
    if not DEST_DB_PATH.exists():
        return pd.DataFrame(columns=["date", "ship", "dest", "source", "updated_at"])
    with closing(_connect()) as con:
        df = pd.read_sql_query("SELECT * FROM ship_voyage ORDER BY date, ship", con)
    df["date"] = pd.to_datetime(df["date"])
    return df


def save_voyages(df: pd.DataFrame, source: str) -> dict:
    """운항(양하지) 기록 저장. 같은 날짜·선박은 새 값으로 갱신."""
    now = datetime.now().isoformat(timespec="seconds")
    old = load_voyages()
    keys_old = set(zip(old["date"].dt.strftime("%Y-%m-%d"), old["ship"])) if len(old) else set()
    rows = [(d.strftime("%Y-%m-%d"), s, t, source, now) for d, s, t in zip(df["date"], df["ship"], df["dest"])]
    with closing(_connect()) as con:
        con.executemany("INSERT OR REPLACE INTO ship_voyage VALUES (?,?,?,?,?)", rows)
        con.commit()
    upd = sum(1 for r in rows if (r[0], r[1]) in keys_old)
    return {"added": len(rows) - upd, "updated": upd}


def clear_voyages() -> None:
    with closing(_connect()) as con:
        con.execute("DELETE FROM ship_voyage")
        con.commit()


# ── 양하지 자료 파일 읽기(열 자동 인식) ───────────────────────────────────
@dataclass
class DestParse:
    kind: str = ""                       # "voyage"(일자 있음) | "master"(선박·양하지만)
    records: pd.DataFrame = field(default_factory=pd.DataFrame)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unknown_ships: dict = field(default_factory=dict)


def _match(headers: list) -> dict:
    nh = [S.norm(h) for h in headers]
    idx = {}
    for role, al in ALIASES.items():
        for a in al:
            j = next((j for j, h in enumerate(nh) if h == a and j not in idx.values()), None)
            if j is not None:
                idx[role] = j
                break
    return idx


def detect_dest(aoa: list[list]) -> dict | None:
    """선박·양하지 열이 있는 표인가? (출하시멘트 LIMS 표는 제외)"""
    if not aoa or S.detect(aoa):
        return None
    for r in range(min(len(aoa), 30)):
        idx = _match([("" if S._blank(c) else c) for c in aoa[r]])
        if "ship" in idx and "dest" in idx:
            return {"header_row": r, "idx": idx}
    return None


def looks_like_dest(content: bytes, filename: str) -> bool:
    try:
        return any(detect_dest(aoa) for _, aoa in S.read_aoa(content, filename))
    except Exception:  # noqa: BLE001 - 읽을 수 없는 파일은 '해당 없음'
        return False


def parse_dest_upload(content: bytes, filename: str, known_ships: set[str] | None = None) -> DestParse:
    try:
        sheets = S.read_aoa(content, filename)
    except Exception as e:  # noqa: BLE001
        return DestParse(errors=[f"파일을 읽지 못했습니다: {e}"])
    known = set(known_ships or ())
    for sn, aoa in sheets:
        det = detect_dest(aoa)
        if not det:
            continue
        idx, hr = det["idx"], det["header_row"]
        recs, skipped = [], 0
        for row in aoa[hr + 1:]:
            if not row or all(S._blank(c) for c in row):
                continue
            def get(k, row=row, idx=idx):
                return row[idx[k]] if k in idx and idx[k] < len(row) else None

            dest = clean_dest(get("dest"))
            # 한 칸에 여러 선박이 쉼표로 적힌 경우도 나눈다
            names = [clean_ship(t, known) for t in S._split_ship_text(str(get("ship") or ""))]
            names = [n for n in names if n]
            d = S._date(get("date")) if "date" in idx else None
            if not names or not dest or ("date" in idx and d is None):
                skipped += 1
                continue
            for n in names:
                recs.append({"date": d, "ship": n, "dest": dest})
        df = pd.DataFrame(recs)
        kind = "voyage" if "date" in idx else "master"
        if df.empty:
            return DestParse(kind=kind, errors=["선박·양하지 값이 있는 행이 없습니다."])
        if kind == "voyage":
            df = df.drop_duplicates(["date", "ship"], keep="last").sort_values(["date", "ship"]).reset_index(drop=True)
        else:
            df = df.drop_duplicates(["ship"], keep="last").sort_values("ship").reset_index(drop=True)
        unknown = {}
        if known:
            for n in df["ship"]:
                if n not in known:
                    unknown[n] = unknown.get(n, 0) + 1
        heads = [("" if S._blank(c) else str(c)) for c in aoa[hr]]
        msgs = [f"시트 ‘{sn}’ · 머리글 {hr + 1}행 · " + ", ".join(f"{lab}←{heads[idx[k]]}" for k, lab in
                                                            (("date", "일자"), ("ship", "선박"), ("dest", "양하지")) if k in idx),
                (f"운항(양하지) 기록 {len(df)}건 · 기간 {df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}" if kind == "voyage"
                 else f"선박 기본 양하지 {len(df)}척(일자 열이 없어 ‘기본값’으로 저장)")
                + (f" · 빈 칸 등으로 건너뜀 {skipped}행" if skipped else ""),
                "양하지: " + ", ".join(f"{k} {v}" for k, v in df["dest"].value_counts().items())]
        if unknown:
            msgs.append("출하시멘트 자료에 없는 선박명(새 배 또는 표기 차이): " + ", ".join(f"{k}({v})" for k, v in unknown.items()))
        return DestParse(kind, df, msgs, [], unknown)
    return DestParse(errors=["선박·양하지 열을 찾지 못했습니다(예: 선박명 / 양하지 [/ 출항일])."])


# ── 출하 기록에 양하지 연결 ─────────────────────────────────────────────
def _hints(v) -> dict:
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return {}


def attach_destinations(df: pd.DataFrame, master: pd.DataFrame | None = None, voyages: pd.DataFrame | None = None,
                        tol_days: int = 1) -> pd.DataFrame:
    """각 출하 기록에 dest(양하지) · dest_src(출처) · dest_detail(선박별) · dests 열을 붙인다."""
    master = load_master() if master is None else master
    voyages = load_voyages() if voyages is None else voyages
    out = df.copy()
    if out.empty:
        for c in ("dest", "dest_src", "dest_detail", "dests"):
            out[c] = pd.Series(dtype=str)
        return out
    mdict = dict(zip(master["ship"], master["dest"])) if len(master) else {}
    vmap: dict[str, list[tuple[pd.Timestamp, str]]] = {}
    for d, s, t in zip(voyages.get("date", []), voyages.get("ship", []), voyages.get("dest", [])):
        vmap.setdefault(s, []).append((pd.Timestamp(d), t))
    tol = pd.Timedelta(days=tol_days)

    def from_voyage(ship: str, date: pd.Timestamp) -> str:
        best, gap = "", None
        for d, t in vmap.get(ship, ()):
            g = abs(d - date)
            if g <= tol and (gap is None or g < gap):
                best, gap = t, g
        return best

    dest, src, detail, dests = [], [], [], []
    hints_col = out["ship_hints"] if "ship_hints" in out else pd.Series([""] * len(out), index=out.index)
    for ships, date, hv, hint_all, n in zip(out["ships"].fillna(""), out["date"], hints_col,
                                             out.get("dest_hint", pd.Series([""] * len(out))).fillna(""), out["n_ship"].fillna(0)):
        names = [x for x in str(ships).split(",") if x]
        hints = _hints(hv)
        if not hints and n == 1 and names and hint_all:          # 예전에 저장된 자료(선박별 주석 없음)
            h = S.dest_from_notes([hint_all])
            if h:
                hints = {names[0]: h}
        res = []
        for s in names:
            t = from_voyage(s, date)
            if t:
                res.append((s, t, "운항기록"))
            elif hints.get(s):
                res.append((s, hints[s], "비고"))
            elif mdict.get(s):
                res.append((s, mdict[s], "기본값"))
            else:
                res.append((s, "", ""))
        got = {t for _, t, _ in res if t}
        if not names or not got:
            dest.append(UNKNOWN)
        elif len(got) > 1:
            dest.append(MIXED)
        elif any(not t for _, t, _ in res):
            dest.append(PARTIAL)
        else:
            dest.append(next(iter(got)))
        srcs = {x for _, t, x in res if t}
        src.append("/".join(x for x in SOURCES if x in srcs) or "-")
        detail.append(", ".join(f"{s}→{t or '?'}" for s, t, _ in res))
        dests.append(",".join(t or "?" for _, t, _ in res))
    out["dest"], out["dest_src"], out["dest_detail"], out["dests"] = dest, src, detail, dests
    return out


def coverage(df: pd.DataFrame) -> dict:
    """양하지 연결 현황."""
    n = len(df)
    single = df[~df["dest"].isin([MIXED, UNKNOWN, PARTIAL])]
    return {"n": n, "single": len(single), "mixed": int((df["dest"] == MIXED).sum()), "unknown": int((df["dest"] == UNKNOWN).sum()),
            "partial": int((df["dest"] == PARTIAL).sum()),
            "by_src": {s: int(df["dest_src"].str.contains(s).sum()) for s in SOURCES},
            "dests": single["dest"].value_counts().to_dict()}


def dest_quality(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """양하지가 하나로 정해진 날짜만 모아 양하지별 평균(추정·분해 없음)."""
    d = df[~df["dest"].isin([MIXED, UNKNOWN, PARTIAL])]
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("dest")
    out = pd.DataFrame({"건수": g.size()})
    for k in keys:
        if k in d:
            out[f"{S.BY_KEY[k].name if k in S.BY_KEY else k} 평균"] = g[k].mean()
    return out.sort_values("건수", ascending=False).reset_index().rename(columns={"dest": "양하지"})


def ship_table(df: pd.DataFrame, master: pd.DataFrame | None = None) -> pd.DataFrame:
    """선박 목록 + 출하 건수 + 비고 주석의 양하지(최다) + 기본 양하지 — 기본값 편집 화면용."""
    master = load_master() if master is None else master
    cnt: dict[str, int] = {}
    hint_cnt: dict[str, dict[str, int]] = {}
    for ships, hv in zip(df.get("ships", pd.Series(dtype=str)).fillna(""), df.get("ship_hints", pd.Series([""] * len(df))).fillna("")):
        for s in [x for x in str(ships).split(",") if x]:
            cnt[s] = cnt.get(s, 0) + 1
        for s, t in _hints(hv).items():
            hint_cnt.setdefault(s, {})
            hint_cnt[s][t] = hint_cnt[s].get(t, 0) + 1
    mdict = {r.ship: (r.dest, r.note) for r in master.itertuples()} if len(master) else {}
    ships = sorted(set(cnt) | set(mdict), key=lambda s: (-cnt.get(s, 0), s))
    rows = []
    for s in ships:
        h = hint_cnt.get(s, {})
        top = max(h, key=h.get) if h else ""
        rows.append({"ship": s, "출하 건수": cnt.get(s, 0), "비고에 적힌 양하지": ", ".join(f"{k}({v})" for k, v in sorted(h.items(), key=lambda x: -x[1])),
                     "추천": top, "dest": mdict.get(s, ("", ""))[0], "note": mdict.get(s, ("", ""))[1]})
    return pd.DataFrame(rows, columns=["ship", "출하 건수", "비고에 적힌 양하지", "추천", "dest", "note"])
