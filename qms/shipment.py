"""출하시멘트(LIMS 일일 로트 표) 분석 모듈.

대상 파일(실제 LIMS 내보내기 구조): 머리글 1줄, 1행 = 채취일 1건(그날 출하분의 대표 시험),
첨가재명칭·석회석비율·첨가재비율·화학성분(XRF)·강도 1/3/7/28일·분말도·주도·Flow·응결시간·비고(출항 선박명).

처리 규칙(실제 파일에서 확인한 사실)
- 시험 항목의 값 0 은 '미시험'(예: 28일 강도는 시험 전)이므로 결측으로 처리한다. 단, 석회석·첨가재 **비율**의 0 은
  '투입 안 함'이라는 실제 값이다(예: 석회석 5% + 첨가재 0%).
- 종결시간은 'HH:MM' 문자열 → 분. 초결 등 숫자 문자열은 숫자로 읽는다.
- 비고 = 그날 출항한 선박명. 1척 = 그 배만 단독 시험한 값, 2척 이상 = 그날 출항한 배들의 평균값(선박별로 나눠 추정하지 않는다).
  괄호 주석(부산·저염 등)을 분리하며 '저염' 표기는 저염 제품 출하를 뜻한다(사용자 확인) → 제품구분(일반/저염/혼재)으로 따로 관리한다.
- 혼합재 합계 = 석회석 비율 + 첨가재 비율. 혼합재 투입량이 줄면 클링커 비율이 올라 강도에 영향을 준다(경험칙, 사용자 제공 지식).

관리기준은 연도별로 수동 입력한다(`data/ship_standards.json`). 해당 연도 값이 없으면 직전 연도 값을 승계하고, 아무것도 없으면 KS 참고값만 표시한다.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .spc import ControlStats, rule_flags
from .standards import DATA_DIR

SHIP_DB_PATH = DATA_DIR / "shipment.db"
SHIP_STANDARDS_PATH = DATA_DIR / "ship_standards.json"
SHIP_MAP_PATH = DATA_DIR / "ship_header_map.json"      # 자동 인식 못 해 사용자가 지정한 열 이름(다음 업로드부터 자동 적용)

KS_REF = "KS L 5201 포틀랜드 시멘트 1종(e나라표준인증·한국시멘트협회 요약, 2026-10 웹 검색 확인 — 원문 대조 권장)"


@dataclass(frozen=True)
class ShipItem:
    key: str
    name: str
    unit: str
    dec: int
    group: str
    aliases: tuple[str, ...]
    hhmm: bool = False          # 'HH:MM' → 분
    zero_ok: bool = False       # 0 이 실제 값(미시험 아님)
    setting: bool = False       # 배합 설정값(판정 제외)
    ks_min: float | None = None
    ks_max: float | None = None
    tip: str = ""


ITEMS: tuple[ShipItem, ...] = (
    ShipItem("ls", "석회석 비율", "%", 1, "배합 구성", ("석회석비율", "석회석혼합률", "석회석혼합비율", "석회석배합률"), zero_ok=True, setting=True),
    ShipItem("addr", "첨가재 비율", "%", 1, "배합 구성", ("첨가재비율", "혼화재비율", "혼합재비율", "첨가재혼합률"), zero_ok=True, setting=True),
    ShipItem("loi", "LOI(강열감량)", "%", 2, "화학성분", ("loi", "강열감량", "강열감량loi"), ks_max=5.0),
    ShipItem("al2o3", "Al₂O₃", "%", 2, "화학성분", ("al2o3", "알루미나", "산화알루미늄")),
    ShipItem("mgo", "MgO", "%", 2, "화학성분", ("mgo", "산화마그네슘"), ks_max=5.0),
    ShipItem("so3", "SO₃(XRF)", "%", 2, "화학성분", ("so3xrf", "xrfso3", "so3"), ks_max=3.5),
    ShipItem("cl", "Cl(XRF)", "ppm", 0, "화학성분", ("clxrf", "xrfcl", "염소xrf", "염화물xrf", "cl"),
             tip="파일에 단위 표기가 없으나 사용자가 ppm으로 확인"),
    ShipItem("ta", "TA(총알칼리)", "%", 2, "화학성분", ("ta", "총알칼리", "전알칼리", "na2oeq", "등가알칼리"),
             tip="Na₂O+0.658·K₂O 와 일치(실제 파일 검증)"),
    ShipItem("s1", "압축강도 1일", "MPa", 1, "강도", ("압축강도1일mpa", "압축강도1일", "1일압축강도", "1일강도", "강도1일")),
    ShipItem("s3", "압축강도 3일", "MPa", 1, "강도", ("압축강도3일mpa", "압축강도3일", "3일압축강도", "3일강도", "강도3일"), ks_min=12.5),
    ShipItem("s7", "압축강도 7일", "MPa", 1, "강도", ("압축강도7일mpa", "압축강도7일", "7일압축강도", "7일강도", "강도7일"), ks_min=22.5),
    ShipItem("s28", "압축강도 28일", "MPa", 1, "강도", ("압축강도28일mpa", "압축강도28일", "28일압축강도", "28일강도", "강도28일"), ks_min=42.5),
    ShipItem("r45", "45㎛ 잔사", "%", 1, "분말도·물성", ("45um", "45um잔사", "45um체잔분", "r45", "45마이크로"), tip="잔사율(%) — 사용자 확인"),
    ShipItem("blaine", "Blaine 분말도", "cm²/g", 0, "분말도·물성", ("blaine", "분말도blaine", "분말도", "블레인"), ks_min=2800.0),
    ShipItem("cons", "주도(표준주도)", "%", 1, "분말도·물성", ("주도", "표준주도", "정상주도", "표준주도수량"), tip="물 사용량(%) — 사용자 확인"),
    ShipItem("flow", "Flow", "", 0, "분말도·물성", ("flow", "플로우", "모르타르flow")),
    ShipItem("fst", "종결시간", "분", 0, "분말도·물성", ("종결시간hhmm", "종결시간", "종결", "finalset"), hhmm=True, ks_max=600.0),
)
BY_KEY = {it.key: it for it in ITEMS}
ITEM_COLS = [it.key for it in ITEMS]
_DEFAULT_ITEMS = ITEMS


def set_item_labels(overrides: dict) -> None:
    """화면 표시 이름·단위를 바꾼다(qms.labels 의 사용자 설정). 기본값에서 다시 만들어 지운 설정은 기본값으로 복귀."""
    global ITEMS
    from dataclasses import replace as _replace
    new = []
    for it in _DEFAULT_ITEMS:
        e = overrides.get(it.key) or {}
        kw = {}
        if e.get("name"):
            kw["name"] = e["name"]
        if "unit" in e:
            kw["unit"] = e["unit"]
        new.append(_replace(it, **kw) if kw else it)
    ITEMS = tuple(new)
    BY_KEY.clear()
    BY_KEY.update({it.key: it for it in ITEMS})
ROLE_ALIASES = {
    "date": ("채취일", "시료채취일", "채취일자", "시료채취일시", "채취일시"),
    "additive": ("첨가재명칭", "첨가재", "첨가재명", "혼화재명칭", "혼합재명칭"),
    "ships": ("비고", "선박", "선박명", "모선", "출항선박"),
    "lot": ("limslotno", "erplotno", "lotno", "로트번호"),
    "product": ("품명", "품종", "제품명", "제품구분", "시멘트종류"),
}
# 품종(1종/3종 등) — LIMS '1종시멘트 벌크' 같은 품명 문자열에서 뽑는다. 비면 1종으로 본다.
# '2종고로슬래그시멘트'는 포틀랜드 2종(중용열)과 다른 고로슬래그 시멘트(KS L 5210) 2종이므로 따로 구분한다.
SLAG2 = "고로슬래그 2종"
SLAG3 = "고로슬래그 3종"
PRODUCTS = ("1종", "3종", SLAG2, SLAG3)   # 출하시멘트 화면에 항상 보이는 품종(사용자 코드표 기준)
_PRODUCT_KEYS = (("고로슬래그3종", SLAG3), ("3종고로", SLAG3), ("슬래그3종", SLAG3), ("고로", SLAG2), ("슬래그", SLAG2), ("1종", "1종"), ("opc", "1종"), ("3종", "3종"), ("조강", "3종"),
                 ("hes", "3종"), ("중용열", "2종"), ("2종", SLAG2), ("4종", "4종"), ("내황산", "5종"), ("5종", "5종"))
# '2종'만 있으면 고로슬래그 2종: 이 공장 LIMS '2종시멘트 벌크' = 고로슬래그 시멘트(첨가재 고로슬래그). 중용열 2종은 '중용열'로 구분


def _product(v, additive=None) -> str:
    """품명 → 품종. 첨가재가 고로슬래그인 '2종'(중용열 표기라도)은 고로슬래그 2종."""
    s = norm(v)
    if not s:
        return "1종"
    for key, code in _PRODUCT_KEYS:
        if norm(key) in s:
            if code == "2종" and "슬래그" in norm(additive):
                return SLAG2
            return code
    return str(v).strip() or "1종"
META_COLS = ["date", "lot", "additive", "mix_total", "n_ship", "ships", "ship_ok", "product_kind", "dest_hint", "ship_raw"]
KINDS = ("일반", "저염", "저염·일반 혼재")
LOW_CL_WORD = "저염"


# ── 머리글 인식 ─────────────────────────────────────────────────────────
def norm(s) -> str:
    """머리글 정규화: NFKC(㎛→μm, 아래첨자→숫자) · 소문자 · 영숫자/한글만."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s)).lower().replace("μ", "u").replace("µ", "u")
    return re.sub(r"[^0-9a-zㄱ-ㆎ가-힣]", "", t)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip()) or v is pd.NaT


