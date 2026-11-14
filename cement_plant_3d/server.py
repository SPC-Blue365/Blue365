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
import email
import imaplib
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
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
         "source": str(meta.get("source") or "mail"), "mailDate": str(meta.get("mailDate") or "")}
    p = sokbo_path()
    with SETTINGS_LOCK:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sokbo": None, "pdf": base64.b64encode(pdf).decode(), "meta": m}, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
    return m


# ---- Gmail 자동 읽기 (IMAP, 앱 비밀번호) ----
MAIL = {"on": False, "every": 0, "last": None, "ok": None, "err": "", "got": None}
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def mail_hdr(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def mail_pdfs(msg) -> list:
    """메일의 PDF 첨부 [(파일 이름, 내용)]"""
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        fn = mail_hdr(part.get_filename() or "")
        if fn.lower().endswith(".pdf") or part.get_content_type() == "application/pdf":
            data = part.get_payload(decode=True) or b""
            if data[:5] == b"%PDF-":
                out.append((fn or "출하속보.pdf", data))
    return out


def mail_check_once(user: str, pw: str, kws: list, sender: str, days: int, seen: set, factory=None) -> list:
    """받은편지함에서 최근 days일 안의 새 출하속보 메일 → [(Message-ID, 제목, 메일 시각, [(파일, PDF)])] (오래된 것부터)"""
    M = (factory or imaplib.IMAP4_SSL)("imap.gmail.com", 993)
    try:
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        d = dt.date.today() - dt.timedelta(days=max(1, days))
        typ, data = M.uid("SEARCH", None, "SINCE", f"{d.day:02d}-{MON[d.month - 1]}-{d.year}")
        uids = (data[0] or b"").split() if typ == "OK" and data else []
        if not uids:
            return []
        uids = uids[-300:]
        typ, hd = M.uid("FETCH", b",".join(uids), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID DATE)])")
        cand = []
        for it in hd or []:
            if not isinstance(it, tuple) or len(it) < 2:
                continue
            m = re.search(rb"UID (\d+)", it[0])
            if not m:
                continue
            h = email.message_from_bytes(it[1])
            subj, frm, mid = mail_hdr(h.get("Subject")), mail_hdr(h.get("From")), (h.get("Message-ID") or "").strip() or ("uid:" + m.group(1).decode())
            s0 = re.sub(r"\s", "", subj)
            if not any(k and k in s0 for k in kws) or (sender and sender.lower() not in frm.lower()) or mid in seen:
                continue
            try:
                when = parsedate_to_datetime(h.get("Date")).astimezone().replace(tzinfo=None)
            except Exception:
                when = dt.datetime.now()
            cand.append((when, m.group(1), mid, subj))
        out = []
        for when, uid, mid, subj in sorted(cand):
            typ, full = M.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((x[1] for x in (full or []) if isinstance(x, tuple) and len(x) > 1), None)
            if raw:
                out.append((mid, subj, when, mail_pdfs(email.message_from_bytes(raw))))
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def mail_loop(user: str, pw: str, kws: list, sender: str, days: int, every: int) -> None:
    sp = STORE.dir / "mail_seen.json"
    try:
        seen = set(json.loads(sp.read_text("utf-8")))
    except (OSError, ValueError):
        seen = set()
    MAIL.update(on=True, every=every)
    while True:
        try:
            found = mail_check_once(user, pw, kws, sender, days, seen)
            for mid, subj, when, pdfs in found:
                seen.add(mid)
                if not pdfs:
                    log(f"메일 출하속보: '{subj}'에 PDF 첨부가 없어 건너뜀")
                    continue
                cur, _ = sokbo_read()
                at = (cur or {}).get("meta", {}).get("mailDate") or (cur or {}).get("meta", {}).get("uploadedAt") or ""
                if at and when.isoformat(timespec="seconds") <= at[:19]:   # 이미 더 최신 속보가 있으면 덮어쓰지 않음
                    continue
                fn, pdf = max(pdfs, key=lambda x: len(x[1]))
                m = sokbo_store_pdf(pdf, {"fileName": fn, "uploadedBy": "자동 (메일)", "source": "mail", "mailDate": when.isoformat(timespec="seconds")})
                if m:
                    MAIL["got"] = when.isoformat(timespec="minutes")
                    log(f"메일 출하속보 반영: {fn} ({when:%m/%d %H:%M} 메일)")
                    USERS.log("(자동)", "출하속보 메일 반영", fn, "-")
            if found:
                sp.write_text(json.dumps(sorted(seen)[-800:], ensure_ascii=False), "utf-8")
            MAIL.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=True, err="")
        except imaplib.IMAP4.error as e:
            MAIL.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=False, err=("로그인 실패 — 계정·앱 비밀번호 확인" if "AUTH" in str(e).upper() else str(e))[:120])
            log(f"메일 확인 오류: {MAIL['err']}")
        except Exception as e:   # 네트워크 끊김 등: 다음 주기에 다시
            MAIL.update(last=dt.datetime.now().isoformat(timespec="minutes"), ok=False, err=f"{type(e).__name__}: {e}"[:120])
            log(f"메일 확인 오류: {MAIL['err']}")
        time.sleep(every)


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
    names = [n for n in ("users.json", "settings.json", "latest.json", "sokbo.json") if (src / n).exists()] + sorted(f.name for f in src.glob("audit*.log"))
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
        if not self.path.startswith("/api/status") and not self.path.startswith("/api/me"):
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
            if not self._need("viewer"):
                return
            m = STORE.meta or {}
            return self._send(200, {"app": "blue365", "version": m.get("version"), "meta": STORE.meta,
                                    "needKey": bool(KEY), "watch": bool(WATCH), "urls": TEAM_URLS, "auth": True, "page": page_build(), "cfg": settings_read()[1], "sokbo": sokbo_read()[1],
                                    "mail": {k: MAIL[k] for k in ("on", "every", "last", "ok", "err", "got")}})
        if path == "/api/settings":
            if not self._need("viewer"):
                return
            d, stamp = settings_read()
            return self._send(200, {"settings": d, "stamp": stamp})
        if path == "/api/sokbo":
            if not self._need("viewer"):
                return
            d, _ = sokbo_read()
            return self._send(200, d) if d else self._send(404, {"error": "아직 올라온 출하속보가 없습니다"})
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
        self._send(404, {"error": "없는 주소입니다"})

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
    ap.add_argument("--mail", default="", help="출하속보 메일을 읽을 Gmail 주소 (앱 비밀번호는 환경 변수 B365_MAIL_PW 또는 --mail-pw-file)")
    ap.add_argument("--mail-pw-file", default="", help="Gmail 앱 비밀번호를 적은 파일 (환경 변수 대신)")
    ap.add_argument("--mail-subject", default="출하속보,出荷速報", help="메일 제목에 들어 있는 말 (쉼표로 여러 개, 기본: 출하속보,出荷速報)")
    ap.add_argument("--mail-from", default="", help="(선택) 보낸 사람 주소·이름의 일부로 거르기")
    ap.add_argument("--mail-interval", type=int, default=600, help="메일 확인 주기(초, 기본 600 = 10분, 최소 120)")
    ap.add_argument("--mail-days", type=int, default=3, help="며칠 전 메일까지 볼지 (기본 3)")
    a = ap.parse_args()

    if not PAGE.exists():
        sys.exit("cement_plant_3d.html이 없습니다. 같은 폴더에서 python build.py를 먼저 실행하세요.")
    HISTORY_MB = max(50, a.history_mb)
    STORE = Store(Path(a.data))
    USERS = Users(STORE.dir)
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

    mail_txt = "사용 안 함"
    if a.mail:
        pw = os.environ.get("B365_MAIL_PW", "")
        if a.mail_pw_file:
            try:
                pw = Path(a.mail_pw_file).read_text("utf-8").strip()
            except OSError as e:
                sys.exit(f"--mail-pw-file 을 읽지 못했습니다: {e}")
        pw = pw.replace(" ", "")
        if not pw:
            sys.exit("Gmail 앱 비밀번호가 없습니다. 환경 변수 B365_MAIL_PW 를 설정하거나 --mail-pw-file 로 파일을 지정하세요.")
        kws = [re.sub(r"\s", "", k) for k in a.mail_subject.split(",") if k.strip()]
        every = max(120, a.mail_interval)
        threading.Thread(target=mail_loop, args=(a.mail, pw, kws, a.mail_from, a.mail_days, every), daemon=True).start()
        u, _, dom = a.mail.partition("@")
        mail_txt = f"{u[:2]}***@{dom} · {every // 60}분마다 · 제목에 '{'·'.join(kws)}' + PDF 첨부"

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
    print(f"  메일 자동   : {mail_txt}")
    print("  끝내려면 Ctrl+C")
    print("=" * 56, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


if __name__ == "__main__":
    main()
