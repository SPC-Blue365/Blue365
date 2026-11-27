#!/usr/bin/env python3
"""Blue365 시멘트 공정 3D — 사내망 팀 공유 서버

파이썬 표준 라이브러리만 사용합니다(추가 설치 없음, 인터넷 불필요).

  python server.py                         → 서버 창에 표시되는 http://<이 PC IP>:8365 로 팀원 접속
  python server.py --watch "\\\\서버\\품질\\업로드"   → 공유 폴더의 최신 .xlsx 자동 반영
  python server.py --key 암호                → (선택) 업로드에 서버 공통 암호를 하나 더 요구
  로그인 필수: 처음에는 이 PC에서 http://localhost:8365 로 관리자 계정을 만듭니다. 업로드는 편집 권한 + 본인 비밀번호 재확인

하는 일
  GET  /login            로그인 · ID 등록 (승인 후 로그인)
  GET  /account          내 계정 · (관리자) 사용자 승인·권한 관리
  GET  /                 화면(cement_plant_3d.html) — 로그인 필요
  GET  /업로드양식.xlsx    업로드 양식
  GET  /api/status       서버 상태와 최신 데이터 버전
  GET  /api/dataset      최신 데이터(JSON)
  GET/POST /api/settings 관리기준 (f-CaO·KS·사내 기준) — 바꾸기는 관리자만, data/settings.json 에 저장
  POST /api/dataset      화면에서 올린 데이터 저장 → 모든 접속자에게 20초 안에 반영
  저장 위치: data/latest.json, 이력은 data/history/ (최근 200개 · 최대 1GB 보관, --history-mb 로 변경)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "cement_plant_3d.html"
TEMPLATE = ROOT / "업로드양식.xlsx"
# 화면이 받는 데이터: 업로드는 집계된 QMS 데이터셋(qms), 공유 폴더 자동 읽기는 원본 시트(sheets) — 화면이 집계함
MAX_BODY = 30 * 1024 * 1024  # 화면에서 25MB 파일을 JSON으로 바꾸면 조금 커짐
KEEP_HISTORY = 200
HISTORY_MB = 1024            # data/history 최대 용량 (MB). --history-mb 로 변경

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


# ---------------------------------------------------------------- 엑셀 읽기
def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _put(lst: list, i: int, v) -> None:
    while len(lst) <= i:
        lst.append(None)
    lst[i] = v


def read_xlsx(data: bytes) -> dict[str, list[list]]:
    """.xlsx → {시트명: 2차원 값 목록}. 화면(qms.js)의 읽기 결과와 같은 모양. 큰 시트도 스트리밍으로 읽음."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        sst: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si"):
                sst.append("".join(t.text or "" for t in si.iter(NS + "t") if t is not None))
        rels = {r.get("Id"): r.get("Target", "") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PNS + "Relationship")}
        out: dict[str, list[list]] = {}
        for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet"):
            target = rels.get(sh.get(RNS + "id"), "").lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            if target not in names:
                continue
            rows: list[list] = []
            with z.open(target) as f:
                rn = 0
                for ev, el in ET.iterparse(f, events=("end",)):
                    if el.tag != NS + "row":
                        continue
                    ri = int(el.get("r", rn + 1)) - 1
                    rn = ri + 1
                    vals: list = []
                    for cn, c in enumerate(el.iter(NS + "c")):
                        ci = _col(c.get("r")) if c.get("r") else cn
                        t, v = c.get("t"), c.find(NS + "v")
                        if t == "s":
                            val = sst[int(v.text)] if v is not None and v.text else None
                        elif t == "inlineStr":
                            val = "".join(x.text or "" for x in c.iter(NS + "t"))
                        elif t == "b":
                            val = v is not None and v.text == "1"
                        elif t in ("str", "e"):
                            val = v.text if v is not None else None
                        elif v is None or not v.text:
                            val = None
                        else:
                            fv = float(v.text)
                            val = int(fv) if fv.is_integer() else fv
                        _put(vals, ci, val)
                    if vals:
                        _put(rows, ri, vals)
                    el.clear()
            out[sh.get("name")] = [r or [] for r in rows]
        return out


# ---------------------------------------------------------------- 저장소
class Store:
    def __init__(self, folder: Path):
        self.dir = folder
        self.hist = folder / "history"
        self.hist.mkdir(parents=True, exist_ok=True)
        self.latest = folder / "latest.json"
        self.lock = threading.Lock()
        self.meta = None
        if self.latest.exists():
            try:
                self.meta = json.loads(self.latest.read_text("utf-8"))["meta"]
            except Exception:  # 손상된 파일은 무시하고 새로 받음
                self.meta = None

    def save(self, payload, meta: dict, kind: str = "sheets") -> dict:
        """kind='qms': 화면이 집계한 QMS 데이터셋 / kind='sheets': 공유 폴더 원본 시트(화면이 집계)"""
        if kind == "qms":
            if not isinstance(payload, dict) or not isinstance(payload.get("streams"), dict):
                raise ValueError("QMS 데이터 형식이 올바르지 않습니다")
        else:
            if not isinstance(payload, dict) or not payload:
                raise ValueError("시트가 없습니다")
            for k, v in payload.items():
                if not isinstance(k, str) or not isinstance(v, list) or not all(isinstance(r, list) for r in v):
                    raise ValueError("시트 형식이 올바르지 않습니다")
        now = dt.datetime.now()
        meta = {
            "fileName": str(meta.get("fileName", ""))[:200],
            "uploadedBy": str(meta.get("uploadedBy", "")).strip()[:40] or "이름 없음",
            "uploadedAt": now.isoformat(timespec="seconds"),
            "source": str(meta.get("source", "upload"))[:20],
            "version": now.strftime("%Y%m%d%H%M%S%f"),
        }
        doc = json.dumps({"meta": meta, kind: payload}, ensure_ascii=False)
        with self.lock:
            tmp = self.latest.with_suffix(".tmp")
            tmp.write_text(doc, "utf-8")
            os.replace(tmp, self.latest)
            (self.hist / f"{meta['version']}.json").write_text(doc, "utf-8")
            files = sorted(self.hist.glob("*.json"))
            for f in files[:-KEEP_HISTORY]:                 # 개수 상한
                f.unlink(missing_ok=True)
            files = files[-KEEP_HISTORY:]
            total = sum(f.stat().st_size for f in files)
            while len(files) > 5 and total > HISTORY_MB * 1024 * 1024:   # 용량 상한 (최근 5개는 항상 보관)
                total -= files[0].stat().st_size
                files.pop(0).unlink(missing_ok=True)
            self.meta = meta
        return meta

    def read(self) -> bytes | None:
        with self.lock:
            return self.latest.read_bytes() if self.latest.exists() else None


STORE: Store
KEY = ""
_PB = {"m": None, "v": None}
SETTINGS_LOCK = threading.Lock()


def sokbo_path() -> Path:
    return STORE.dir / "sokbo.json"


def sokbo_read():
    """출하속보(화면이 PDF에서 읽은 표) — (내용, 버전). 없으면 (None, None)"""
    try:
        with SETTINGS_LOCK:
            d = json.loads(sokbo_path().read_text("utf-8"))
        return d, (d.get("meta") or {}).get("version")
    except (OSError, ValueError, AttributeError):
        return None, None


def sokbo_clean(v, depth=0):
    """출하속보 값 정리: 허용 형식(사전·목록·문자·숫자)만, 문자열은 꺾쇠 등 제거·길이 제한"""
    if depth > 6:
        raise ValueError("출하속보 구조가 너무 깊습니다")
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return v
    if isinstance(v, str):
        return re.sub(r"[<>`]", "", v)[:160]
    if isinstance(v, list):
        if len(v) > 120:
            raise ValueError("출하속보 목록이 너무 깁니다")
        return [sokbo_clean(x, depth + 1) for x in v]
    if isinstance(v, dict):
        if len(v) > 80:
            raise ValueError("출하속보 항목이 너무 많습니다")
        return {re.sub(r"[^\w가-힣/.\-() &]", "", str(k))[:40]: sokbo_clean(x, depth + 1) for k, x in v.items()}
    raise ValueError("출하속보 형식이 올바르지 않습니다")


# ---- 출하속보 재고 기록 (날짜별, 해당일 24시 기준) — 전일 대비 변동·추이용 ----
SOKHIST_KEEP = 400


def sokhist_path() -> Path:
    return STORE.dir / "sokbo_hist.json"


def sokhist_read() -> dict:
    try:
        with SETTINGS_LOCK:
            d = json.loads(sokhist_path().read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def sokhist_clean(stock) -> dict:
    """재고 표만 (숫자만): sc·pier·dhCem·dhClk {호기: t, sum: t} · total"""
    out = {}
    if not isinstance(stock, dict):
        return out
    for k in ("sc", "pier", "dhCem", "dhClk"):
        v = stock.get(k)
        if isinstance(v, dict):
            out[k] = {str(n)[:6]: x for n, x in list(v.items())[:20] if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e7}
    t = stock.get("total")
    if isinstance(t, (int, float)) and not isinstance(t, bool) and t == t:
        out["total"] = t
    return out


def sokhist_put(date: str, stock, src: str) -> bool:
    """한 날짜는 한 번만 기록 (같은 날짜를 다시 올리면 손으로 올린 것만 덮어씀)"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date or "")):
        return False
    st = sokhist_clean(stock)
    if not st:
        return False
    with SETTINGS_LOCK:
        try:
            h = json.loads(sokhist_path().read_text("utf-8"))
            h = h if isinstance(h, dict) else {}
        except (OSError, ValueError):
            h = {}
        if date in h and src != "upload":
            return False
        h[date] = dict(st, src=src, at=dt.datetime.now().isoformat(timespec="seconds"))
        for k in sorted(h)[:-SOKHIST_KEEP]:
            del h[k]
        tmp = sokhist_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(h, ensure_ascii=False), "utf-8")
        os.replace(tmp, sokhist_path())
    return True


def sokbo_store_pdf(pdf: bytes, meta: dict) -> dict | None:
    """출하속보 PDF 원본 저장 → 화면이 PDF를 읽어 반영 (같은 파일이면 건너뜀)"""
    if pdf[:5] != b"%PDF-" or len(pdf) > 10 * 1024 * 1024:
        raise ValueError("PDF 파일이 아니거나 너무 큽니다")
    h = hashlib.sha256(pdf).hexdigest()
    cur, _ = sokbo_read()
    if cur and (cur.get("meta") or {}).get("sha256") == h:
        return None
    now = dt.datetime.now()
    m = {"version": now.strftime("%Y%m%d%H%M%S%f"), "uploadedAt": now.isoformat(timespec="seconds"), "sha256": h,
         "uploadedBy": str(meta.get("uploadedBy") or "자동"), "fileName": re.sub(r'[<>`\\/:*?"|]', "", str(meta.get("fileName") or ""))[:80],
         "source": str(meta.get("source") or "folder"), "srcDate": str(meta.get("srcDate") or "")}
    p = sokbo_path()
    with SETTINGS_LOCK:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sokbo": None, "pdf": base64.b64encode(pdf).decode(), "meta": m}, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
    return m


# ---- 출하속보 폴더 자동 읽기 (구글 드라이브 동기화 폴더 등) ----
# Gmail → (Google Apps Script) → 구글 드라이브 폴더 → (서버 PC의 구글 드라이브 앱이 동기화) → 이 폴더의 최신 PDF를 반영
SWATCH = {"on": False, "folder": "", "every": 0, "last": None, "ok": None, "err": "", "got": None}


SOKBO_DIR_NAME = "Blue365 출하속보"


def drive_candidates() -> list:
    """구글 드라이브(데스크톱) 앱이 보여 주는 ‘Blue365 출하속보’ 폴더 후보 (드라이브 문자·언어별)"""
    subs = ("내 드라이브", "My Drive")
    out = [Path(f"{c}:/") / s / SOKBO_DIR_NAME for c in "GHIJKLMNOPQRSTUVWXYZDEF" for s in subs]
    home = Path.home()
    out += [home / "Google Drive" / s / SOKBO_DIR_NAME for s in subs] + [home / "Google Drive" / SOKBO_DIR_NAME, home / "내 드라이브" / SOKBO_DIR_NAME, home / "My Drive" / SOKBO_DIR_NAME]
    return out


def find_sokbo_dir(spec: str):
    """--sokbo-watch 값 → 실제 폴더 (auto 면 구글 드라이브 폴더를 찾아봄). 없으면 None"""
    if spec.strip().lower() == "auto":
        for p in drive_candidates():
            try:
                if p.is_dir():
                    return p
            except OSError:
                pass
        return None
    p = Path(spec)
    return p if p.is_dir() else None


def sokbo_watch_loop(spec: str, every: int) -> None:
    SWATCH.update(on=True, folder=SOKBO_DIR_NAME if spec.strip().lower() == "auto" else Path(spec).name, every=every)
    last = None
    folder = None
    while True:
        try:
            if folder is None or not folder.is_dir():   # 구글 드라이브 앱이 서버보다 늦게 켜져도 계속 찾아봄
                folder = find_sokbo_dir(spec)
                if folder is None:
                    SWATCH.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=False,
                                  err="폴더를 찾지 못함 — 구글 드라이브 앱 로그인·‘Blue365 출하속보’ 폴더 동기화 확인")
                    time.sleep(every)
                    continue
                SWATCH["folder"] = str(folder)
                log(f"출하속보 폴더: {folder}")
            files = [p for p in folder.glob("*.pdf") if not p.name.startswith(("~$", "."))]
            if files:
                newest = max(files, key=lambda p: p.stat().st_mtime)
                st = newest.stat()
                sig = (newest.name, st.st_mtime, st.st_size)
                if sig != last:
                    time.sleep(3)   # 동기화·저장이 끝날 때까지 잠시 대기
                    st2 = newest.stat()
                    if (st2.st_mtime, st2.st_size) == sig[1:]:
                        last = sig
                        when = dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
                        cur, _ = sokbo_read()
                        cm = (cur or {}).get("meta", {})
                        at = cm.get("srcDate") or cm.get("uploadedAt") or ""
                        if not at or when > at[:19]:   # 이미 더 최신 속보(손으로 올린 것 포함)가 있으면 덮어쓰지 않음
                            m = sokbo_store_pdf(newest.read_bytes(), {"fileName": newest.name, "uploadedBy": "자동 (드라이브 폴더)", "source": "folder", "srcDate": when})
                            if m:
                                SWATCH["got"] = when[:16]
                                log(f"출하속보 폴더 반영: {newest.name}")
                                USERS.log("(자동)", "출하속보 폴더 반영", newest.name, "-")
            SWATCH.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=True, err="")
        except PermissionError:
            SWATCH.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=False, err="파일이 열려 있거나 동기화 중 — 다음 주기에 다시")
        except Exception as e:
            SWATCH.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=False, err=f"{type(e).__name__}: {e}"[:120])
            log(f"출하속보 폴더 확인 오류: {SWATCH['err']}")
        time.sleep(every)


# ---------------------------------------------------------------------------
# MMS (Manufacturing Monitor) 읽기 전용 연결 — 현장 확인 2026-11-16
#   로그인: POST {주소}/user/login {hasLogined, loginName, loginPwd, defLanguage} → data.token (+ JSESSIONID 쿠키)
#   값    : POST {주소}/monitorTrend/getOpcTagValueInRedis (헤더 Token) — 보내는 형식은 시험(--mms-test)으로 찾아 저장
#   아이디·비밀번호는 서버 PC의 data/mms.json 에만 저장 (Windows: 그 PC·그 사용자만 풀 수 있게 암호화)
# ---------------------------------------------------------------------------
MMS_DEFAULT_URL = ""   # 주소는 저장소에 두지 않음 — MMS설정.bat 에서 입력 (예: http://서버주소/mms-web)
MMS_MAP_NAME = "MMS_매칭표.xlsx"
MMS = {"on": False, "ok": None, "err": "", "last": None, "every": 0, "fmt": "", "tags": 0, "got": 0, "items": 0, "skip": 0, "map": ""}
MMSV = {"t": None, "vals": {}}
MMS_FORMATS = {
    "list": lambda tags: tags,
    "tagNames": lambda tags: {"tagNames": tags},
    "tags": lambda tags: {"tags": tags},
    "tagList": lambda tags: {"tagList": tags},
    "tagNameList": lambda tags: {"tagNameList": tags},
    "objs": lambda tags: [{"tagName": t} for t in tags],
    "csv": lambda tags: {"tagNames": ",".join(tags)},
}


class MMSError(Exception):
    pass


class MMSAlready(MMSError):
    pass


class MMSKicked(MMSError):
    pass


def mms_already(j) -> bool:
    """MMS 응답이 ‘이미 로그인된 계정 — 계속할까요?’인지 (현장 화면: ‘The account has been logged in, confirm to continue?’)"""
    if not isinstance(j, dict) or str(j.get("errorCode", 0)) in ("0", "None"):
        return False
    m = str(j.get("msg") or "")
    return bool(re.search(r"has been logged in|already logged|confirm to continue|이미.*로그인", m, re.I))


def _dpapi(data: bytes, enc: bool):
    """Windows DPAPI: 이 PC·이 Windows 사용자만 풀 수 있게 암호화/복호화. Windows가 아니면 None"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes as w

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    dst = BLOB()
    c32 = ctypes.windll.crypt32
    ok = (c32.CryptProtectData(ctypes.byref(src), "Blue365 MMS", None, None, None, 0, ctypes.byref(dst)) if enc
          else c32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)))
    if not ok:
        return None
    out = ctypes.string_at(dst.pbData, dst.cbData)
    ctypes.windll.kernel32.LocalFree(dst.pbData)
    return out