def match_headers(headers: list, overrides: dict | None = None) -> dict:
    """{역할/항목 키: 열 번호}. 앞쪽 별칭일수록 우선(더 구체적)."""
    nh = [norm(h) for h in headers]
    idx: dict[str, int] = {}
    used: set[int] = set()

    def take(key: str, aliases) -> None:
        ov = overrides.get(key) if overrides else None
        if isinstance(ov, str):                               # 열 이름으로 지정(열 순서가 바뀌어도 유지)
            j = next((j for j, h in enumerate(nh) if h and h == norm(ov) and j not in used), None)
            if j is not None:
                idx[key] = j
                used.add(j)
                return
        elif ov is not None and ov >= 0:
            idx[key] = int(ov)
            used.add(idx[key])
            return
        for a in aliases:
            for j, h in enumerate(nh):
                if h == a and j not in used:
                    idx[key] = j
                    used.add(j)
                    return

    for role, al in ROLE_ALIASES.items():
        take(role, al)
    for it in ITEMS:
        take(it.key, it.aliases)
    return idx


def detect(aoa: list[list]) -> dict | None:
    """이 시트가 출하시멘트 표인가? 머리글 줄(headerRow)과 인식 열을 돌려준다(아니면 None)."""
    if not aoa or len(aoa) < 3:
        return None
    best = None
    for r in range(min(len(aoa), 40)):
        row = aoa[r]
        if sum(not _blank(c) for c in row) < 8:
            continue
        idx = match_headers([("" if _blank(c) else c) for c in row])
        core = sum(1 for it in ITEMS if it.key in idx)
        score = core + (3 if "date" in idx else 0) + (2 if "additive" in idx else 0) + (1 if "ships" in idx else 0)
        if best is None or score > best["score"]:
            best = {"header_row": r, "idx": idx, "score": score, "core": core}
    if best is None:
        return None
    has_strength = any(k in best["idx"] for k in ("s1", "s3", "s7", "s28"))
    if "date" in best["idx"] and best["core"] >= 8 and (has_strength or "additive" in best["idx"]):
        return best
    return None