def mms_cfg_path() -> Path:
    return STORE.dir / "mms.json"


def mms_cfg_read() -> dict:
    p = mms_cfg_path()
    if not p.exists():
        return {}
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = base64.b64decode(c.get("pw", "") or "")
    if c.get("pwProt") == "dpapi":
        dec = _dpapi(raw, False)
        if dec is None:
            raise MMSError("저장된 MMS 비밀번호를 풀 수 없습니다 (다른 PC·다른 Windows 사용자). --mms-setup 으로 다시 저장하세요")
        raw = dec
    c["password"] = raw.decode("utf-8")
    return c


def mms_cfg_write(c: dict) -> None:
    c = dict(c)
    pw = c.pop("password", "").encode("utf-8")
    enc = _dpapi(pw, True)
    c["pw"] = base64.b64encode(enc if enc is not None else pw).decode()
    c["pwProt"] = "dpapi" if enc is not None else "none"
    p = mms_cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


class MMSClient:
    def __init__(self, c: dict):
        import http.cookiejar
        import urllib.request
        self.c, self.url = c, c.get("url", MMS_DEFAULT_URL).rstrip("/")
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.token = None

    def _post(self, path: str, body):
        import urllib.error
        import urllib.request
        h = {"Content-Type": "application/json;charset=UTF-8", "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"}
        if self.token:
            h["Token"] = self.token
        req = urllib.request.Request(self.url + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=h, method="POST")
        try:
            with self.op.open(req, timeout=15) as r:
                txt = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise MMSError(f"MMS 응답 오류 HTTP {e.code} ({path})") from None
        except (urllib.error.URLError, OSError) as e:
            raise MMSError(f"MMS에 접속하지 못했습니다: {getattr(e, 'reason', e)}") from None
        try:
            return json.loads(txt)
        except ValueError:
            raise MMSError(f"MMS 응답이 JSON이 아닙니다 ({path}) — 로그인이 풀렸거나 주소가 다를 수 있습니다") from None

    def login(self, force: bool = True) -> None:
        """force: ‘이미 로그인된 계정’이면 브라우저의 ‘계속’처럼 hasLogined=true 로 다시 로그인 (다른 곳의 같은 계정 로그인이 끊길 수 있음)"""
        pw = self.c.get("password", "")
        if self.c.get("pwHash") == "md5":
            pw = hashlib.md5(pw.encode("utf-8")).hexdigest()
        # pwHash "raw": 브라우저가 보내는 loginPwd 값을 그대로 저장해 둔 경우 — 변환 없이 보냄
        self.token = None
        body = {"hasLogined": False, "loginName": self.c.get("user", ""), "loginPwd": pw, "defLanguage": 2}
        j = self._post("/user/login", body)
        if mms_already(j):
            if not force:
                raise MMSAlready("이 MMS 계정이 이미 다른 곳(브라우저 등)에서 로그인되어 있습니다")
            body["hasLogined"] = True
            j = self._post("/user/login", body)
        if not isinstance(j, dict) or str(j.get("errorCode", 0)) not in ("0", "None"):
            raise MMSError(f"MMS 로그인 실패: {(j or {}).get('msg') or (j or {}).get('errorCode')}")
        tok = (j.get("data") or {}).get("token") if isinstance(j.get("data"), dict) else None
        if not tok:
            raise MMSError("MMS 로그인 응답에 token이 없습니다")
        self.token = tok

    def values(self, tags: list, fmt: str) -> dict:
        out = {}
        for i in range(0, len(tags), 200):
            part = tags[i:i + 200]
            out.update(mms_extract(self._post("/monitorTrend/getOpcTagValueInRedis", MMS_FORMATS[fmt](part)), part))
        return out


def _mnum(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def mms_extract(j, tags: list) -> dict:
    """응답 JSON 어디에 있든 ‘요청한 태그 → 숫자’를 찾아냄 ({태그: 값} 또는 [{tagName: 태그, value: 값}] 등)"""
    want = {t: t for t in tags}
    low = {t.lower(): t for t in tags}
    out = {}

    def key_of(s):
        return want.get(s) or low.get(s.lower()) if isinstance(s, str) else None

    def walk(x, depth=0):
        if depth > 8:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                t = key_of(k)
                if t and _mnum(v) is not None:
                    out[t] = _mnum(v)
                elif t and isinstance(v, dict):
                    for vk in ("value", "val", "v", "tagValue", "currentValue", "Value", "pv"):
                        if _mnum(v.get(vk)) is not None:
                            out[t] = _mnum(v.get(vk))
                            break
            name = next((key_of(v) for v in x.values() if key_of(v)), None)
            if name:
                for vk in ("value", "val", "v", "tagValue", "currentValue", "Value", "pv", "tagVal"):
                    if vk in x and _mnum(x[vk]) is not None:
                        out[name] = _mnum(x[vk])
                        break
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)
    walk(j)
    return out


def mms_calc_fn(txt: str):
    """매칭표 ‘계산’ 칸 → 여러 태그 값을 하나로"""
    t = str(txt or "")
    m = re.search(r"[×x\*]\s*([\d.]+)", t)
    k = float(m.group(1)) if m else (10.197 if re.search(r"mbar\s*→\s*mmAq", t, re.I) else 1.0)
    if "합계" in t or "sum" in t.lower():
        f = sum
    elif "평균" in t or "avg" in t.lower():
        def f(v): return sum(v) / len(v)
    elif "높은" in t or "최대" in t or "max" in t.lower():
        f = max
    elif "낮은" in t or "최소" in t or "min" in t.lower():
        f = min
    else:
        def f(v): return v[0]
    return lambda v: f(v) * k


def mms_map_load(path: Path) -> list:
    """매칭표 엑셀 → [(설비 ID, 항목 키, [태그...], 계산 함수, 계산 글)]. 상태가 ‘매칭’ 또는 ‘사용’인 줄만"""
    sheets = read_xlsx(path.read_bytes())
    rows = sheets.get("매칭표") or next(iter(sheets.values()), [])
    hi = next((i for i, r in enumerate(rows[:20]) if r and "설비 ID" in [str(x or "").strip() for x in r]), None)
    if hi is None:
        raise MMSError(f"{path.name}: ‘설비 ID’ 머리글을 찾지 못했습니다")
    H = {str(x or "").strip(): j for j, x in enumerate(rows[hi])}
    need = ["설비 ID", "항목 키", "MMS 태그", "상태"]
    if any(k not in H for k in need):
        raise MMSError(f"{path.name}: 머리글 {', '.join(k for k in need if k not in H)} 이(가) 없습니다")
    out = []
    for r in rows[hi + 1:]:
        g = lambda k: str(r[H[k]]).strip() if k in H and H[k] < len(r) and r[H[k]] is not None else ""
        if g("상태") not in ("매칭", "사용"):
            continue
        tags = [t.strip() for t in re.split(r"[\n;]+", g("MMS 태그")) if t.strip()]
        if g("설비 ID") and g("항목 키") and tags:
            out.append((g("설비 ID"), g("항목 키"), tags, mms_calc_fn(g("계산")), g("계산")))
    return out


def mms_probe(cl: MMSClient, tags: list):
    """보내는 형식을 하나씩 시험 → 값이 가장 많이 온 형식"""
    best, res = None, {}
    for f in MMS_FORMATS:
        try:
            v = cl.values(tags[:30], f)
        except MMSError as e:
            v = {}
            res[f] = str(e)
            continue
        res[f] = len(v)
        if v and (best is None or len(v) > res[best]):
            best = f
    return best, res


def mms_once(cl: MMSClient, items: list, fmt: str) -> dict:
    tags = sorted({t for it in items for t in it[2]})
    vals = cl.values(tags, fmt)
    out, n = {}, 0
    for eid, key, ts, fn, _ in items:
        got = [vals[t] for t in ts if t in vals]
        if len(got) == len(ts):
            out.setdefault(eid, {})[key] = round(fn(got), 4)
            n += 1
    return {"vals": out, "tags": len(tags), "got": len(vals), "items": n}