# ── 값 해석 ─────────────────────────────────────────────────────────────
def _num(v) -> float | None:
    if _blank(v):
        return None
    if isinstance(v, (bool, np.bool_)):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        return f if np.isfinite(f) else None
    s = str(v).strip()
    if re.fullmatch(r"(?i)n\.?d\.?|nd|n/a|na|-+|—|불검출|미검출", s):
        return None
    s = re.sub(r"^[<>≤≥]\s*", "", s)
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return f if np.isfinite(f) else None


def hhmm_to_min(v) -> float | None:
    if _blank(v):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        if 0 < f < 1:
            return float(round(f * 1440))
        return f if f > 0 else None
    if isinstance(v, (datetime, pd.Timestamp)):
        t = v.hour * 60 + v.minute
        return float(t) if t > 0 else None
    if hasattr(v, "hour") and hasattr(v, "minute"):          # datetime.time
        t = v.hour * 60 + v.minute
        return float(t) if t > 0 else None
    m = re.match(r"^\s*(\d{1,3})\s*[:시]\s*(\d{1,2})", str(v))
    if m:
        t = int(m.group(1)) * 60 + int(m.group(2))
        return float(t) if t > 0 else None
    n = _num(v)
    return n if n and n > 0 else None


def _date(v) -> pd.Timestamp | None:
    if _blank(v):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v).normalize()
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        if 20000 < f < 80000:
            return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(f))).normalize()
        if f == int(f) and 19900101 <= f <= 21001231:
            v = str(int(f))
        else:
            return None
    s = str(v).strip()
    m = re.match(r"^(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", s) or re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if not m:
        return None
    try:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ── 비고(선박) 해석 ─────────────────────────────────────────────────────
def _split_ship_text(text: str) -> list[str]:
    """괄호 밖의 , ， 、 / ; 줄바꿈에서만 나눈다(괄호 안 쉼표는 유지)."""
    out, depth, cur = [], 0, ""
    for ch in str(text):
        if ch in "(（":
            depth += 1
        if ch in ")）":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ",，、/;\n":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _clean_ship(tok: str) -> dict:
    low = LOW_CL_WORD in tok
    notes: list[str] = []

    def grab(m):
        n = re.sub(r"[\s.,，、/;]+", " ", m.group(1).replace(LOW_CL_WORD, " ")).strip()
        if n:
            notes.append(n)
        return ""

    s = re.sub(r"[(（]([^)）]*)[)）]?", grab, tok)
    s = s.replace(LOW_CL_WORD, "")
    s = re.sub(r"[)）]", "", s)
    s = re.sub(r"[\s.·]+", "", s)
    return {"name": s, "notes": notes, "low": low}


def _canon_ship(name: str, vocab: set[str]) -> str:
    if name.endswith("호"):
        return name
    if name + "호" in vocab:
        return name + "호"
    if re.fullmatch(r"[가-힣]+\d+", name):
        return name + "호"
    return name


def _resolve_ships(raw_rows: list[list[dict]]) -> list[dict]:
    """선박명 정규화(‘수성3’→‘수성3호’), 쉼표 없이 붙은 이름은 자주 나오는 선박명(5회 이상)으로 분리."""
    vocab = {t["name"] for toks in raw_rows for t in toks if t["name"].endswith("호")}
    cnt: dict[str, int] = {}
    for toks in raw_rows:
        for t in toks:
            n = _canon_ship(t["name"], vocab)
            cnt[n] = cnt.get(n, 0) + 1
    known = {n for n, c in cnt.items() if n.endswith("호") and c >= 5}
    forms = sorted([(n, n) for n in known] + [(n[:-1], n) for n in known], key=lambda x: -len(x[0]))

    def full_cover(tok: str):
        memo: dict[int, list[str] | None] = {}

        def go(i: int):
            if i == len(tok):
                return []
            if i in memo:
                return memo[i]
            res = None
            for f, n in forms:
                if tok.startswith(f, i):
                    rest = go(i + len(f))
                    if rest is not None:
                        res = [n] + rest
                        break
            memo[i] = res
            return res

        return go(0)

    def partial(tok: str):
        names, i, left = [], 0, ""
        while i < len(tok):
            hit = next(((f, n) for f, n in forms if tok.startswith(f, i)), None)
            if hit:
                names.append(hit[1])
                i += len(hit[0])
            else:
                left += tok[i]
                i += 1
        return names, left

    out = []
    for toks in raw_rows:
        seen: list[str] = []
        ok, notes, lows, hints = True, [], [], {}
        for t in toks:
            notes += t["notes"]
            lows.append(t["low"])
            n = _canon_ship(t["name"], vocab)
            if n in known:
                names = [n]
            else:
                names = full_cover(t["name"])
                if names is None:
                    ok = False
                    names, _ = partial(t["name"])
                    if not names:
                        names = [n]
            for x in names:
                if x not in seen:
                    seen.append(x)
                d = dest_from_notes(t["notes"])
                if d:
                    hints[x] = d                     # 이 선박 이름 바로 뒤 괄호에 적힌 양하지(예: 리나호(부산))
        out.append({"ships": seen, "ok": ok and bool(seen), "notes": list(dict.fromkeys(notes)), "lows": lows, "hints": hints})
    return out


DEST_STOP = {"저염", "수분", "일반", "특수", "벌크", "포대", "샘플", "재시험", "평균"}


def dest_from_notes(notes: list[str]) -> str:
    """괄호 주석에서 양하지 후보(한글 2~5자 지명, 예: 부산·평택). 수분 등 시험 메모는 제외."""
    for n in notes:
        for w in re.split(r"[\s.,·/]+", n):
            if re.fullmatch(r"[가-힣]{2,5}", w) and w not in DEST_STOP:
                return w
    return ""


def _kind(lows: list[bool]) -> str:
    if not lows:
        return "일반"
    if all(lows):
        return "저염"
    return "저염·일반 혼재" if any(lows) else "일반"