def mms_loop(map_path: Path, every: int) -> None:
    MMS.update(on=True, every=every, map=map_path.name)
    cl, items, mt = None, [], None
    logins = []

    def relogin(x: MMSClient) -> None:
        """30분에 4번 넘게 다시 로그인해야 하면(같은 계정이 다른 곳에서도 로그인 중) 멈춤 → 15분 쉼"""
        now = time.time()
        logins[:] = [t for t in logins if now - t < 1800]
        if len(logins) >= 4:
            raise MMSKicked("같은 MMS 계정이 다른 곳(브라우저 등)에서도 로그인 중이라 서로 로그인을 끊고 있습니다 — 15분 쉬고 다시 시도. Blue365 전용 MMS 계정 권장")
        x.login()
        logins.append(now)
    while True:
        try:
            c = mms_cfg_read()
            if not c:
                raise MMSError("MMS 설정이 없습니다 — 서버 폴더에서 MMS설정.bat (python server.py --mms-setup) 실행")
            if not map_path.exists():
                raise MMSError(f"매칭표가 없습니다: {map_path}")
            m = map_path.stat().st_mtime
            if m != mt:
                items, mt = mms_map_load(map_path), m
                log(f"MMS 매칭표 읽음: {len(items)}개 항목 ({map_path.name})")
            if not items:
                raise MMSError("매칭표에 상태가 ‘매칭’인 줄이 없습니다")
            if cl is None:
                cl = MMSClient(c)
                relogin(cl)
            fmt = c.get("fmt")
            if fmt not in MMS_FORMATS:
                fmt, res = mms_probe(cl, sorted({t for it in items for t in it[2]}))
                if not fmt:
                    raise MMSError(f"값 요청 형식을 찾지 못했습니다 ({res}) — 화면 F12의 getOpcTagValueInRedis Payload 형식이 필요합니다")
                c["fmt"] = fmt
                mms_cfg_write(c)
            try:
                r = mms_once(cl, items, fmt)
            except MMSKicked:
                raise
            except MMSError:
                relogin(cl)
                r = mms_once(cl, items, fmt)
            if r["got"] == 0:
                cl = None
                raise MMSError("값이 하나도 오지 않았습니다 — 다음 주기에 다시 로그인합니다")
            now = dt.datetime.now().isoformat(timespec="seconds")
            MMSV.update(t=now, vals=r["vals"])
            MMS.update(ok=True, err="", last=now, fmt=fmt, tags=r["tags"], got=r["got"], items=r["items"], skip=len(items) - r["items"])
        except MMSKicked as e:
            log(f"MMS: {e}")
            MMS.update(ok=False, err=str(e), last=dt.datetime.now().isoformat(timespec="seconds"))
            cl = None
            time.sleep(max(0, 900 - every))
            logins.clear()
        except MMSError as e:
            if str(e) != MMS.get("err"):
                log(f"MMS: {e}")
            MMS.update(ok=False, err=str(e), last=dt.datetime.now().isoformat(timespec="seconds"))
        except Exception as e:  # noqa: BLE001 — 예상 못 한 오류도 서버는 계속
            log(f"MMS 오류: {e!r}")
            MMS.update(ok=False, err=f"예상 못 한 오류: {e!r}")
            cl = None
        time.sleep(every)


def mms_setup() -> None:
    import getpass
    print("=" * 56)
    print(" Blue365 · MMS 연결 설정 (읽기 전용)")
    print("  아이디·비밀번호는 이 PC의 data/mms.json 에만 저장됩니다.")
    print("  (Windows: 이 PC·이 Windows 사용자만 풀 수 있게 암호화)")
    print("=" * 56)
    old = {}
    try:
        old = mms_cfg_read()
    except MMSError:
        pass
    url = input(f"MMS 주소 (예: http://서버주소/mms-web){' [' + old['url'] + ']' if old.get('url') else ''}: ").strip() or old.get("url", "")
    if not re.match(r"https?://", url):
        sys.exit("MMS 주소는 http:// 로 시작해야 합니다 (브라우저 주소창의 #/ 앞부분, 예: http://서버주소/mms-web).")
    user = input(f"MMS 아이디{' [' + old['user'] + ']' if old.get('user') else ''}: ").strip() or old.get("user", "")
    print("  ※ 비밀번호는 입력해도 화면에 보이지 않습니다. 한/영 키가 ‘영문’인지 먼저 확인하세요.")
    pw = getpass.getpass("MMS 비밀번호: ")
    if not user or not pw:
        sys.exit("아이디와 비밀번호가 필요합니다.")
    c = {"url": url.rstrip("/"), "user": user, "password": pw, "pwHash": "plain"}
    tries = 0
    while True:
        tries += 1
        print("로그인 시험 중…")
        try:
            MMSClient(c).login(force=False)
            break
        except MMSAlready:
            print("  ✓ 아이디·비밀번호는 맞습니다. 다만 이 계정이 이미 다른 곳(브라우저 등)에서 로그인되어 있습니다.")
            print("    계속하면 그쪽 MMS 로그인이 끊길 수 있습니다 (MMS는 한 계정 한 곳 로그인으로 보임).")
            print("    ※ 서버가 30초마다 값을 읽으므로, 같은 계정을 브라우저에서도 쓰면 서로 로그인을 끊게 됩니다.")
            print("      Blue365 전용(읽기 전용) MMS 계정을 전산팀에 요청하는 것을 권합니다.")
            if input("    지금은 이 계정으로 계속할까요? (y/N): ").strip().lower() != "y":
                sys.exit("저장하지 않았습니다.")
            try:
                MMSClient(c).login(force=True)
                break
            except MMSError as e:
                print(f"  ✗ {e}")
        except MMSError as e:
            print(f"  ✗ {e}")
        if tries >= 3:
            sys.exit("3번 실패해 멈춥니다 (계정 잠김 방지). 저장하지 않았습니다. 아래 확인 후 다시 실행하세요.\n"
                     "  브라우저에서 MMS 로그인 → F12 Network → login → Payload의 loginPwd 값이\n"
                     "  ① 입력한 비밀번호와 같은지 ② 32자리 영문·숫자인지(MD5) ③ 그 밖의 긴 문자열인지 확인")
        print("  브라우저에서 F12 → Network → login 요청 → Payload 탭의 loginPwd 값을 보고 고르세요 (그 값은 채팅·메일로 보내지 마세요).")
        print("   1) 비밀번호를 다시 입력 (오타·한/영)")
        print("   2) loginPwd가 32자리 영문·숫자 → MD5 방식으로 시험")
        print("   3) loginPwd가 그 밖의 긴 문자열 → 그 값을 그대로 붙여넣기 (서버가 같은 값을 보냄)")
        print("   0) 끝내기")
        ch = input(f"  선택 (남은 시도 {3 - tries}번): ").strip()
        if ch == "1":
            c.update(password=getpass.getpass("  MMS 비밀번호: "), pwHash="plain")
        elif ch == "2":
            c["pwHash"] = "md5"
        elif ch == "3":
            c.update(password=getpass.getpass("  loginPwd 값 붙여넣기 (보이지 않음, 마우스 오른쪽 클릭으로 붙여넣기): ").strip(), pwHash="raw")
        else:
            sys.exit("저장하지 않았습니다.")
    mms_cfg_write(c)
    prot = json.loads(mms_cfg_path().read_text(encoding="utf-8")).get("pwProt")
    print(f"  ✓ 로그인 성공 · 저장: {mms_cfg_path()}")
    print("    비밀번호 보호: " + ("Windows 암호화 (이 PC·이 Windows 사용자만 풀 수 있음)" if prot == "dpapi" else "암호화 안 됨 — 이 폴더 접근 권한을 제한하세요"))
    print("다음: MMS시험.bat (python server.py --mms-test) 로 값이 오는지 확인하세요.")


def mms_test(map_path: Path) -> None:
    print(f"MMS 시험 · 매칭표 {map_path}")
    try:
        c = mms_cfg_read()
        if not c:
            sys.exit("MMS 설정이 없습니다. 먼저 MMS설정.bat (python server.py --mms-setup)")
        items = mms_map_load(map_path)
        print(f"  매칭표: 상태 ‘매칭’ {len(items)}개 항목")
        if not items:
            sys.exit("  상태가 ‘매칭’인 줄이 없습니다.")
        cl = MMSClient(c)
        cl.login()
        print("  ✓ 로그인 (※ 같은 계정으로 브라우저에서 MMS를 보고 있었다면 그쪽 로그인이 끊길 수 있습니다)")
        tags = sorted({t for it in items for t in it[2]})
        fmt, res = mms_probe(cl, tags)
        for f, n in res.items():
            print(f"    형식 {f:12s}: {n if isinstance(n, int) else '오류 — ' + n}")
        if not fmt:
            sys.exit("  ✗ 값이 오는 형식을 찾지 못했습니다. F12 → getOpcTagValueInRedis → Payload·Preview 형식을 알려 주세요.")
        c["fmt"] = fmt
        mms_cfg_write(c)
        r = mms_once(cl, items, fmt)
        print(f"  ✓ 형식 ‘{fmt}’ 저장 · 태그 {r['tags']}개 중 {r['got']}개 값 받음 · 화면 항목 {r['items']}/{len(items)}개")
        for eid, kv in list(r["vals"].items())[:12]:
            print("    " + eid + ": " + ", ".join(f"{k}={v:g}" for k, v in kv.items()))
        miss = sorted(set(tags) - set(cl.values(tags, fmt)))
        if miss:
            print(f"  값이 안 온 태그 {len(miss)}개 (태그 이름 확인):")
            for t in miss[:20]:
                print("    - " + t)
    except MMSError as e:
        sys.exit(f"  ✗ {e}")


# ---------------------------------------------------------------------------
# 원료 야드 재고 (석회석/부원료 재고현황 · 근무조 3차 00~08 / 1차 08~16 / 2차 16~24) — 현장 제공 2026-11-25
#   1-5K 1Yard·2Yard → 기존 프리블렌딩 Y1·Y2 (PBA1·PBA2), 6-7K → 신설 Y1·Y2 (PBB1·PBB2), S=적재 R=사용, 구치장 = 기존 서브 야적장
#   들어오는 길: 데이터 창 직접 입력(편집 권한 + 비밀번호) 또는 구글 드라이브 폴더의 JSON(Apps Script가 시트를 읽어 저장, --yard-watch)
# ---------------------------------------------------------------------------
YARD_IDS = ("PBA1", "PBA2", "PBB1", "PBB2")
YARD_DIR_NAME = "Blue365 원료재고"
YWATCH = {"on": False, "folder": "", "every": 0, "last": None, "ok": None, "err": "", "got": None}


def yard_path() -> Path:
    return STORE.dir / "yard.json"


def yard_hist_path() -> Path:
    return STORE.dir / "yard_hist.json"


def _ynum(v, hi=500000, nd=1):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0 or v > hi:
        return None
    return round(float(v), nd)


def _yhm(v):
    v = str(v or "").strip()
    return v if re.fullmatch(r"\d{1,3}:\d{2}", v) else None


def _yat(v):
    v = str(v or "").strip()[:19]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", v) else None


def yard_clean(b, zero_blank=False) -> dict:
    """원료 야드 입력값 검사 (석회석/부원료 재고현황 ‘재고 및 생산실적’ 시트 구성)
    yards  : 석회석 야드 PBA1·PBA2(1-5K 1·2Yard) PBB1·PBB2(6-7K) {t, m=S/R, at}
    sub    : 구치장 {A}             run  : 실가동(인출) 시간 A·B·RE(R/E)·SB(부원료 6-7K) "H:MM"
    subm   : 부원료 야드 B1·B2 {t, m}  draw : 근무조 인출량·시간 A·B(OSP→야드) LS(L-slag) DR(직송) SA·SB(쉘) {t, h}
    grade  : 야드 품위 {pcao, cao, mgo, k2o} %   chg : 야드 변경 {at, full=만실량}   extra : OSP1·OSP2 재고 등
    zero_blank: 시트 자동 읽기 — 실시간 작성 중인 시트는 아직 안 쓴 칸이 0·0:00이라 값 없음으로 봄 (현장 설명 2026-11-25)"""
    if not isinstance(b, dict):
        raise ValueError("형식이 올바르지 않습니다")
    date = str(b.get("date", ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("날짜(YYYY-MM-DD)가 필요합니다")
    shift = str(b.get("shift", ""))
    if shift not in ("1", "2", "3"):
        raise ValueError("근무조는 1·2·3차 중 하나입니다")

    def t_(v):
        n = _ynum(v)
        return None if zero_blank and n == 0 else n

    def hm_(v):
        h = _yhm(v)
        return None if not h or (zero_blank and re.fullmatch(r"0{1,3}:00", h)) else h

    def d_(k):
        v = b.get(k)
        return v if isinstance(v, dict) else {}

    def tm_(v, keep_at=False):
        v = v if isinstance(v, dict) else {}
        t, m = t_(v.get("t")), str(v.get("m") or "").upper()[:1]
        o = {}
        if t is not None:
            o["t"] = t
            if keep_at and _yat(v.get("at")):
                o["at"] = _yat(v.get("at"))
        if m in ("S", "R"):
            o["m"] = m
        return o

    yards = {k: o for k in YARD_IDS if (o := tm_(d_("yards").get(k), True))}
    subm = {k: o for k in ("B1", "B2") if (o := tm_(d_("subm").get(k)))}
    draw = {}
    for k in ("A", "B", "LS", "DR", "SA", "SB"):
        v = d_("draw").get(k)
        if isinstance(v, dict):
            o = {x: y for x, y in (("t", t_(v.get("t"))), ("h", hm_(v.get("h")))) if y is not None}
            if o:
                draw[k] = o
    grade = {}
    for k in YARD_IDS:
        v = d_("grade").get(k)
        if isinstance(v, dict):
            o = {x: _ynum(v.get(x), 100, 2) for x in ("pcao", "cao", "mgo", "k2o") if _ynum(v.get(x), 100)}
            if o:
                grade[k] = o
    chg = {}
    for k in YARD_IDS + ("SB1", "SB2"):
        v = d_("chg").get(k)
        if isinstance(v, dict) and _yat(v.get("at")):
            chg[k] = {"at": _yat(v.get("at"))[:16], "full": _ynum(v.get("full"))}
    out = {"date": date, "shift": shift, "yards": yards, "subm": subm, "draw": draw, "grade": grade, "chg": chg,
           "sub": {k: n for k, v in d_("sub").items() if k in ("A", "B") and (n := t_(v)) is not None},
           "run": {k: h for k, v in d_("run").items() if k in ("A", "B", "RE", "SB") and (h := hm_(v))},
           "extra": {k: n for k, v in d_("extra").items() if k in ("lslag", "direct", "osp1", "osp2") and (n := t_(v)) is not None},
           "at": _yat(b.get("at")) or dt.datetime.now().isoformat(timespec="seconds")}
    if not (yards or out["sub"] or subm or draw):
        raise ValueError("야드 재고가 하나도 없습니다")
    return out


def yard_read():
    try:
        with SETTINGS_LOCK:
            d = json.loads(yard_path().read_text("utf-8"))
        return d, (d.get("meta") or {}).get("version")
    except (OSError, ValueError, AttributeError):
        return None, None


def yard_hist_read() -> dict:
    try:
        with SETTINGS_LOCK:
            h = json.loads(yard_hist_path().read_text("utf-8"))
        return h if isinstance(h, dict) else {}
    except (OSError, ValueError):
        return {}


def yard_store(y: dict, by: str, src: str) -> dict:
    """최신값 저장 + 날짜#근무조 기록(같은 근무조는 나중 값으로 덮음, 빈 칸은 앞 값 유지 — 교대근무자가 나눠 입력해도 모임)"""
    now = dt.datetime.now()
    meta = {"version": now.strftime("%Y%m%d%H%M%S%f"), "savedAt": now.isoformat(timespec="seconds"), "by": by[:40], "source": src[:20]}
    key = f"{y['date']}#{y['shift']}"
    with SETTINGS_LOCK:
        try:
            h = json.loads(yard_hist_path().read_text("utf-8"))
            h = h if isinstance(h, dict) else {}
        except (OSError, ValueError):
            h = {}
        old = h.get(key) or {}
        merged = dict(y)
        merged["yards"] = dict(old.get("yards") or {})
        for k, v in y["yards"].items():   # 새 재고(t)가 오면 그 시각(at)도 새것으로 — 예전 시각이 남지 않게
            o = {x: z for x, z in (merged["yards"].get(k) or {}).items() if not ("t" in v and x == "at")}
            merged["yards"][k] = dict(o, **v)
        for k in ("sub", "run", "extra", "subm", "draw", "grade", "chg"):
            merged[k] = dict(old.get(k) or {}, **y[k])
        h[key] = dict(merged, src=src)
        for k in sorted(h)[:-1200]:
            del h[k]
        for path, data in ((yard_hist_path(), h), (yard_path(), {"yard": merged, "meta": meta})):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            os.replace(tmp, path)
    return meta


def find_yard_dir(spec: str):
    if spec.strip().lower() == "auto":
        for p in drive_candidates():
            q = p.parent / YARD_DIR_NAME
            try:
                if q.is_dir():
                    return q
            except OSError:
                pass
        return None
    p = Path(spec)
    return p if p.is_dir() else None


def yard_watch_loop(spec: str, every: int) -> None:
    """구글 드라이브 ‘Blue365 원료재고’ 폴더의 최신 JSON(Apps Script가 시트를 읽어 저장)을 반영"""
    YWATCH.update(on=True, folder=YARD_DIR_NAME if spec.strip().lower() == "auto" else Path(spec).name, every=every)
    last, folder = None, None
    while True:
        try:
            if folder is None or not folder.is_dir():
                folder = find_yard_dir(spec)
                if folder is None:
                    YWATCH.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=False, err=f"폴더를 찾지 못함 — 구글 드라이브의 ‘{YARD_DIR_NAME}’ 동기화 확인")
                    time.sleep(every)
                    continue
                YWATCH["folder"] = str(folder)
            files = [p for p in folder.glob("*.json") if not p.name.startswith(("~$", "."))]
            if files:
                newest = max(files, key=lambda p: p.stat().st_mtime)
                sig = (newest.name, newest.stat().st_mtime, newest.stat().st_size)
                if sig != last:
                    data = json.loads(newest.read_text("utf-8"))
                    for y in (data if isinstance(data, list) else [data]):
                        try:
                            yard_store(yard_clean(y, zero_blank=True), "자동 (재고현황 시트)", "drive")
                        except ValueError:
                            pass   # 아직 아무 칸도 안 쓴 근무조
                    last = sig
                    YWATCH["got"] = dt.datetime.now().isoformat(timespec="minutes")
                    log(f"원료 야드 재고 반영: {newest.name}")
            YWATCH.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=True, err="")
        except (OSError, ValueError) as e:
            YWATCH.update(ok=False, err=str(e)[:160], last=dt.datetime.now().isoformat(timespec="minutes"))
        time.sleep(every)


# ---------------------------------------------------------------------------
# AI 질의 (관리자 전용 · Claude API) — 사내 문서(data/ai_docs) + 화면이 보낸 현재 데이터로 답함
#   API 키는 이 PC의 data/ai.json 에만 (Windows DPAPI 암호화). 월 사용 한도(USD)를 넘으면 멈춤.
#   가격: Anthropic 공식 API 가격 (2026-11 기준) Claude Opus 5.5 입력 $4 · 출력 $20 · 캐시 읽기 $0.20 / 100만 토큰, 캐시 쓰기 = 입력의 1.25배
# ---------------------------------------------------------------------------
AI_MODEL = "claude-opus-5-5"
AI_PRICE = {"in": 4.0, "out": 20.0, "cr": 0.20, "cw": 5.0}
AI_LOCK = threading.Lock()
AI_DOC_EXT_TXT = (".md", ".txt", ".csv")
AI_SYSTEM = """당신은 삼척 시멘트 공장의 공정·품질 전문가 ‘Blue365 AI’입니다. 원료(석회석 채광~조합원료), 소성(킬른·냉각기), 분쇄(원료밀·시멘트밀), 품질시험(XRF/XRD/f-CaO/강도)을 연결해서 생각합니다.
규칙
1. <현재 데이터>와 <사내 문서>에 있는 내용만 ‘사실’로 씁니다. 수치마다 출처(데이터 항목과 시각, 또는 문서 이름)를 붙입니다.
2. 데이터·문서에 없는 내용은 ‘추정’ 또는 ‘경험칙’으로 표시합니다. 모르면 모른다고 말하고, 수치를 지어내지 않습니다.
3. 품질 이상·공정 문제 질문은 ① 현상 정의와 정량화 ② 원인 후보를 화학/원료/공정/설비/시험오차 5개 축으로 가능성 순위 ③ 원인별 확인 방법(어떤 데이터·시험) ④ 단기 조치와 근본 대책 구분 ⑤ KS L 5201·사내 관리기준 대비 평가 순서로 답합니다.
4. KS 기준 중 ok=false(원문 대조 전 추정 기준)는 ‘미달’로 단정하지 않습니다.
5. 데이터에서 ‘가상’으로 표시된 값(생산량·운전값 등)은 근거로 쓰지 않습니다.
6. 설비 조작을 직접 지시하지 않고, 담당자 확인이 필요한 권고로 씁니다.
7. 한국어로, 경영진도 이해할 수 있게 결론을 먼저 쓰고, 표는 간결하게 씁니다."""


class AIError(Exception):
    pass


def ai_cfg_path() -> Path:
    return STORE.dir / "ai.json"


def ai_usage_path() -> Path:
    return STORE.dir / "ai_usage.json"


def ai_docs_dir() -> Path:
    return STORE.dir / "ai_docs"


def ai_cfg_read() -> dict:
    p = ai_cfg_path()
    if not p.exists():
        return {}
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = base64.b64decode(c.get("k", "") or "")
    if c.get("kProt") == "dpapi":
        dec = _dpapi(raw, False)
        if dec is None:
            raise AIError("저장된 API 키를 풀 수 없습니다 (다른 PC·다른 Windows 사용자). AI설정.bat 으로 다시 저장하세요")
        raw = dec
    c["key"] = raw.decode("utf-8")
    return c