# ── 파일 읽기 ───────────────────────────────────────────────────────────
def read_aoa(content: bytes, filename: str) -> list[tuple[str, list[list]]]:
    """업로드 파일 → [(시트명, 2차원 배열)]. 빈 칸은 None."""
    name = filename.lower()
    sheets: list[tuple[str, pd.DataFrame]] = []
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        eng = None if not name.endswith(".xls") else "xlrd"
        raw = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=object, engine=eng)
        sheets = list(raw.items())
    else:
        text = None
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("CSV 문자 인코딩을 읽지 못했습니다(UTF-8/CP949 지원).")
        sep = "\t" if text.count("\t") > text.count(",") else ","
        sheets = [("CSV", pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=object, keep_default_na=False))]
    out = []
    for sn, df in sheets:
        df = df.astype(object).where(df.notna(), None)
        out.append((str(sn), df.values.tolist()))
    return out


@dataclass
class ShipParse:
    records: pd.DataFrame = field(default_factory=pd.DataFrame)
    report: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sheet: str = ""


def looks_like_shipment(content: bytes, filename: str) -> bool:
    try:
        return any(detect(aoa) for _, aoa in read_aoa(content, filename))
    except Exception:  # noqa: BLE001 - 읽을 수 없는 파일은 '해당 없음'
        return False


def parse_aoa(aoa: list[list], overrides: dict | None = None, header_row: int | None = None) -> ShipParse:
    det = detect(aoa)
    hr = header_row if header_row is not None else (det["header_row"] if det else -1)
    if hr < 0:
        return ShipParse(errors=["출하시멘트 형식(채취일·첨가재명칭·강도 등의 열)을 찾지 못했습니다."])
    headers = [("" if _blank(c) else str(c).strip()) for c in aoa[hr]]
    idx = match_headers(headers, overrides)
    if "date" not in idx:
        return ShipParse(errors=["채취일(날짜) 열을 찾지 못했습니다."])
    body = aoa[hr + 1:]
    used = set(idx.values())

    # 추가 항목: 숫자 열 중 0 이 아닌 값이 10건 이상인 나머지 열(상세 화면에서 선택 가능)
    extras: dict[str, int] = {}
    for j, h in enumerate(headers):
        if not h or j in used or j == 0:
            continue
        vals = [r[j] for r in body if j < len(r) and not _blank(r[j])]
        nums = [_num(v) for v in vals]
        nn = [x for x in nums if x is not None]
        if vals and len(nn) / len(vals) >= 0.9 and sum(1 for x in nn if x != 0) >= 10:
            extras[h] = j

    recs, ship_tokens, skipped, zeros = [], [], 0, {}
    for r in body:
        if not r or all(_blank(c) for c in r):
            continue
        def get(k, r=r):
            return r[idx[k]] if k in idx and idx[k] < len(r) else None

        d = _date(get("date"))
        if d is None:
            skipped += 1
            continue
        rec = {"date": d, "lot": "" if _blank(get("lot")) else str(get("lot")).strip(),
               "additive": "" if _blank(get("additive")) else str(get("additive")).strip(),
               "product": _product(get("product"), get("additive")),
               "ship_raw": re.sub(r"\s+", " ", str(get("ships"))).strip() if not _blank(get("ships")) else ""}
        for it in ITEMS:
            if it.key not in idx:
                rec[it.key] = None
                continue
            v = hhmm_to_min(get(it.key)) if it.hhmm else _num(get(it.key))
            if v is not None and (v < 0 or (v == 0 and not it.zero_ok)):
                zeros[it.key] = zeros.get(it.key, 0) + 1
                v = None
            rec[it.key] = v
        ex = {}
        for h, j in extras.items():
            v = _num(r[j]) if j < len(r) else None
            if v is not None and v > 0:
                ex[h] = v
            elif v == 0:
                zeros[f"x:{h}"] = zeros.get(f"x:{h}", 0) + 1
        rec["extra"] = json.dumps(ex, ensure_ascii=False)
        toks = [_clean_ship(t) for t in _split_ship_text(rec["ship_raw"])] if rec["ship_raw"] else []
        ship_tokens.append([t for t in toks if t["name"]])
        recs.append(rec)

    res = _resolve_ships(ship_tokens)
    unsure, ship_count, unknown = [], {}, {}
    for rec, rs in zip(recs, res):
        rec["ships"] = ",".join(rs["ships"])
        rec["n_ship"] = len(rs["ships"])
        rec["ship_ok"] = bool(rs["ok"])
        rec["product_kind"] = _kind(rs["lows"])
        rec["dest_hint"] = "/".join(rs["notes"])      # 괄호 주석 원문(부산·평택·저염 등)
        rec["ship_hints"] = json.dumps(rs["hints"], ensure_ascii=False)   # {선박: 주석의 양하지} — 양하지 자동 연결에 사용
        if rec["ship_raw"] and not rs["ok"]:
            unsure.append({"date": rec["date"].strftime("%Y-%m-%d"), "raw": rec["ship_raw"]})
        for n in rs["ships"]:
            ship_count[n] = ship_count.get(n, 0) + 1
    df = pd.DataFrame(recs)
    if df.empty:
        return ShipParse(errors=["읽을 수 있는 행이 없습니다(채취일이 비어 있음)."])
    df["mix_total"] = df["ls"].fillna(0) + df["addr"].fillna(0)
    df.loc[df["ls"].isna() & df["addr"].isna(), "mix_total"] = np.nan
    # 같은 LOT(없으면 날짜) 중복 → 나중 행이 우선
    df["_k"] = _key_series(df)
    dup = int(df.duplicated("_k", keep="last").sum())
    df = df.drop_duplicates("_k", keep="last").drop(columns="_k").sort_values("date").reset_index(drop=True)
    known_ships = {n for n, c in ship_count.items() if c >= 5}
    for n, c in ship_count.items():
        if n not in known_ships:
            unknown[n] = c
    found = [(it.key, headers[idx[it.key]]) for it in ITEMS if it.key in idx]
    report = {
        "header_row": hr, "rows": len(df), "skipped": skipped, "duplicates": dup,
        "period": (df["date"].min(), df["date"].max()), "found": found,
        "missing": [it.key for it in ITEMS if it.key not in idx], "zeros": zeros,
        "ship_count": ship_count, "unknown_ships": unknown, "ship_unsure": unsure,
        "n_single": int(((df["n_ship"] == 1) & df["ship_ok"]).sum()),
        "kinds": df["product_kind"].value_counts().to_dict(), "extras": list(extras), "headers": headers, "idx": idx,
    }
    msgs = [
        f"읽은 행 {len(df)}건 · 머리글 {hr + 1}행 · 기간 {report['period'][0]:%Y-%m-%d} ~ {report['period'][1]:%Y-%m-%d}"
        + (f" · 날짜가 없어 건너뜀 {skipped}행" if skipped else ""),
        f"인식한 항목 {len(found)}개: " + ", ".join(f"{BY_KEY[k].name}←{h}" for k, h in found),
    ]
    zk = [f"{BY_KEY[k].name} {v}건" for k, v in zeros.items() if not k.startswith("x:")]
    if zk:
        msgs.append("값 0 = ‘미시험’으로 보고 계산에서 제외: " + ", ".join(zk))
    if report["missing"]:
        msgs.append("찾지 못한 항목: " + ", ".join(BY_KEY[k].name for k in report["missing"]))
    msgs.append(f"비고(선박) 해석: 선박 {len(known_ships)}척, 1모선 단독 시험 {report['n_single']}건, 제품구분 "
                + " · ".join(f"{k} {v}건" for k, v in report["kinds"].items()))
    if unsure:
        msgs.append(f"비고를 확신하지 못한 {len(unsure)}건은 ‘모선 수’ 분석에서 제외 표시: "
                    + ", ".join(f"{u['date']} “{u['raw']}”" for u in unsure[:4]))
    return ShipParse(df, report, msgs, [])