def ai_cfg_write(c: dict) -> None:
    c = dict(c)
    k = c.pop("key", "").encode("utf-8")
    enc = _dpapi(k, True)
    c["k"] = base64.b64encode(enc if enc is not None else k).decode()
    c["kProt"] = "dpapi" if enc is not None else "none"
    p = ai_cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def ai_usage_read() -> dict:
    try:
        d = json.loads(ai_usage_path().read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ai_sdk():
    try:
        import anthropic  # 선택 설치 (AI설정.bat 이 pip install anthropic)
        return anthropic
    except ImportError:
        return None


def ai_status() -> dict:
    """화면에 알릴 AI 상태 (비밀 없음)"""
    if not ai_cfg_path().exists():
        return {"ready": False, "why": "AI설정.bat 으로 API 키를 저장하지 않음"}
    if ai_sdk() is None:
        return {"ready": False, "why": "anthropic 패키지 없음 — AI설정.bat 실행"}
    try:
        c = ai_cfg_read()
    except AIError as e:
        return {"ready": False, "why": str(e)}
    m = ai_usage_read().get(dt.date.today().strftime("%Y-%m"), {})
    return {"ready": bool(c.get("key")), "why": "" if c.get("key") else "API 키 없음", "model": AI_MODEL,
            "cap": c.get("cap"), "used": round(m.get("usd", 0), 2), "n": m.get("n", 0),
            "docs": len([p for p in ai_docs_dir().glob("*") if p.suffix.lower() in AI_DOC_EXT_TXT + (".pdf",)]) if ai_docs_dir().is_dir() else 0}


def ai_docs():
    """사내 문서: .md·.txt·.csv(최대 40만 자) → 시스템 프롬프트, .pdf(최대 8MB) → 문서 블록"""
    d, txt, pdfs, names, tot, pb = ai_docs_dir(), [], [], [], 0, 0
    if not d.is_dir():
        return "", [], []
    for p in sorted(d.iterdir()):
        ext = p.suffix.lower()
        try:
            if ext in AI_DOC_EXT_TXT:
                raw = p.read_bytes()
                for enc in ("utf-8-sig", "cp949"):
                    try:
                        t = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        t = None
                if t is None or tot + len(t) > 400_000:
                    continue
                tot += len(t)
                txt.append(f'<문서 이름="{p.name}">\n{t}\n</문서>')
                names.append(p.name)
            elif ext == ".pdf":
                b = p.read_bytes()
                if pb + len(b) > 8 * 1024 * 1024:
                    continue
                pb += len(b)
                pdfs.append({"type": "document", "title": p.name, "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(b).decode()}})
                names.append(p.name)
        except OSError:
            continue
    return "\n\n".join(txt), pdfs, names


def ai_ask(q: str, ctx: str, hist: list) -> dict:
    an = ai_sdk()
    if an is None:
        raise AIError("anthropic 패키지가 없습니다 — 서버 폴더의 AI설정.bat 을 실행하세요")
    c = ai_cfg_read()
    if not c.get("key"):
        raise AIError("API 키가 없습니다 — AI설정.bat 으로 저장하세요")
    mon = dt.date.today().strftime("%Y-%m")
    used = ai_usage_read().get(mon, {}).get("usd", 0)
    cap = c.get("cap")
    if cap and used >= cap:
        raise AIError(f"이번 달 AI 사용 한도 ${cap}에 도달했습니다 (사용 ${used:.2f}). AI설정.bat 에서 한도를 바꿀 수 있습니다")
    doc_txt, pdfs, names = ai_docs()
    system = [{"type": "text", "text": AI_SYSTEM}]
    if doc_txt:
        system.append({"type": "text", "text": "<사내 문서>\n" + doc_txt + "\n</사내 문서>"})
    system[-1]["cache_control"] = {"type": "ephemeral"}   # 규칙·문서는 매번 같아 캐시 (다시 읽으면 입력 비용 약 1/20)
    msgs = []
    if pdfs:
        pdfs[-1]["cache_control"] = {"type": "ephemeral"}
        msgs += [{"role": "user", "content": pdfs + [{"type": "text", "text": "위 PDF는 <사내 문서>입니다."}]},
                 {"role": "assistant", "content": "사내 문서를 확인했습니다."}]
    for h in hist[-6:]:
        msgs.append({"role": "assistant" if h.get("role") == "assistant" else "user", "content": str(h.get("content", ""))[:8000] or "-"})
    msgs.append({"role": "user", "content": f"<현재 데이터>\n{ctx}\n</현재 데이터>\n\n질문: {q}"})
    cl = an.Anthropic(api_key=c["key"], timeout=300.0, max_retries=2)
    kw = dict(model=AI_MODEL, max_tokens=8000, system=system, messages=msgs)
    try:
        try:   # 정책상 거절되면 서버가 다른 모델로 이어서 답함 (server-side fallback)
            r = cl.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except TypeError:   # 오래된 SDK: fallbacks 인자 없음
            r = cl.messages.create(**kw)
    except an.AuthenticationError:
        raise AIError("API 키가 맞지 않습니다 — AI설정.bat 으로 다시 저장하세요")
    except an.RateLimitError:
        raise AIError("요청이 많아 잠시 막혔습니다. 1분 뒤 다시 시도하세요")
    except an.APIStatusError as e:
        raise AIError(f"AI 서버 오류 ({e.status_code}): {str(getattr(e, 'message', e))[:160]}")
    except an.APIConnectionError:
        raise AIError("AI 서버에 연결하지 못했습니다 (이 PC의 인터넷·방화벽 확인)")
    if r.stop_reason == "refusal":
        raise AIError("AI가 이 질문에 답하지 않았습니다 (안전 정책). 질문을 바꿔 보세요")
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    u = r.usage
    tk = {"in": getattr(u, "input_tokens", 0) or 0, "out": getattr(u, "output_tokens", 0) or 0,
          "cr": getattr(u, "cache_read_input_tokens", 0) or 0, "cw": getattr(u, "cache_creation_input_tokens", 0) or 0}
    usd = sum(tk[k] * AI_PRICE[k] for k in tk) / 1e6
    with SETTINGS_LOCK:
        d = ai_usage_read()
        m = d.setdefault(mon, {"n": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "usd": 0.0})
        m["n"] += 1
        for k in tk:
            m[k] += tk[k]
        m["usd"] = round(m["usd"] + usd, 4)
        tmp = ai_usage_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        os.replace(tmp, ai_usage_path())
    if r.stop_reason == "max_tokens":
        text += "\n\n(답이 길어 중간에 끊겼습니다. 질문을 나눠 주세요.)"
    return {"answer": text or "(빈 답변)", "model": getattr(r, "model", AI_MODEL), "docs": names,
            "usage": dict(tk, usd=round(usd, 4)), "month": {"usd": round(m["usd"], 2), "cap": cap}}


def ai_setup() -> None:
    import getpass
    print("=" * 56)
    print(" Blue365 · AI 질의 설정 (관리자 전용 · Claude API)")
    print("  API 키는 이 PC의 data/ai.json 에만 저장됩니다 (Windows: 이 PC·이 사용자만 풀 수 있게 암호화).")
    print("  키는 https://platform.claude.com 의 API Keys 에서 만듭니다 (조직 결제 설정 필요).")
    print("=" * 56)
    an = ai_sdk()
    if an is None:
        sys.exit("anthropic 패키지가 없습니다. AI설정.bat 으로 실행하면 먼저 설치합니다 (python -m pip install anthropic).")
    try:
        old = ai_cfg_read()
    except AIError:
        old = {}
    print("  ※ 키는 입력해도 화면에 보이지 않습니다. 마우스 오른쪽 클릭으로 붙여넣기 후 Enter.")
    k = getpass.getpass(f"API 키 (sk-ant-…){' [Enter = 기존 키 유지]' if old.get('key') else ''}: ").strip() or old.get("key", "")
    if not k.startswith("sk-ant-"):
        sys.exit("API 키는 sk-ant- 로 시작합니다. 다시 실행하세요.")
    print("키 확인 중 (모델 정보 조회 — 요금 없음)…")
    try:
        an.Anthropic(api_key=k, timeout=30.0).models.retrieve(AI_MODEL)
        print(f"  ✓ 키 확인: {AI_MODEL} 사용 가능")
    except AttributeError:
        print("  (이 SDK 버전은 확인 기능이 없어 건너뜀)")
    except an.AuthenticationError:
        sys.exit("  ✗ 키가 맞지 않습니다. 다시 실행하세요.")
    except Exception as e:   # 네트워크 등 — 저장은 하되 알림
        print(f"  ! 확인하지 못함: {str(e)[:160]} — 저장은 합니다")
    cap0 = old.get("cap") or 30
    cv = input(f"월 사용 한도 USD (넘으면 멈춤) [{cap0}]: ").strip()
    try:
        cap = float(cv) if cv else float(cap0)
    except ValueError:
        cap = float(cap0)
    ai_cfg_write({"key": k, "cap": cap, "at": dt.datetime.now().isoformat(timespec="seconds")})
    ai_docs_dir().mkdir(parents=True, exist_ok=True)
    rd = ai_docs_dir() / "읽어보세요.txt"
    if not rd.exists():
        rd.write_text("이 폴더에 사내 문서를 넣으면 AI가 답할 때 근거로 씁니다.\n- 형식: .md .txt .csv (최대 40만 자), .pdf (합계 8MB)\n- 예: 품질 관리기준표, 공정 SOP, 설비 매뉴얼 요약, 과거 품질 이상 보고서\n- 외부(Anthropic API)로 전송되므로 사내 보안 기준상 보내도 되는 문서만 넣으세요.\n", "utf-8")
    print(f"저장 완료 · 월 한도 ${cap:g} · 사내 문서 폴더: {ai_docs_dir()}")
    print("서버실행.bat 을 다시 실행하면 관리자 화면의 ‘AI 질의’가 켜집니다.")


def settings_path() -> Path:
    return STORE.dir / "settings.json"


def settings_read():
    """(설정, 변경 표시). 없거나 손상되면 (None, None) → 화면이 기본값을 씀"""
    p = settings_path()
    try:
        with SETTINGS_LOCK:
            d = json.loads(p.read_text("utf-8"))
        return (d if isinstance(d, dict) else None), str(d.get("at", "")) if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None, None


CFG_ITEMS = ("blaine", "ist", "fst", "s1", "s3", "s7", "s28", "MgO", "SO3", "LOI", "Cl")
CFG_PRODS = ("1종", "3종")


def settings_clean(c) -> dict:
    """화면에서 온 관리기준을 형식에 맞게 정리 (모르는 항목은 버림, 범위를 벗어난 값은 오류)"""
    if not isinstance(c, dict):
        raise ValueError("설정 형식이 올바르지 않습니다")

    def num(v, lo, hi, name, none_ok=False):
        if v is None and none_ok:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not (lo <= v <= hi):
            raise ValueError(f"{name} 값이 올바르지 않습니다")
        return v

    f = c.get("fcao") if isinstance(c.get("fcao"), dict) else {}
    out = {"v": 1, "fcao": {"target": num(f.get("target"), 0, 5, "f-CaO 목표"), "tol": num(f.get("tol"), 0.05, 3, "f-CaO 허용폭"),
                           "warnRate": num(f.get("warnRate"), 0, 100, "주의 이탈 비율")}, "ks": {}, "inh": {}}
    for pr in CFG_PRODS:
        k = (c.get("ks") or {}).get(pr) if isinstance(c.get("ks"), dict) else None
        h = (c.get("inh") or {}).get(pr) if isinstance(c.get("inh"), dict) else None
        out["ks"][pr], out["inh"][pr] = {}, {}
        for it in CFG_ITEMS:
            x = k.get(it) if isinstance(k, dict) else None
            if isinstance(x, dict) and x.get("v") is not None:
                out["ks"][pr][it] = {"v": num(x.get("v"), 0, 1e6, f"{pr} {it} KS 기준"), "ok": 1 if x.get("ok") else 0}
            y = h.get(it) if isinstance(h, dict) else None
            if isinstance(y, dict) and (y.get("lo") is not None or y.get("hi") is not None):
                lo, hi = num(y.get("lo"), 0, 1e6, f"{pr} {it} 사내 하한", True), num(y.get("hi"), 0, 1e6, f"{pr} {it} 사내 상한", True)
                if lo is not None and hi is not None and lo > hi:
                    raise ValueError(f"{pr} {it} 사내 기준의 하한이 상한보다 큽니다")
                out["inh"][pr][it] = {"lo": lo, "hi": hi}
    # 킬른 정지·보수 기간
    dn = c.get("down")
    if dn is not None:
        if not isinstance(dn, list) or len(dn) > 40:
            raise ValueError("정지·보수 기간 형식이 올바르지 않습니다")
        out["down"] = []
        rev = c.get("downRev")
        if isinstance(rev, int) and not isinstance(rev, bool) and 0 <= rev <= 1000:
            out["downRev"] = rev
        for x in dn:
            if not isinstance(x, dict) or not re.fullmatch(r"K[3-7]|RM(?:3|4|5|51|6|7)", str(x.get("k", ""))):
                raise ValueError("정지·보수 기간의 설비(킬른·원료밀)가 올바르지 않습니다")
            f, t = str(x.get("from") or ""), str(x.get("to") or "")
            for d in (f, t):
                if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                    raise ValueError("정지·보수 기간의 날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")
            if f and t and f > t:
                raise ValueError("정지·보수 기간의 시작일이 종료일보다 늦습니다")
            out["down"].append({"k": x["k"], "from": f, "to": t, "kind": "repair" if x.get("kind") == "repair" else "stop",
                                "note": re.sub(r"[<>&\"'`]", "", str(x.get("note") or ""))[:30]})
    return out


def page_build():
    """화면 파일의 버전(빌드 시각). 파일이 바뀌면 열려 있는 화면들이 스스로 다시 엽니다."""
    try:
        m = PAGE.stat().st_mtime
        if _PB["m"] != m:
            mm = re.search(rb'name="b365-build" content="([^"]+)"', PAGE.read_bytes()[:4000])
            _PB.update(m=m, v=mm.group(1).decode() if mm else None)
        return _PB["v"]
    except OSError:
        return None

# ---------------------------------------------------------------- 접속 허용 대역
# 기본: 사내망(사설 IP) 대역만 허용 → 인터넷(공인 IP)에서 온 접속은 거절
PRIVATE_NETS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7", "fe80::/10"]
LOCAL_NETS = ["127.0.0.0/8", "::1/128"]           # 서버 PC 자신은 항상 허용
ALLOW: list = []                                    # [] 이면 제한 없음(--allow-any)


def parse_allow(text: str) -> list:
    """'192.168.10.0/24,10.20.' → 네트워크 목록. '192.168.10.' 처럼 끝이 점이면 그 대역으로 봄."""
    nets = []
    for part in [x.strip() for x in text.split(",") if x.strip()]:
        if part.endswith("."):
            octs = part.rstrip(".").split(".")
            part = ".".join(octs + ["0"] * (4 - len(octs))) + f"/{8 * len(octs)}"
        nets.append(ipaddress.ip_network(part, strict=False))
    return nets


def allowed(ip: str) -> bool:
    if not ALLOW:
        return True
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return any(a.version == n.version and a in n for n in ALLOW)
WATCH: str | None = None


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 자동 백업
BACKUP_DIR: Path | None = None
BACKUP_KEEP = 14


def backup_once() -> Path | None:
    """하루 한 번 data 폴더의 핵심 파일을 zip 으로 보관 (사용자·관리기준·최신 데이터·감사 기록).
    이력(history)과 로그인 유지 정보(sessions.json)는 넣지 않습니다."""
    if not BACKUP_DIR:
        return None
    out = BACKUP_DIR / f"blue365-backup-{dt.date.today():%Y%m%d}.zip"
    if out.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    src = STORE.dir
    names = [n for n in ("users.json", "settings.json", "latest.json", "sokbo.json", "sokbo_hist.json", "yard.json", "yard_hist.json", "ai_usage.json") if (src / n).exists()] + sorted(f.name for f in src.glob("audit*.log"))
    if not names:
        return None
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            try:
                z.writestr(n, (src / n).read_bytes())      # 파일은 통째로 바꿔 쓰므로(os.replace) 읽는 순간의 온전한 내용
            except OSError:
                pass
    os.replace(tmp, out)
    for f in sorted(BACKUP_DIR.glob("blue365-backup-*.zip"))[:-BACKUP_KEEP]:
        f.unlink(missing_ok=True)
    log(f"자동 백업: {out} ({out.stat().st_size / 1024:.0f} KB, {len(names)}개 파일)")
    return out


def backup_loop() -> None:
    while True:
        try:
            backup_once()
        except Exception as e:      # 백업 실패가 서버를 멈추지 않게
            log(f"자동 백업 실패: {e}")
        time.sleep(1800)


# ---------------------------------------------------------------- 공유 폴더 감시
def watch_loop(folder: Path, interval: int) -> None:
    last = None
    if STORE.meta:  # 이미 더 최신 업로드가 있으면 시작할 때 옛 파일로 덮어쓰지 않음
        try:
            up = dt.datetime.fromisoformat(STORE.meta["uploadedAt"]).timestamp()
            files = [p for p in folder.glob("*.xlsx") if not p.name.startswith("~$")]
            if files:
                newest = max(files, key=lambda p: p.stat().st_mtime)
                if newest.stat().st_mtime <= up:
                    last = (newest.name, newest.stat().st_mtime, newest.stat().st_size)
        except Exception:
            pass
    while True:
        try:
            files = [p for p in folder.glob("*.xlsx") if not p.name.startswith("~$")]
            if files:
                newest = max(files, key=lambda p: p.stat().st_mtime)
                st = newest.stat()
                sig = (newest.name, st.st_mtime, st.st_size)
                if sig != last:
                    time.sleep(3)  # 저장이 끝날 때까지 잠시 대기
                    st2 = newest.stat()
                    if (st2.st_mtime, st2.st_size) == sig[1:]:
                        sheets = read_xlsx(newest.read_bytes())
                        meta = STORE.save(sheets, {"fileName": newest.name, "uploadedBy": "공유 폴더", "source": "folder"})
                        last = sig
                        log(f"공유 폴더 반영: {newest.name} (버전 {meta['version']})")
        except PermissionError:
            log("파일이 열려 있어 다음 주기에 다시 읽습니다")
        except Exception as e:  # 잘못된 파일이 있어도 서버는 계속 동작
            log(f"공유 폴더 읽기 실패: {e}")
        time.sleep(interval)


# ---------------------------------------------------------------- HTTP
# ---------------------------------------------------------------- 사용자 · 로그인
ROLES = ("viewer", "editor", "admin")                    # 뷰어 < 편집 < 관리자
ROLE_KO = {"viewer": "뷰어", "editor": "편집", "admin": "관리자"}
SESSION_HOURS = 12            # 관리자: 로그인 뒤 12시간 고정 / 뷰어·편집: 12시간 동안 화면 활동이 없으면 로그아웃
AUDIT_MAX = 5 * 1024 * 1024      # audit.log 가 이 크기를 넘으면 audit-날짜.log 로 보관
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")


def pw_ok(pw: str) -> bool:
    return isinstance(pw, str) and 8 <= len(pw) <= 64 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)


class Users:
    """data/users.json — 비밀번호는 PBKDF2-SHA256(20만 회)+솔트로만 저장. 기록은 data/audit.log"""

    def __init__(self, folder: Path):
        self.path = folder / "users.json"
        self.audit = folder / "audit.log"
        self.lock = threading.Lock()
        self.data = {"users": {}, "ips": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
                self.data.setdefault("ips", {})
            except Exception:
                sys.exit(f"{self.path} 파일을 읽을 수 없습니다. 파일을 확인하세요.")

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _hash(pw: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()

    def log(self, actor: str, action: str, detail: str = "", ip: str = ""):
        clean = lambda x: re.sub(r"[\x00-\x1f\x7f\u2028\u2029]", " ", str(x))[:200]   # 줄바꿈·탭으로 가짜 기록 줄을 만들지 못하게
        line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{clean(actor)}\t{clean(action)}\t{clean(detail)}\t{clean(ip)}\n"
        with self.lock:
            try:
                if self.audit.exists() and self.audit.stat().st_size > AUDIT_MAX:      # 너무 커지면 날짜를 붙여 보관하고 새로 시작
                    os.replace(self.audit, self.audit.with_name(f"audit-{dt.datetime.now():%Y%m%d-%H%M%S}.log"))
            except OSError:
                pass
            with open(self.audit, "a", encoding="utf-8") as f:
                f.write(line)
        log(f"[기록] {actor} · {action} · {detail}")

    def audit_tail(self, n=60):
        if not self.audit.exists():
            return []
        with open(self.audit, "rb") as f:                 # 끝부분 64KB만 읽음
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().decode("utf-8", "replace").splitlines()
        if size > 65536:
            lines = lines[1:]                             # 잘린 첫 줄 버림
        lines = lines[-n:]
        return [dict(zip(("t", "who", "act", "detail", "ip"), (l.split("\t") + [""] * 5)[:5])) for l in reversed(lines)]

    def all(self) -> list:
        """사용자 목록 사본 (다른 요청이 동시에 등록·삭제해도 안전)"""
        with self.lock:
            return list(self.data["users"].values())

    def has_admin(self) -> bool:
        return any(u.get("role") == "admin" and u.get("status") == "active" for u in self.all())

    def get(self, uid: str):
        return self.data["users"].get((uid or "").lower())

    def add(self, uid, pw, name, dept, ip, admin=False):
        salt = secrets.token_hex(16)
        u = {"id": uid, "name": name, "dept": dept, "salt": salt, "hash": self._hash(pw, salt),
             "role": "admin" if admin else None, "status": "active" if admin else "pending",
             "created": dt.datetime.now().isoformat(timespec="seconds"), "ip": ip, "lastLogin": None, "lastIp": None}
        with self.lock:
            if uid.lower() in self.data["users"]:      # 같은 아이디가 동시에 등록되는 경우
                return None
            self.data["users"][uid.lower()] = u
            self._save()
        return u

    def reapply(self, uid, pw, name, dept, ip):
        """거절된 아이디의 재신청: 새 비밀번호·부서·이름으로 바꾸고 다시 승인 대기로"""
        with self.lock:
            u = self.data["users"].get(uid.lower())
            if not u or u.get("status") != "rejected":
                return None
            u["salt"] = secrets.token_hex(16)
            u["hash"] = self._hash(pw, u["salt"])
            u.update(id=uid, name=name, dept=dept, role=None, status="pending", ip=ip, reapplied=(u.get("reapplied") or 0) + 1,
                     created=dt.datetime.now().isoformat(timespec="seconds"), approvedBy=None, approvedAt=None, mustChange=False)
            self._save()
            return u

    def verify(self, uid, pw):
        u = self.get(uid)
        if not u or not isinstance(pw, str):
            hashlib.pbkdf2_hmac("sha256", b"x", b"y" * 16, 200_000)      # 없는 아이디도 같은 시간 소요
            return None
        return u if hmac.compare_digest(self._hash(pw, u["salt"]), u["hash"]) else None

    def update(self, uid, **kw):
        with self.lock:
            u = self.data["users"].get(uid.lower())
            if not u:
                return None
            if "pw" in kw:
                pw = kw.pop("pw")
                u["salt"] = secrets.token_hex(16)
                u["hash"] = self._hash(pw, u["salt"])
            u.update(kw)
            self._save()
            return u

    def delete(self, uid):
        with self.lock:
            self.data["users"].pop(uid.lower(), None)
            self._save()

    def mark_ip(self, ip, uid):
        with self.lock:
            self.data["ips"][ip] = uid
            self._save()

    def known_ip(self, ip) -> bool:
        return ip in self.data["ips"]

    def public(self, u):
        return {k: u.get(k) for k in ("id", "name", "dept", "role", "status", "created", "ip", "lastLogin", "lastIp", "approvedBy", "approvedAt", "reapplied")}


USERS: Users
SESS: dict = {}            # 토큰의 SHA-256 → {uid, exp, born, ck} (토큰 원문은 서버에 두지 않음)
SESS_LOCK = threading.Lock()
SESS_FILE: Path | None = None      # data/sessions.json — 서버를 다시 켜도 로그인 유지
COOKIE_DAYS = 30                   # 뷰어·편집 쿠키 보관 기간 (서버가 SESSION_HOURS 무활동이면 먼저 끊음)


def tk(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sess_save() -> None:
    """SESS_LOCK 을 잡은 상태에서 호출"""
    if not SESS_FILE:
        return
    try:
        tmp = SESS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(SESS), "utf-8")
        os.replace(tmp, SESS_FILE)
    except OSError as e:
        log(f"로그인 유지 정보 저장 실패: {e}")


def sess_load() -> None:
    if not SESS_FILE or not SESS_FILE.exists():
        return
    try:
        data = json.loads(SESS_FILE.read_text("utf-8"))
        now = time.time()
        with SESS_LOCK:
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(v.get("uid"), str) and v.get("exp", 0) > now:
                    SESS[k] = v
    except Exception:      # 손상된 파일은 무시 (모두 다시 로그인)
        pass


def cookie(token: str, admin: bool) -> str:
    age = SESSION_HOURS * 3600 if admin else COOKIE_DAYS * 86400
    return f"b365s={token}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict"
FAILS: dict = {}           # IP → [실패 시각...] (로그인 10회/10분 초과 시 잠시 차단)


def is_local(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
        if a.version == 6 and a.ipv4_mapped:
            a = a.ipv4_mapped
        return a.is_loopback
    except ValueError:
        return False


# 화면은 파일 하나(스크립트·스타일 내장)라 'unsafe-inline'은 허용하되, 외부 주소 연결·불러오기는 모두 막음
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "Blue365/1.0"
    timeout = 30               # 30초 동안 아무것도 오지 않는 연결은 끊음

    def log_message(self, fmt, *args):  # 접속 기록은 요약해서
        quiet = self.path.startswith("/api/status") or self.path.startswith("/api/me")
        if not quiet or (len(args) > 1 and str(args[1]) not in ("200", "304")):   # 상태 확인은 실패했을 때만 기록
            log(f"{self.client_address[0]} {fmt % args}")

    def _send(self, code: int, body, ctype="application/json; charset=utf-8", extra: dict | None = None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")          # 다른 사이트 안에 끼워 넣기 금지
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)      # 외부 주소로 데이터를 보내거나 불러오지 못하게
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if getattr(self, "_cookie", None) and "Set-Cookie" not in (extra or {}):
            self.send_header("Set-Cookie", self._cookie)
            self._cookie = None
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @property
    def ip(self) -> str:
        return self.client_address[0]

    def _guard(self) -> bool:
        if allowed(self.ip):
            return True
        log(f"접속 거절: {self.ip} (허용 대역 밖)")
        self._send(403, "이 서버는 사내망에서만 접속할 수 있습니다.", "text/plain; charset=utf-8")
        return False

    # ---- 세션
    def _token(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        m = c.get("b365s")
        return m.value if m else None

    def _user(self):
        t = self._token()
        if not t:
            return None
        h, now = tk(t), time.time()
        with SESS_LOCK:
            s = SESS.get(h)
            if not s or s["exp"] < now:
                if SESS.pop(h, None):
                    sess_save()
                return None
        u = USERS.get(s["uid"])
        if not u or u.get("status") != "active" or u.get("role") not in ROLES:
            return None
        # 뷰어·편집: 화면이 열려 있으면(20초마다 확인 요청) 계속 연장 → 상황판이 로그아웃되지 않음. 관리자는 연장하지 않음
        if u["role"] != "admin" and s["exp"] - now < SESSION_HOURS * 3600 - 600:
            with SESS_LOCK:
                s["exp"] = now + SESSION_HOURS * 3600
                if now - s.get("ck", 0) > 86400:          # 쿠키도 하루에 한 번 새로 내려 줌
                    s["ck"] = now
                    self._cookie = cookie(t, False)
                sess_save()
        return u

    def _need(self, role: str, temp_ok: bool = False):
        """권한 확인: 부족하면 401/403 응답 후 None. 임시 비밀번호 사용자는 비밀번호를 바꾸기 전까지 막음"""
        u = self._user()
        if not u:
            self._send(401, {"error": "로그인이 필요합니다", "login": "/login"})
            return None
        if u.get("mustChange") and not temp_ok:
            self._send(403, {"error": "임시 비밀번호입니다. 먼저 비밀번호를 바꿔 주세요", "mustChange": True, "login": "/account"})
            return None
        if ROLES.index(u["role"]) < ROLES.index(role):
            self._send(403, {"error": f"{ROLE_KO[role]} 권한이 필요합니다"})
            return None
        return u

    def _body(self, limit=64 * 1024):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            raise ValueError("보낸 내용이 없습니다")
        if n > limit:
            raise OverflowError
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _same_origin(self) -> bool:
        o = self.headers.get("Origin")
        if not o:
            return True
        return urlparse(o).netloc == self.headers.get("Host", "")

    def _file(self, p: Path, ctype="text/html; charset=utf-8"):
        if not p.exists():
            return self._send(500, f"{p.name} 파일이 없습니다.", "text/plain; charset=utf-8")
        self._send(200, p.read_bytes(), ctype)

    # ---- GET
    def do_GET(self):
        if not self._guard():
            return
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html", "/cement_plant_3d.html"):
            u = self._user()
            if not u:
                return self._redirect("/login")
            if u.get("mustChange"):
                return self._redirect("/account")
            return self._file(PAGE)
        if path == "/logo.png":
            return self._file(ROOT / "logo.png", "image/png")
        if path == "/login":
            return self._file(ROOT / "login.html")
        if path == "/account":
            if not self._user():
                return self._redirect("/login")
            return self._file(ROOT / "account.html")
        if path == "/api/me":
            u = self._user()
            out = {"user": None, "setup": not USERS.has_admin(), "local": is_local(self.ip), "knownIp": USERS.known_ip(self.ip)}
            if u:
                out["user"] = {k: u.get(k) for k in ("id", "name", "dept", "role")}
                out["user"]["mustChange"] = bool(u.get("mustChange"))
                if u["role"] == "admin" and not u.get("mustChange"):
                    out["pending"] = sum(1 for x in USERS.all() if x.get("status") == "pending")
            return self._send(200, out)
        if path in ("/업로드양식.xlsx", "/template.xlsx"):
            if not self._need("viewer"):
                return
            if not TEMPLATE.exists():
                return self._send(404, {"error": "업로드양식.xlsx가 없습니다"})
            return self._send(200, TEMPLATE.read_bytes(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": "attachment; filename*=UTF-8''" + quote("업로드양식.xlsx")})
        if path == "/api/status":
            su = self._need("viewer")
            if not su:
                return
            m = STORE.meta or {}
            return self._send(200, {"app": "blue365", "version": m.get("version"), "meta": STORE.meta,
                                    "needKey": bool(KEY), "watch": bool(WATCH), "urls": TEAM_URLS, "auth": True, "page": page_build(), "cfg": settings_read()[1], "sokbo": sokbo_read()[1], "yard": yard_read()[1], "yardWatch": dict(YWATCH) if YWATCH["on"] else None, "ai": ai_status() if su.get("role") == "admin" else None,
                                    "sokboWatch": {k: SWATCH[k] for k in ("on", "folder", "every", "last", "ok", "err", "got")},
                                    "mms": dict(MMS, t=MMSV["t"]) if MMS["on"] else None})
        if path == "/api/settings":
            if not self._need("viewer"):
                return
            d, stamp = settings_read()
            return self._send(200, {"settings": d, "stamp": stamp})
        if path == "/api/yard":
            if not self._need("viewer"):
                return
            d, _ = yard_read()
            return self._send(200, dict(d or {"yard": None, "meta": None}, hist=yard_hist_read()))
        if path == "/api/sokbo":
            if not self._need("viewer"):
                return
            d, _ = sokbo_read()
            return self._send(200, dict(d, hist=sokhist_read())) if d else self._send(404, {"error": "아직 올라온 출하속보가 없습니다", "hist": sokhist_read()})
        if path == "/api/mms":
            if not self._need("viewer"):
                return
            return self._send(200, {"t": MMSV["t"], "vals": MMSV["vals"], "ok": MMS["ok"], "err": MMS["err"]})
        if path == "/api/dataset":
            if not self._need("viewer"):
                return
            b = STORE.read()
            return self._send(200, b) if b else self._send(404, {"error": "아직 올라온 데이터가 없습니다"})
        if path == "/api/admin/users":
            if not self._need("admin"):
                return
            users = sorted(USERS.all(), key=lambda x: (x.get("status") != "pending", x.get("created") or ""))
            return self._send(200, {"users": [USERS.public(u) for u in users], "audit": USERS.audit_tail()})
        self._send(404, {"error": "없는 주소입니다"})

    # ---- POST
    def do_POST(self):
        if not self._guard():
            return
        if not self._same_origin():
            return self._send(403, {"error": "다른 사이트에서 온 요청은 받지 않습니다"})
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            return self._send(415, {"error": "JSON 형식 요청만 받습니다"})
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/dataset":
                return self._upload()
            body = self._body()
        except OverflowError:
            return self._send(413, {"error": "보낸 내용이 너무 큽니다"})
        except (ValueError, UnicodeDecodeError) as e:
            return self._send(400, {"error": f"형식 오류: {e}"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "형식 오류"})
        if path == "/api/login":
            return self._login(body)
        if path == "/api/logout":
            t = self._token()
            with SESS_LOCK:
                if SESS.pop(tk(t), None) if t else None:
                    sess_save()
            return self._send(200, {"ok": True}, extra={"Set-Cookie": "b365s=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if path == "/api/register":
            return self._register(body)
        if path == "/api/password":
            return self._password(body)
        if path == "/api/admin/user":
            return self._admin(body)
        if path == "/api/settings":
            return self._settings(body)
        if path == "/api/sokbo":
            return self._sokbo(body)
        if path == "/api/sokbo-hist":
            return self._sokhist(body)
        if path == "/api/yard":
            return self._yard(body)
        if path == "/api/ai":
            return self._ai(body)
        self._send(404, {"error": "없는 주소입니다"})

    def _ai(self, b):
        """AI 질의 — 관리자만 (API 요금이 관리자 키로 나감)"""
        u = self._need("admin")
        if not u:
            return
        q = str(b.get("q") or "").strip()[:2000]
        ctx = str(b.get("ctx") or "")[:150_000]
        hist = [h for h in (b.get("hist") or []) if isinstance(h, dict)][-6:]
        if not q:
            return self._send(400, {"error": "질문이 비어 있습니다"})
        if not AI_LOCK.acquire(blocking=False):
            return self._send(429, {"error": "다른 AI 질문을 처리하는 중입니다. 잠시 뒤 다시 시도하세요"})
        try:
            r = ai_ask(q, ctx, hist)
        except AIError as e:
            return self._send(400, {"error": str(e)})
        finally:
            AI_LOCK.release()
        USERS.log(u["id"], "AI 질의", f"{len(q)}자 · ${r['usage']['usd']:.3f}", self.ip)
        return self._send(200, r)

    def _yard(self, b):
        """원료 야드 재고 직접 입력 (편집 이상, 본인 비밀번호 다시 확인)"""
        u = self._need("editor")
        if not u:
            return
        if not USERS.verify(u["id"], b.get("password")):
            USERS.log(u["id"], "업로드 비밀번호 틀림", "원료 야드", self.ip)
            return self._send(401, {"error": "비밀번호가 맞지 않습니다 (입력 확인)"})
        try:
            y = yard_clean(b.get("yard"))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        meta = yard_store(y, f"{u['dept']} {u['name']}", "input")
        USERS.log(u["id"], "원료 야드 재고 입력", f"{y['date']} {y['shift']}차", self.ip)
        d, _ = yard_read()
        return self._send(200, {"ok": True, "yard": d["yard"], "meta": meta, "hist": yard_hist_read()})

    def _sokhist(self, b):
        """드라이브 폴더로 받은 PDF는 화면이 읽으므로, 처음 읽은 화면이 그 날짜 재고를 기록 (지금 서버의 속보 버전·날짜일 때만, 날짜당 한 번)"""
        u = self._need("viewer")
        if not u:
            return
        d, ver = sokbo_read()
        if not d or not ver or str(b.get("version")) != str(ver) or d.get("sokbo") is not None:
            return self._send(409, {"error": "지금 서버의 출하속보와 다릅니다"})
        ok = sokhist_put(str(b.get("date", "")), b.get("stock"), "pdf")
        return self._send(200, {"ok": ok, "hist": sokhist_read()})

    def _sokbo(self, b):
        """출하속보 올리기 (편집 이상, 본인 비밀번호 다시 확인) → data/sokbo.json"""
        u = self._need("editor")
        if not u:
            return
        if KEY and not hmac.compare_digest(self.headers.get("X-Upload-Key", "").encode(), KEY.encode()):
            return self._send(401, {"error": "업로드 비밀번호(서버 --key)가 맞지 않습니다"})
        if not USERS.verify(u["id"], b.get("password")):
            USERS.log(u["id"], "업로드 비밀번호 틀림", "출하속보", self.ip)
            return self._send(401, {"error": "비밀번호가 맞지 않습니다 (업로드 확인)"})
        try:
            s = sokbo_clean(b.get("sokbo"))
            if not isinstance(s, dict) or s.get("kind") != "sokbo" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get("date", ""))):
                raise ValueError("출하속보 형식이 올바르지 않습니다")
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        now = dt.datetime.now()
        fn = re.sub(r"[<>`\\/:*?\"|]", "", str((b.get("meta") or {}).get("fileName") or ""))[:80]
        meta = {"version": now.strftime("%Y%m%d%H%M%S%f"), "uploadedAt": now.isoformat(timespec="seconds"),
                "uploadedBy": f"{u['dept']} {u['name']}", "fileName": fn, "date": s["date"], "source": "upload"}
        p = sokbo_path()
        with SETTINGS_LOCK:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sokbo": s, "meta": meta}, ensure_ascii=False), "utf-8")
            os.replace(tmp, p)
        sokhist_put(s["date"], s.get("stock"), "upload")
        USERS.log(u["id"], "출하속보 업로드", f"{s['date']} {fn}", self.ip)
        self._send(200, {"ok": True, "sokbo": s, "meta": meta})

    def _login(self, b):
        now = time.time()
        fails = [t for t in FAILS.get(self.ip, []) if now - t < 600]
        FAILS[self.ip] = fails
        if len(fails) >= 10:
            return self._send(429, {"error": "로그인 실패가 많아 10분간 잠겼습니다. 잠시 후 다시 시도하세요."})
        u = USERS.verify(str(b.get("id", "")), b.get("pw"))
        if not u:
            fails.append(now)
            tried = str(b.get("id", ""))
            USERS.log(tried if ID_RE.match(tried) else "(형식 오류 아이디)", "로그인 실패", "", self.ip)
            return self._send(401, {"error": "아이디 또는 비밀번호가 맞지 않습니다"})
        st = u.get("status")
        if st == "pending":
            return self._send(403, {"error": "관리자 승인을 기다리는 중입니다. 승인되면 로그인할 수 있습니다."})
        if st == "rejected":
            return self._send(403, {"error": "등록 요청이 거절되었습니다. ‘ID 등록’ 탭에서 같은 아이디로 다시 신청할 수 있습니다."})
        if st != "active" or u.get("role") not in ROLES:
            return self._send(403, {"error": "사용이 중지된 계정입니다. 관리자에게 문의하세요."})
        FAILS.pop(self.ip, None)
        t = secrets.token_urlsafe(32)
        with SESS_LOCK:
            for k in [k for k, s in SESS.items() if s["exp"] < now]:
                SESS.pop(k, None)
            SESS[tk(t)] = {"uid": u["id"].lower(), "exp": now + SESSION_HOURS * 3600, "born": now, "ck": now}
            sess_save()
        USERS.update(u["id"], lastLogin=dt.datetime.now().isoformat(timespec="seconds"), lastIp=self.ip)
        USERS.mark_ip(self.ip, u["id"])
        USERS.log(u["id"], "로그인", ROLE_KO[u["role"]], self.ip)
        return self._send(200, {"ok": True, "user": {**{k: u.get(k) for k in ("id", "name", "dept", "role")}, "mustChange": bool(u.get("mustChange"))}},
                          extra={"Set-Cookie": cookie(t, u["role"] == "admin")})

    def _register(self, b):
        uid, pw = str(b.get("id", "")).strip(), b.get("pw")
        name, dept = str(b.get("name", "")).strip()[:20], str(b.get("dept", "")).strip()[:30]
        if not ID_RE.match(uid):
            return self._send(400, {"error": "아이디는 영문·숫자·_ . - 로 3~20자입니다"})
        if not pw_ok(pw):
            return self._send(400, {"error": "비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요"})
        if not name or not dept or re.search(r"[<>&\"'`]", name + dept):
            return self._send(400, {"error": "부서와 이름을 바르게 적어 주세요"})
        old = USERS.get(uid)
        again = bool(old) and old.get("status") == "rejected" and not b.get("setup")     # 거절된 요청은 다시 신청할 수 있음
        if old and not again:
            return self._send(409, {"error": "이미 있는 아이디입니다"})
        setup = bool(b.get("setup"))
        if setup:
            if USERS.has_admin():
                return self._send(403, {"error": "관리자 계정이 이미 있습니다"})
            if not is_local(self.ip):
                return self._send(403, {"error": "관리자 계정은 서버 PC에서만 만들 수 있습니다"})
            if not USERS.add(uid, pw, name, dept, self.ip, admin=True):
                return self._send(409, {"error": "이미 있는 아이디입니다"})
            USERS.log(uid, "관리자 계정 생성", f"{dept} {name}", self.ip)
            return self._send(200, {"ok": True, "admin": True})
        pend = sum(1 for x in USERS.all() if x.get("status") == "pending" and x.get("ip") == self.ip)
        if pend >= 3:
            return self._send(429, {"error": "이 PC에서 승인 대기 중인 요청이 이미 3건 있습니다"})
        if again:
            if not USERS.reapply(uid, pw, name, dept, self.ip):
                return self._send(409, {"error": "이미 있는 아이디입니다"})
            USERS.log(uid, "ID 재등록 요청", f"{dept} {name} (이전 요청 거절됨)", self.ip)
            return self._send(200, {"ok": True, "again": True})
        if not USERS.add(uid, pw, name, dept, self.ip):
            return self._send(409, {"error": "이미 있는 아이디입니다"})
        USERS.log(uid, "ID 등록 요청", f"{dept} {name}", self.ip)
        return self._send(200, {"ok": True})

    def _password(self, b):
        u = self._need("viewer", temp_ok=True)
        if not u:
            return
        if not USERS.verify(u["id"], b.get("old")):
            return self._send(401, {"error": "현재 비밀번호가 맞지 않습니다"})
        if not pw_ok(b.get("new")):
            return self._send(400, {"error": "새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요"})
        if b.get("new") == b.get("old"):
            return self._send(400, {"error": "새 비밀번호가 지금 비밀번호와 같습니다"})
        USERS.update(u["id"], pw=b["new"], mustChange=False)
        keep = tk(self._token() or "")             # 다른 PC에 남은 로그인은 끊음 (지금 화면은 유지)
        with SESS_LOCK:
            for k in [k for k, x in SESS.items() if x["uid"] == u["id"].lower() and k != keep]:
                SESS.pop(k, None)
            sess_save()
        USERS.log(u["id"], "비밀번호 변경", "", self.ip)
        return self._send(200, {"ok": True})

    def _settings(self, b):
        me = self._need("admin")                    # 관리기준은 관리자만 바꿈
        if not me:
            return
        try:
            d = settings_clean(b.get("settings"))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        d["at"] = dt.datetime.now().isoformat(timespec="seconds")
        d["by"] = f"{me['dept']} {me['name']}"
        p = settings_path()
        with SETTINGS_LOCK:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, p)
        USERS.log(me["id"], "관리기준 변경", f"f-CaO {d['fcao']['target']}±{d['fcao']['tol']}%, 주의 {d['fcao']['warnRate']}%", self.ip)
        return self._send(200, {"ok": True, "settings": d, "stamp": d["at"]})

    def _admin(self, b):
        me = self._need("admin")
        if not me:
            return
        uid, act = str(b.get("id", "")), b.get("action")
        u = USERS.get(uid)
        if not u:
            return self._send(404, {"error": "없는 사용자입니다"})
        if u["id"].lower() == me["id"].lower() and act in ("role", "disable", "delete", "reject"):
            return self._send(400, {"error": "자기 계정의 권한·상태는 바꿀 수 없습니다 (관리자 잠김 방지)"})
        now = dt.datetime.now().isoformat(timespec="seconds")
        role = b.get("role")
        if act in ("approve", "role"):
            if role not in ROLES:
                return self._send(400, {"error": "권한을 골라 주세요"})
            USERS.update(uid, role=role, status="active", approvedBy=me["id"], approvedAt=now)
            USERS.log(me["id"], "승인" if act == "approve" else "권한 변경", f"{u['id']} ({u['dept']} {u['name']}) → {ROLE_KO[role]}", self.ip)
        elif act == "reject":
            USERS.update(uid, status="rejected", role=None)
            USERS.log(me["id"], "등록 거절", f"{u['id']} ({u['dept']} {u['name']})", self.ip)
        elif act == "disable":
            USERS.update(uid, status="disabled")
            self._kill(uid)
            USERS.log(me["id"], "사용 중지", u["id"], self.ip)
        elif act == "enable":
            if u.get("role") not in ROLES:
                return self._send(400, {"error": "먼저 권한을 정해 승인해 주세요"})
            USERS.update(uid, status="active")
            USERS.log(me["id"], "사용 재개", u["id"], self.ip)
        elif act == "reset":
            temp = "B" + secrets.token_hex(4) + "7"
            USERS.update(uid, pw=temp, mustChange=True)
            self._kill(uid)
            USERS.log(me["id"], "비밀번호 초기화", u["id"], self.ip)
            return self._send(200, {"ok": True, "temp": temp})
        elif act == "delete":
            USERS.delete(uid)
            self._kill(uid)
            USERS.log(me["id"], "삭제", u["id"], self.ip)
        else:
            return self._send(400, {"error": "알 수 없는 작업입니다"})
        if act in ("role",):
            self._kill(uid)       # 권한이 바뀌면 다시 로그인
        return self._send(200, {"ok": True})

    @staticmethod
    def _kill(uid):
        with SESS_LOCK:
            for k in [k for k, s in SESS.items() if s["uid"] == uid.lower()]:
                SESS.pop(k, None)
            sess_save()

    def _upload(self):
        u = self._need("editor")
        if not u:
            return
        if KEY and not hmac.compare_digest(self.headers.get("X-Upload-Key", "").encode(), KEY.encode()):
            return self._send(401, {"error": "업로드 비밀번호(서버 --key)가 맞지 않습니다"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return self._send(400, {"error": "보낸 내용이 없습니다"})
        if n > MAX_BODY:
            return self._send(413, {"error": "파일이 너무 큽니다 (최대 25MB)"})
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return self._send(400, {"error": f"데이터 형식 오류: {e}"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "데이터 형식 오류"})
        if not USERS.verify(u["id"], body.get("password")):          # 업로드할 때마다 본인 비밀번호 다시 확인
            USERS.log(u["id"], "업로드 비밀번호 틀림", "", self.ip)
            return self._send(401, {"error": "비밀번호가 맞지 않습니다 (업로드 확인)"})
        meta_in = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        meta_in["source"] = "upload"                                 # 올린 사람·출처는 서버가 정함
        meta_in["uploadedBy"] = f"{u['dept']} {u['name']}"
        try:
            if body.get("qms") is not None:
                meta = STORE.save(body.get("qms"), meta_in, "qms")
            else:
                meta = STORE.save(body.get("sheets"), meta_in, "sheets")
        except (ValueError, AttributeError) as e:
            return self._send(400, {"error": f"데이터 형식 오류: {e}"})
        USERS.log(u["id"], "데이터 업로드", f"{meta['fileName']} (버전 {meta['version']})", self.ip)
        self._send(200, {"ok": True, "meta": meta})


TEAM_URLS: list[str] = []


def lan_ips() -> list[str]:
    """이 PC의 사내망 IPv4 주소 (팀원 접속용). 실제로 외부에 패킷을 보내지 않습니다."""
    found: list[str] = []
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))      # UDP connect 는 경로만 정하고 전송하지 않음
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127.") and ip not in found:
                    found.append(ip)
        except OSError:
            pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    global STORE, KEY, WATCH, ALLOW, USERS, HISTORY_MB, SESS_FILE, BACKUP_DIR, BACKUP_KEEP
    ap = argparse.ArgumentParser(description="Blue365 시멘트 공정 3D 팀 공유 서버")
    ap.add_argument("--host", default="0.0.0.0", help="받을 주소 (기본: 모든 네트워크)")
    ap.add_argument("--port", type=int, default=8365, help="포트 (기본 8365)")
    ap.add_argument("--data", default=str(ROOT / "data"), help="데이터 저장 폴더")
    ap.add_argument("--watch", help="최신 .xlsx를 자동으로 읽을 공유 폴더")
    ap.add_argument("--interval", type=int, default=60, help="공유 폴더 확인 주기(초, 기본 60)")
    ap.add_argument("--allow", default="", help="접속 허용 대역, 쉼표로 구분 (예: 192.168.10.0/24,10.20.). 비우면 사내망 사설 IP 전체")
    ap.add_argument("--allow-any", action="store_true", help="접속 대역 제한 끄기 (권장하지 않음)")
    ap.add_argument("--history-mb", type=int, default=HISTORY_MB, help="이력(data/history) 최대 용량 MB (기본 1024)")
    ap.add_argument("--backup-dir", default="", help="자동 백업을 둘 폴더 (기본: 데이터 폴더 안 backup). 다른 디스크·공유 폴더를 권장")
    ap.add_argument("--backup-keep", type=int, default=14, help="보관할 백업 개수 (기본 14일치)")
    ap.add_argument("--no-backup", action="store_true", help="자동 백업 끄기")
    ap.add_argument("--key", default=os.environ.get("B365_UPLOAD_KEY", ""), help="(선택) 업로드에 추가로 요구할 서버 공통 암호")
    ap.add_argument("--sokbo-watch", default="", help="출하속보 PDF가 들어오는 폴더. auto = 구글 드라이브의 ‘Blue365 출하속보’ 폴더를 자동으로 찾음")
    ap.add_argument("--sokbo-interval", type=int, default=60, help="출하속보 폴더 확인 주기(초, 기본 60)")
    ap.add_argument("--yard-watch", default="", help="원료 야드 재고 JSON 폴더. auto = 구글 드라이브의 ‘Blue365 원료재고’ 폴더")
    ap.add_argument("--mms", action="store_true", help="MMS(Manufacturing Monitor)에서 매칭표의 설비 값을 읽기 전용으로 가져옴")
    ap.add_argument("--mms-every", type=int, default=30, help="MMS 값 읽는 주기(초, 기본 30, 최소 10)")
    ap.add_argument("--mms-map", default=str(ROOT / MMS_MAP_NAME), help=f"매칭표 엑셀 (기본: 서버 폴더의 {MMS_MAP_NAME})")
    ap.add_argument("--mms-setup", action="store_true", help="MMS 주소·아이디·비밀번호 저장 (로그인 시험 후 저장)")
    ap.add_argument("--mms-test", action="store_true", help="MMS 로그인·값 요청 형식 시험 (서버는 켜지 않음)")
    ap.add_argument("--ai-setup", action="store_true", help="AI 질의(관리자 전용) Claude API 키·월 한도 저장")
    a = ap.parse_args()

    if not PAGE.exists():
        sys.exit("cement_plant_3d.html이 없습니다. 같은 폴더에서 python build.py를 먼저 실행하세요.")
    HISTORY_MB = max(50, a.history_mb)
    STORE = Store(Path(a.data))
    USERS = Users(STORE.dir)
    if a.mms_setup:
        return mms_setup()
    if a.mms_test:
        return mms_test(Path(a.mms_map))
    if a.ai_setup:
        return ai_setup()
    SESS_FILE = STORE.dir / "sessions.json"
    sess_load()
    BACKUP_KEEP = max(1, a.backup_keep)
    BACKUP_DIR = None if a.no_backup else (Path(a.backup_dir) if a.backup_dir else STORE.dir / "backup")
    if BACKUP_DIR:
        threading.Thread(target=backup_loop, daemon=True).start()
    KEY = a.key
    try:
        ALLOW = [] if a.allow_any else (parse_allow(a.allow) if a.allow else parse_allow(",".join(PRIVATE_NETS))) + parse_allow(",".join(LOCAL_NETS))
    except ValueError as e:
        sys.exit(f"--allow 값이 올바르지 않습니다: {e}")
    if a.watch:
        folder = Path(a.watch)
        if not folder.is_dir():
            sys.exit(f"공유 폴더를 찾을 수 없습니다: {folder}")
        WATCH = str(folder)
        threading.Thread(target=watch_loop, args=(folder, max(10, a.interval)), daemon=True).start()

    sokbo_txt = "사용 안 함"
    if a.sokbo_watch:
        every = max(15, a.sokbo_interval)
        sf = find_sokbo_dir(a.sokbo_watch)
        threading.Thread(target=sokbo_watch_loop, args=(a.sokbo_watch, every), daemon=True).start()
        sokbo_txt = (f"{sf} · {every}초마다 최신 PDF" if sf else
                     f"아직 폴더를 찾지 못함 ({'구글 드라이브의 ‘' + SOKBO_DIR_NAME + '’' if a.sokbo_watch.lower() == 'auto' else a.sokbo_watch}) — {every}초마다 다시 찾습니다")

    yard_txt = "사용 안 함"
    if a.yard_watch:
        yf = find_yard_dir(a.yard_watch)
        threading.Thread(target=yard_watch_loop, args=(a.yard_watch, 60), daemon=True).start()
        yard_txt = f"{yf} · 60초마다" if yf else f"아직 폴더를 찾지 못함 (구글 드라이브의 ‘{YARD_DIR_NAME}’) — 60초마다 다시 찾습니다"
    mms_txt = "사용 안 함"
    if a.mms:
        every = max(10, a.mms_every)
        threading.Thread(target=mms_loop, args=(Path(a.mms_map), every), daemon=True).start()
        mms_txt = (f"{every}초마다 · 매칭표 {Path(a.mms_map).name}" + ("" if Path(a.mms_map).exists() else " (파일 없음!)")
                   + ("" if mms_cfg_path().exists() else "  ※ 아직 설정 안 됨: MMS설정.bat 먼저 실행"))

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    global TEAM_URLS
    host = socket.gethostname()
    ips = lan_ips()
    TEAM_URLS = [f"http://{ip}:{a.port}" for ip in ips]
    print("=" * 56)
    print(" Blue365 시멘트 공정 3D · 팀 공유 서버")
    print(f"  이 PC에서   : http://localhost:{a.port}")
    if TEAM_URLS:
        print(f"  팀원 접속   : {TEAM_URLS[0]}   ← 이 주소를 팀원에게 알려 주세요")
        for u in TEAM_URLS[1:]:
            print(f"                {u}   (다른 네트워크 카드)")
    else:
        print("  팀원 접속   : IP 주소를 찾지 못했습니다. 명령 프롬프트에서 ipconfig 로 IPv4 주소를 확인해")
        print(f"                http://<IPv4 주소>:{a.port} 로 접속하세요.")
    if host.isascii() and host:
        print(f"  (이름 주소)  : http://{host}:{a.port}   ← 사내 DNS에 등록된 경우에만 동작")
    else:
        print(f"  ※ 컴퓨터 이름({host})에 한글이 있어 이름 주소는 쓸 수 없습니다. 위 IP 주소를 쓰세요.")
    pm = re.search(rb'name="b365-build" content="([^"]+)"', PAGE.read_bytes()[:4000]) if PAGE.exists() else None
    print(f"  화면 파일   : {PAGE.name} · 버전 {pm.group(1).decode() if pm else '알 수 없음 (예전 파일입니다. 최신 cement_plant_3d.html로 바꾸세요)'}")
    print(f"  데이터 저장 : {STORE.dir}")
    n_users = sum(1 for u in USERS.all() if u.get("status") == "active")
    n_pend = sum(1 for u in USERS.all() if u.get("status") == "pending")
    print(f"  로그인      : 사용 (승인된 사용자 {n_users}명, 승인 대기 {n_pend}건, 유지 중인 로그인 {len(SESS)}건)")
    print(f"  로그인 유지 : 뷰어·편집은 화면을 켜 둔 동안 계속 유지(무활동 {SESSION_HOURS}시간 뒤 종료), 관리자는 {SESSION_HOURS}시간")
    print("  업로드      : 편집 권한 + 업로드할 때 본인 비밀번호 확인" + (" + 서버 업로드 암호(--key)" if KEY else ""))
    if not USERS.has_admin():
        print(f"  ★ 관리자 계정이 없습니다. 이 PC의 브라우저에서 http://localhost:{a.port} 로 접속해 먼저 만드세요.")
    shown = [str(n) for n in ALLOW if str(n) not in LOCAL_NETS and n.version == 4]
    print(f"  접속 허용   : {'제한 없음 (주의: 외부 접속 가능)' if not ALLOW else ('사내망 사설 IP 전체' if not a.allow else ', '.join(shown))}")
    odd = [ip for ip in ips if ALLOW and not allowed(ip)]
    if odd:
        print(f"  ※ 이 PC 주소({', '.join(odd)})가 허용 대역 밖입니다. 회사가 공인 IP를 사내망에 쓰는 경우이니")
        print(f"     --allow {odd[0].rsplit('.', 1)[0]}.  처럼 사내 대역을 지정하세요.")
    print(f"  자동 백업   : {str(BACKUP_DIR) + f' (하루 1회, 최근 {BACKUP_KEEP}개 보관)' if BACKUP_DIR else '사용 안 함'}")
    if BACKUP_DIR and not a.backup_dir:
        print("                ※ 같은 디스크입니다. PC 고장에 대비하려면 --backup-dir 로 다른 디스크·공유 폴더를 지정하세요.")
    print(f"  공유 폴더   : {WATCH or '사용 안 함'}")
    print(f"  출하속보 폴더: {sokbo_txt}")
    print(f"  원료 야드 폴더: {yard_txt}")
    _ai = ai_status()
    print(f"  AI 질의     : {'사용 (관리자 전용 · ' + AI_MODEL + ' · 월 한도 $' + format(_ai.get('cap') or 0, 'g') + ' · 이번 달 $' + str(_ai.get('used')) + ' · 사내 문서 ' + str(_ai.get('docs')) + '개)' if _ai['ready'] else '사용 안 함 (' + _ai['why'] + ')'}")
    print(f"  MMS 연결    : {mms_txt}")
    print("  끝내려면 Ctrl+C")
    print("=" * 56, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


if __name__ == "__main__":
    main()