def load_header_map() -> dict:
    try:
        return json.loads(SHIP_MAP_PATH.read_text(encoding="utf-8")) if SHIP_MAP_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def remember_header_map(mapping: dict) -> None:
    """{항목 키: 파일의 열 이름} 을 기억한다."""
    cur = load_header_map()
    cur.update({k: v for k, v in mapping.items() if isinstance(v, str) and v})
    SHIP_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHIP_MAP_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_upload(content: bytes, filename: str, overrides: dict | None = None) -> ShipParse:
    overrides = {**load_header_map(), **(overrides or {})}
    try:
        sheets = read_aoa(content, filename)
    except Exception as e:  # noqa: BLE001 - 사용자에게 읽기 실패 사유 전달
        return ShipParse(errors=[f"파일을 읽지 못했습니다: {e}"])
    for sn, aoa in sheets:
        if detect(aoa):
            p = parse_aoa(aoa, overrides)
            p.sheet = sn
            return p
    return ShipParse(errors=["출하시멘트 형식을 찾지 못했습니다(채취일·첨가재명칭·압축강도 등의 열 이름이 필요)."])


# ── 저장(SQLite, 열 단위 병합) ──────────────────────────────────────────
def _connect():
    SHIP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(SHIP_DB_PATH)


def shipment_mtime() -> float:
    return SHIP_DB_PATH.stat().st_mtime if SHIP_DB_PATH.exists() else 0.0


def _key_series(df: pd.DataFrame) -> pd.Series:
    """중복 판정 키: LOT 번호, 없으면 '날짜|품종'(같은 날 1종·3종이 서로 덮어쓰지 않게)."""
    prod = df["product"].fillna("1종").astype(str) if "product" in df else pd.Series("1종", index=df.index)
    by_date = df["date"].dt.strftime("%Y-%m-%d") + "|" + prod
    return pd.Series(np.where(df["lot"].fillna("") != "", df["lot"], by_date), index=df.index)


def load_shipment_raw() -> pd.DataFrame:
    if not SHIP_DB_PATH.exists():
        return pd.DataFrame(columns=["date"])
    with closing(_connect()) as con:
        try:
            df = pd.read_sql_query("SELECT * FROM shipment", con, parse_dates=["date"])
        except Exception:  # noqa: BLE001 - 표가 아직 없으면 빈 자료
            return pd.DataFrame(columns=["date"])
    if "ship_ok" in df:
        df["ship_ok"] = df["ship_ok"].astype(bool)
    return df.sort_values("date").reset_index(drop=True)


def save_shipment(new: pd.DataFrame) -> dict:
    """같은 LOT(없으면 날짜)는 새 파일 값으로 갱신하되, 새 파일에서 빈 칸(미시험)인 항목은 기존 값을 유지한다."""
    old = load_shipment_raw()
    cols = ["date", "lot", "additive", "product", *ITEM_COLS, "mix_total", "n_ship", "ships", "ship_ok", "product_kind",
            "dest_hint", "ship_hints", "ship_raw", "extra"]
    if "ship_hints" not in new:
        new = new.assign(ship_hints="{}")
    if "product" not in new:
        new = new.assign(product="1종")
    new = new[cols].copy()
    new["_k"] = _key_series(new)
    if old.empty or "lot" not in old:
        merged, added, updated = new, len(new), 0
    else:
        old = old[[c for c in cols if c in old.columns]].copy()
        old["_k"] = _key_series(old)
        om = old.set_index("_k")
        rows, added, updated = [], 0, 0
        seen = set()
        for _, r in new.iterrows():
            k = r["_k"]
            seen.add(k)
            if k in om.index:
                updated += 1
                o = om.loc[k]
                r = r.copy()
                for c in ITEM_COLS:
                    if pd.isna(r[c]) and c in o.index and not pd.isna(o[c]):
                        r[c] = o[c]
                ex_o = json.loads(o["extra"]) if isinstance(o.get("extra"), str) and o["extra"] else {}
                ex_n = json.loads(r["extra"]) if isinstance(r["extra"], str) and r["extra"] else {}
                r["extra"] = json.dumps({**ex_o, **ex_n}, ensure_ascii=False)
                if not r["additive"] and isinstance(o.get("additive"), str):
                    r["additive"] = o["additive"]
            else:
                added += 1
            rows.append(r)
        keep = old[~old["_k"].isin(seen)]
        merged = pd.concat([keep, pd.DataFrame(rows)], ignore_index=True)
    merged = merged.drop(columns="_k", errors="ignore")
    merged["mix_total"] = merged["ls"].fillna(0) + merged["addr"].fillna(0)
    merged.loc[merged["ls"].isna() & merged["addr"].isna(), "mix_total"] = np.nan
    merged = merged.sort_values("date").reset_index(drop=True)
    out = merged.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out["ship_ok"] = out["ship_ok"].astype(int)
    with closing(_connect()) as con:
        out.to_sql("shipment", con, if_exists="replace", index=False)
        con.commit()
    return {"added": added, "updated": updated, "total": len(merged)}


def clear_shipment() -> None:
    SHIP_DB_PATH.unlink(missing_ok=True)


def load_shipment() -> pd.DataFrame:
    """저장된 자료(추가 항목은 'x:열이름' 열로 펼침)."""
    df = load_shipment_raw()
    if df.empty or "extra" not in df:
        return df
    if "product" not in df.columns:                 # 예전 저장본 호환: 품종 없으면 1종
        df["product"] = "1종"
    else:
        df["product"] = df["product"].fillna("1종").replace("", "1종")
    ex = df["extra"].apply(lambda s: json.loads(s) if isinstance(s, str) and s else {})
    exdf = pd.DataFrame(list(ex)).add_prefix("x:") if len(ex) else pd.DataFrame(index=df.index)
    return pd.concat([df.drop(columns="extra"), exdf], axis=1)


def extra_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("x:")]


# ── 연도별 관리기준(수동 입력) ──────────────────────────────────────────
LIMIT_FIELDS = ("lsl", "usl", "target", "ks_min", "ks_max")


def load_ship_standards() -> dict:
    if SHIP_STANDARDS_PATH.exists():
        try:
            return json.loads(SHIP_STANDARDS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"version": 1, "years": {}}


def save_ship_standards(std: dict) -> None:
    SHIP_STANDARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHIP_STANDARDS_PATH.write_text(json.dumps(std, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


# 품종별 KS 참고값(1종과 다른 항목만). 3종 = KS L 5201 조강 포틀랜드 시멘트(공정 데이터 기준표 standards.py 와 같은 값).
KS_BY_PRODUCT = {
    "3종": {"so3": (None, 4.5), "blaine": (3300.0, None), "s1": (10.0, None), "s3": (20.0, None), "s7": (32.5, None),
            "s28": (47.5, None)},
}
# 고로슬래그 시멘트(KS L 5210)는 KS 값을 아직 확인·입력하지 않았다 → 1종 값을 잘못 쓰지 않도록 KS 판정 생략(사내 기준만).
KS_NOT_SET = {SLAG2, SLAG3}


def years_key(product: str | None = None) -> str:
    """품종별 기준 저장 위치. 1종은 예전 저장본('years')을 그대로 쓴다(하위 호환)."""
    return "years" if product in (None, "", "1종", "전체") else f"years@{product}"


def ks_default(key: str, product: str | None = None) -> dict:
    if product in KS_NOT_SET:
        return {"ks_min": None, "ks_max": None}
    over = KS_BY_PRODUCT.get(product or "", {}).get(key)
    if over is not None:
        return {"ks_min": over[0], "ks_max": over[1]}
    it = BY_KEY.get(key)
    return {"ks_min": it.ks_min if it else None, "ks_max": it.ks_max if it else None}


def effective_limits(std: dict, key: str, year: int, product: str | None = None) -> dict:
    """해당 연도·품종의 기준. 그 연도에 저장된 값이 없으면 직전 연도 값을 승계, 없으면 KS 참고값만."""
    yk = years_key(product)
    years = sorted(int(y) for y in std.get(yk, {}) if str(y).isdigit())
    for y in reversed([y for y in years if y <= year]):
        e = std[yk][str(y)].get(key)
        if e is not None:
            return {**{f: _clean(e.get(f)) for f in LIMIT_FIELDS}, "note": e.get("note", ""), "from_year": y}
    return {"lsl": None, "usl": None, "target": None, **ks_default(key, product), "note": "", "from_year": None}


def year_table(std: dict, year: int, product: str | None = None) -> pd.DataFrame:
    """편집용 표(항목별 1행). 저장 안 된 연도는 직전 연도 값을 승계해 보여 준다."""
    rows = []
    yk = years_key(product)
    for it in ITEMS:
        e = effective_limits(std, it.key, year, product)
        own = str(year) in std.get(yk, {}) and it.key in std[yk][str(year)]
        rows.append({"key": it.key, "항목": it.name, "단위": it.unit, "KS 하한": e["ks_min"], "KS 상한": e["ks_max"],
                     "사내 하한": e["lsl"], "사내 상한": e["usl"], "목표": e["target"], "비고(변경 사유 등)": e["note"],
                     "출처": f"{year}년 입력" if own else (f"{e['from_year']}년 승계" if e["from_year"] else "KS 참고값")})
    return pd.DataFrame(rows)


def save_year(std: dict, year: int, table: pd.DataFrame, product: str | None = None) -> dict:
    ys = std.setdefault(years_key(product), {})
    ent = {}
    for _, r in table.iterrows():
        ent[r["key"]] = {"ks_min": _clean(r["KS 하한"]), "ks_max": _clean(r["KS 상한"]), "lsl": _clean(r["사내 하한"]),
                         "usl": _clean(r["사내 상한"]), "target": _clean(r["목표"]),
                         "note": "" if pd.isna(r["비고(변경 사유 등)"]) else str(r["비고(변경 사유 등)"])}
    ys[str(year)] = ent
    std["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_ship_standards(std)
    return std


def limits_frame(std: dict, df: pd.DataFrame, key: str) -> pd.DataFrame:
    """각 행(채취일의 연도·품종)에 맞는 기준값을 붙인 표 — 연도가 바뀌면 기준선도 계단식으로 바뀐다."""
    years = df["date"].dt.year
    prods = df["product"].fillna("1종").astype(str) if "product" in df else pd.Series("1종", index=df.index)
    cache: dict = {}
    for y, p in set(zip(years.dropna().astype(int), prods)):
        cache[(y, p)] = effective_limits(std, key, int(y), p)
    out = pd.DataFrame({f: [cache[(int(y), p)][f] if (not pd.isna(y) and (int(y), p) in cache) else None
                            for y, p in zip(years, prods)] for f in LIMIT_FIELDS}, index=df.index)
    return out.astype(float)


# ── 필터·판정·통계 ──────────────────────────────────────────────────────
def apply_filters(df: pd.DataFrame, start=None, end=None, additive: str | None = None, mode: str = "전체",
                  kind: str = "일반 제품만", dest: str | None = None, product: str | None = None) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if start is not None:
        m &= df["date"] >= pd.Timestamp(start)
    if end is not None:
        m &= df["date"] <= pd.Timestamp(end)
    if product and product != "전체" and "product" in df:
        m &= df["product"] == product
    if additive:
        m &= df["additive"] == additive
    if mode == "1모선 단독 시험만":
        m &= (df["n_ship"] == 1) & df["ship_ok"]
    elif mode == "2모선 이상(평균값)만":
        m &= df["n_ship"] >= 2
    if kind == "일반 제품만":
        m &= df["product_kind"] == "일반"
    elif kind == "저염 제품만":
        m &= df["product_kind"] == "저염"
    if dest and "dest" in df:
        m &= df["dest"] == dest
    return df[m].reset_index(drop=True)


@dataclass
class ItemJudge:
    key: str
    n: int
    series: pd.Series
    stats: ControlStats | None
    ks_out: pd.Series
    plant_out: pd.Series
    r1: np.ndarray
    r2: np.ndarray
    limits: pd.DataFrame
    status: str
    label: str


def judge_item(df: pd.DataFrame, key: str, std: dict, tail: int = 10) -> ItemJudge:
    """항목 판정: KS(위험) → 사내 기준(경고) → 관리한계·연속 치우침(주의), 최근 tail 건 기준. 기준은 각 행의 연도 기준."""
    sub = df[df[key].notna()].sort_values("date")
    s = pd.Series(sub[key].astype(float).values, index=pd.DatetimeIndex(sub["date"]))
    lim = limits_frame(std, sub, key)
    lim.index = s.index if len(s) else lim.index
    v = s.to_numpy()
    ks_out = ((lim["ks_min"].notna() & (s < lim["ks_min"])) | (lim["ks_max"].notna() & (s > lim["ks_max"]))) if len(s) else pd.Series(dtype=bool)
    plant_out = ((lim["lsl"].notna() & (s < lim["lsl"])) | (lim["usl"].notna() & (s > lim["usl"]))) if len(s) else pd.Series(dtype=bool)
    stats = None
    r1 = r2 = np.zeros(len(v), dtype=bool)
    if len(v) >= 5:
        sd = float(np.std(v, ddof=1))
        if sd > 0:
            stats = ControlStats(center=float(np.mean(v)), sigma=sd, sigma_within=sd, n=len(v), base_start=s.index.min(), base_end=s.index.max())
            fl = rule_flags(v, stats, ("R1", "R2"))
            r1, r2 = fl["R1"], fl["R2"]
    it = BY_KEY.get(key)
    if it is not None and it.setting:
        status, label = "설정값", "배합 설정값(판정 제외)"
    elif len(v) < 5:
        status, label = "자료 부족", "자료 5건 미만"
    elif ks_out.tail(tail).any():
        status, label = "위험", f"최근 {tail}건 중 KS 기준 이탈"
    elif plant_out.tail(tail).any():
        status, label = "경고", f"최근 {tail}건 중 사내 관리기준 이탈"
    elif r1[-tail:].any():
        status, label = "주의", f"최근 {tail}건 중 관리한계(±3σ) 이탈"
    elif r2[-tail:].any():
        status, label = "참고", "중심선 한쪽 9점 연속(참고)"
    else:
        status, label = "정상", "정상"
    return ItemJudge(key, len(v), s, stats, ks_out, plant_out, r1, r2, lim, status, label)


STATUS_ICON = {"위험": "🔴", "경고": "🟠", "주의": "🟡", "참고": "🔵", "정상": "🟢", "설정값": "⚪", "자료 부족": "⚪"}


def summary_table(df: pd.DataFrame, std: dict, keys: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for it in ITEMS:
        if keys and it.key not in keys:
            continue
        if it.key not in df.columns or df[it.key].notna().sum() == 0:
            continue
        j = judge_item(df, it.key, std)
        s = j.series
        last = s.iloc[-1] if len(s) else np.nan
        cur = j.limits.iloc[-1] if len(s) else None
        rows.append({
            "판정": f"{STATUS_ICON[j.status]} {j.status}", "항목": it.name, "단위": it.unit, "그룹": it.group, "key": it.key,
            "최근값": last, "최근 채취일": s.index[-1] if len(s) else pd.NaT,
            "평균": float(s.mean()) if len(s) else np.nan, "표준편차": float(s.std(ddof=1)) if len(s) > 1 else np.nan,
            "최소": float(s.min()) if len(s) else np.nan, "최대": float(s.max()) if len(s) else np.nan,
            "KS 하한": cur["ks_min"] if cur is not None else np.nan, "KS 상한": cur["ks_max"] if cur is not None else np.nan,
            "사내 하한": cur["lsl"] if cur is not None else np.nan, "사내 상한": cur["usl"] if cur is not None else np.nan,
            "목표": cur["target"] if cur is not None else np.nan,
            "KS 이탈(건)": int(j.ks_out.sum()), "사내 이탈(건)": int(j.plant_out.sum()), "관리한계 이탈(건)": int(j.r1.sum()),
            "시험 건수": j.n, "미시험(건)": int(len(df) - j.n), "상태 설명": j.label,
        })
    out = pd.DataFrame(rows)
    for c in ("최근값", "평균", "표준편차", "최소", "최대", "KS 하한", "KS 상한", "사내 하한", "사내 상한", "목표"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


# ── 혼합재(석회석+첨가재) ↔ 강도 ────────────────────────────────────────
STRENGTH_KEYS = ("s1", "s3", "s7", "s28")
MIX_KNOWLEDGE = (
    "혼합재(석회석+첨가재) 투입량이 줄면 같은 양의 시멘트 안에 클링커 비율이 늘어 강도가 달라진다(사용자 제공 지식 + 경험칙). "
    "예: 혼합재 10% 설계에서 실제 투입이 8%·7%·5%로 줄어드는 경우. 일반적으로 클링커 비율↑ → 초기·28일 강도↑, "
    "반대로 혼합재↑ → 강도↓(희석 효과). 플라이애시·고로슬래그는 장기강도에 기여하나 초기강도는 낮아 재령별 영향 크기가 다르다."
)


def composition_table(df: pd.DataFrame) -> pd.DataFrame:
    """(첨가재, 석회석%, 첨가재%) 조합별 평균 — 배합이 바뀐 시점 비교."""
    d = df[df["mix_total"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    g = d.groupby(["additive", "ls", "addr"], dropna=False)
    out = g.agg(건수=("date", "size"), 시작=("date", "min"), 종료=("date", "max"), 혼합재합계=("mix_total", "first"),
                **{BY_KEY[k].name: (k, "mean") for k in (*STRENGTH_KEYS, "blaine", "so3") if k in d.columns}).reset_index()
    return out.rename(columns={"additive": "첨가재", "ls": "석회석(%)", "addr": "첨가재(%)"}).sort_values("시작").reset_index(drop=True)


def mix_changes(df: pd.DataFrame, min_run: int = 5, window: int = 20) -> pd.DataFrame:
    """혼합재 합계가 바뀐 시점별 전·후 강도 비교. 짧은 구간(min_run 건 미만)은 잡음으로 보고 앞 구간에 합친다."""
    d = df[df["mix_total"].notna()].sort_values("date").reset_index(drop=True)
    if len(d) < 2 * min_run:
        return pd.DataFrame()
    seg = (d["mix_total"] != d["mix_total"].shift()).cumsum()
    runs = d.groupby(seg).agg(start=("date", "min"), mix=("mix_total", "first"), n=("date", "size"), i0=("date", lambda x: x.index[0]))
    runs = runs[runs["n"] >= min_run].reset_index(drop=True)
    rows = []
    for a, b in zip(runs.index[:-1], runs.index[1:]):
        r0, r1 = runs.loc[a], runs.loc[b]
        if r0["mix"] == r1["mix"]:
            continue
        i1 = int(r1["i0"])
        before, after = d.iloc[max(0, i1 - window):i1], d.iloc[i1:i1 + window]
        row = {"변경일": r1["start"], "혼합재 합계(전→후, %)": f"{r0['mix']:g} → {r1['mix']:g}", "변화(%p)": r1["mix"] - r0["mix"],
               "전 건수": len(before), "후 건수": len(after)}
        for k in STRENGTH_KEYS:
            if k in d.columns:
                bm, am = before[k].mean(), after[k].mean()
                row[f"{BY_KEY[k].name} 변화(MPa)"] = am - bm if pd.notna(bm) and pd.notna(am) else np.nan
        dv = row.get("압축강도 28일 변화(MPa)", np.nan)
        # 경험칙: 혼합재↓(클링커↑) → 강도↑, 혼합재↑ → 강도↓
        row["28일 강도 방향(경험칙 대비)"] = "-" if pd.isna(dv) or row["변화(%p)"] == 0 else ("✔ 예상과 같은 방향" if dv * -row["변화(%p)"] > 0 else "✖ 예상과 반대(다른 요인 확인)")
        rows.append(row)
    return pd.DataFrame(rows)


def mix_effect(df: pd.DataFrame, key: str, controls: tuple[str, ...] = ("blaine", "so3"), split: bool = False) -> dict | None:
    """key ~ 혼합재 합계 (+ 첨가재 종류 더미 + 분말도·SO₃) 최소제곱 추정. 혼합재 1%p 변화당 강도 변화(MPa) — 추정치.
    split=True 이면 혼합재 합계 대신 석회석 비율·첨가재 비율을 따로 추정한다(석회석=충전재, 첨가재=포졸란·슬래그 성격이 달라서)."""
    cols = ["mix_total", "ls", "addr", key, "additive", *controls]
    d = df[cols].dropna(subset=["mix_total", key]).copy()
    for c in controls:
        d = d[d[c].notna()]
    if len(d) < 30 or d["mix_total"].nunique() < 2:
        return None
    if split:
        X = [np.ones(len(d)), d["ls"].to_numpy(float), d["addr"].to_numpy(float)]
        names = ["절편", "석회석 비율(%p당)", "첨가재 비율(%p당)"]
    else:
        X = [np.ones(len(d)), d["mix_total"].to_numpy(float)]
        names = ["절편", "혼합재 합계(%p당)"]
    adds = sorted(d["additive"].unique())
    for a in (adds[1:] if len(adds) > 1 else []):
        X.append((d["additive"] == a).to_numpy(float))
        names.append(f"첨가재={a}")
    for c in controls:
        X.append(d[c].to_numpy(float))
        names.append(BY_KEY[c].name)
    A = np.column_stack(X)
    y = d[key].to_numpy(float)
    ok = np.isfinite(A).all(axis=1) & np.isfinite(y)              # 석회석·첨가재 비율이 빈 행 등(NaN)은 제외 — 남기면 SVD 미수렴 오류
    A, y = A[ok], y[ok]
    if len(y) < 30 or len(y) <= A.shape[1] or not np.ptp(A[:, 1:3], axis=0).any():
        return None
    try:
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    resid = y - A @ beta
    dof = len(y) - A.shape[1]
    sigma2 = float(resid @ resid) / dof if dof > 0 else np.nan
    try:
        cov = sigma2 * np.linalg.pinv(A.T @ A)
    except np.linalg.LinAlgError:
        return None
    se = np.sqrt(np.abs(np.diag(cov)))
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(resid @ resid) / sst if sst > 0 else np.nan
    return {"n": len(y), "r2": r2, "coef": dict(zip(names, beta)), "se": dict(zip(names, se)), "mix_coef": float(beta[1]),
            "mix_se": float(se[1]), "controls": [BY_KEY[c].name for c in controls], "split": split}
