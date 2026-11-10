#!/usr/bin/env python3
"""Blue365 시멘트 공정 3D — 사내망 팀 공유 서버

파이썬 표준 라이브러리만 사용합니다(추가 설치 없음, 인터넷 불필요).

  python server.py                         → 서버 창에 표시되는 http://<이 PC IP>:8365 로 팀원 접속
  python server.py --watch "\\\\서버\\품질\\업로드"   → 공유 폴더의 최신 .xlsx 자동 반영
  python server.py --key 비밀번호            → 업로드할 때 비밀번호 요구

하는 일
  GET  /login            로그인 · ID 등록 (승인 후 로그인)
  GET  /account          내 계정 · (관리자) 사용자 승인·권한 관리
  GET  /                 화면(cement_plant_3d.html) — 로그인 필요
  GET  /업로드양식.xlsx    업로드 양식
  GET  /api/status       서버 상태와 최신 데이터 버전
  GET  /api/dataset      최신 데이터(JSON)
  POST /api/dataset      화면에서 올린 데이터 저장 → 모든 접속자에게 20초 안에 반영
  저장 위치: data/latest.json, 이력은 data/history/ (최근 200개 보관)
"""
from __future__ import annotations

import argparse
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
            old = sorted(self.hist.glob("*.json"))[:-KEEP_HISTORY]
            for f in old:
                f.unlink(missing_ok=True)
            self.meta = meta
        return meta

    def read(self) -> bytes | None:
        with self.lock:
            return self.latest.read_bytes() if self.latest.exists() else None


STORE: Store
KEY = ""

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
SESSION_HOURS = 12
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
        line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{actor}\t{action}\t{detail}\t{ip}\n"
        with self.lock, open(self.audit, "a", encoding="utf-8") as f:
            f.write(line)
        log(f"[기록] {actor} · {action} · {detail}")

    def audit_tail(self, n=60):
        if not self.audit.exists():
            return []
        lines = self.audit.read_text("utf-8").splitlines()[-n:]
        return [dict(zip(("t", "who", "act", "detail", "ip"), (l.split("\t") + [""] * 5)[:5])) for l in reversed(lines)]

    def has_admin(self) -> bool:
        return any(u.get("role") == "admin" and u.get("status") == "active" for u in self.data["users"].values())

    def get(self, uid: str):
        return self.data["users"].get((uid or "").lower())

    def add(self, uid, pw, name, dept, ip, admin=False):
        salt = secrets.token_hex(16)
        u = {"id": uid, "name": name, "dept": dept, "salt": salt, "hash": self._hash(pw, salt),
             "role": "admin" if admin else None, "status": "active" if admin else "pending",
             "created": dt.datetime.now().isoformat(timespec="seconds"), "ip": ip, "lastLogin": None, "lastIp": None}
        with self.lock:
            self.data["users"][uid.lower()] = u
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
        return {k: u.get(k) for k in ("id", "name", "dept", "role", "status", "created", "ip", "lastLogin", "lastIp", "approvedBy", "approvedAt")}


USERS: Users
SESS: dict = {}            # 토큰 → {uid, exp}
SESS_LOCK = threading.Lock()
FAILS: dict = {}           # IP → [실패 시각...] (로그인 10회/10분 초과 시 잠시 차단)


def is_local(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
        if a.version == 6 and a.ipv4_mapped:
            a = a.ipv4_mapped
        return a.is_loopback
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "Blue365/1.0"

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
        with SESS_LOCK:
            s = SESS.get(t)
            if not s or s["exp"] < time.time():
                SESS.pop(t, None)
                return None
        u = USERS.get(s["uid"])
        if not u or u.get("status") != "active" or u.get("role") not in ROLES:
            return None
        return u

    def _need(self, role: str):
        """권한 확인: 부족하면 401/403 응답 후 None"""
        u = self._user()
        if not u:
            self._send(401, {"error": "로그인이 필요합니다", "login": "/login"})
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
            if not self._user():
                return self._redirect("/login")
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
                if u["role"] == "admin":
                    out["pending"] = sum(1 for x in USERS.data["users"].values() if x.get("status") == "pending")
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
                                    "needKey": bool(KEY), "watch": bool(WATCH), "urls": TEAM_URLS, "auth": True})
        if path == "/api/dataset":
            if not self._need("viewer"):
                return
            b = STORE.read()
            return self._send(200, b) if b else self._send(404, {"error": "아직 올라온 데이터가 없습니다"})
        if path == "/api/admin/users":
            if not self._need("admin"):
                return
            users = sorted(USERS.data["users"].values(), key=lambda x: (x.get("status") != "pending", x.get("created") or ""))
            return self._send(200, {"users": [USERS.public(u) for u in users], "audit": USERS.audit_tail()})
        self._send(404, {"error": "없는 주소입니다"})

    # ---- POST
    def do_POST(self):
        if not self._guard():
            return
        if not self._same_origin():
            return self._send(403, {"error": "다른 사이트에서 온 요청은 받지 않습니다"})
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
                SESS.pop(t, None)
            return self._send(200, {"ok": True}, extra={"Set-Cookie": "b365s=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if path == "/api/register":
            return self._register(body)
        if path == "/api/password":
            return self._password(body)
        if path == "/api/admin/user":
            return self._admin(body)
        self._send(404, {"error": "없는 주소입니다"})

    def _login(self, b):
        now = time.time()
        fails = [t for t in FAILS.get(self.ip, []) if now - t < 600]
        FAILS[self.ip] = fails
        if len(fails) >= 10:
            return self._send(429, {"error": "로그인 실패가 많아 10분간 잠겼습니다. 잠시 후 다시 시도하세요."})
        u = USERS.verify(str(b.get("id", "")), b.get("pw"))
        if not u:
            fails.append(now)
            USERS.log(str(b.get("id", ""))[:20] or "-", "로그인 실패", "", self.ip)
            return self._send(401, {"error": "아이디 또는 비밀번호가 맞지 않습니다"})
        st = u.get("status")
        if st == "pending":
            return self._send(403, {"error": "관리자 승인을 기다리는 중입니다. 승인되면 로그인할 수 있습니다."})
        if st == "rejected":
            return self._send(403, {"error": "등록 요청이 거절되었습니다. 관리자에게 문의하세요."})
        if st != "active" or u.get("role") not in ROLES:
            return self._send(403, {"error": "사용이 중지된 계정입니다. 관리자에게 문의하세요."})
        FAILS.pop(self.ip, None)
        t = secrets.token_urlsafe(32)
        with SESS_LOCK:
            for k in [k for k, s in SESS.items() if s["exp"] < now]:
                SESS.pop(k, None)
            SESS[t] = {"uid": u["id"].lower(), "exp": now + SESSION_HOURS * 3600}
        USERS.update(u["id"], lastLogin=dt.datetime.now().isoformat(timespec="seconds"), lastIp=self.ip)
        USERS.mark_ip(self.ip, u["id"])
        USERS.log(u["id"], "로그인", ROLE_KO[u["role"]], self.ip)
        return self._send(200, {"ok": True, "user": {k: u.get(k) for k in ("id", "name", "dept", "role")}},
                          extra={"Set-Cookie": f"b365s={t}; Path=/; Max-Age={SESSION_HOURS * 3600}; HttpOnly; SameSite=Strict"})

    def _register(self, b):
        uid, pw = str(b.get("id", "")).strip(), b.get("pw")
        name, dept = str(b.get("name", "")).strip()[:20], str(b.get("dept", "")).strip()[:30]
        if not ID_RE.match(uid):
            return self._send(400, {"error": "아이디는 영문·숫자·_ . - 로 3~20자입니다"})
        if not pw_ok(pw):
            return self._send(400, {"error": "비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요"})
        if not name or not dept or re.search(r"[<>&\"'`]", name + dept):
            return self._send(400, {"error": "부서와 이름을 바르게 적어 주세요"})
        if USERS.get(uid):
            return self._send(409, {"error": "이미 있는 아이디입니다"})
        setup = bool(b.get("setup"))
        if setup:
            if USERS.has_admin():
                return self._send(403, {"error": "관리자 계정이 이미 있습니다"})
            if not is_local(self.ip):
                return self._send(403, {"error": "관리자 계정은 서버 PC에서만 만들 수 있습니다"})
            USERS.add(uid, pw, name, dept, self.ip, admin=True)
            USERS.log(uid, "관리자 계정 생성", f"{dept} {name}", self.ip)
            return self._send(200, {"ok": True, "admin": True})
        pend = sum(1 for x in USERS.data["users"].values() if x.get("status") == "pending" and x.get("ip") == self.ip)
        if pend >= 3:
            return self._send(429, {"error": "이 PC에서 승인 대기 중인 요청이 이미 3건 있습니다"})
        USERS.add(uid, pw, name, dept, self.ip)
        USERS.log(uid, "ID 등록 요청", f"{dept} {name}", self.ip)
        return self._send(200, {"ok": True})

    def _password(self, b):
        u = self._need("viewer")
        if not u:
            return
        if not USERS.verify(u["id"], b.get("old")):
            return self._send(401, {"error": "현재 비밀번호가 맞지 않습니다"})
        if not pw_ok(b.get("new")):
            return self._send(400, {"error": "새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요"})
        USERS.update(u["id"], pw=b["new"], mustChange=False)
        USERS.log(u["id"], "비밀번호 변경", "", self.ip)
        return self._send(200, {"ok": True})

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
        if not USERS.verify(u["id"], body.get("password")):          # 업로드할 때마다 본인 비밀번호 다시 확인
            USERS.log(u["id"], "업로드 비밀번호 틀림", "", self.ip)
            return self._send(401, {"error": "비밀번호가 맞지 않습니다 (업로드 확인)"})
        meta_in = body.get("meta") or {}
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
    global STORE, KEY, WATCH, ALLOW, USERS
    ap = argparse.ArgumentParser(description="Blue365 시멘트 공정 3D 팀 공유 서버")
    ap.add_argument("--host", default="0.0.0.0", help="받을 주소 (기본: 모든 네트워크)")
    ap.add_argument("--port", type=int, default=8365, help="포트 (기본 8365)")
    ap.add_argument("--data", default=str(ROOT / "data"), help="데이터 저장 폴더")
    ap.add_argument("--watch", help="최신 .xlsx를 자동으로 읽을 공유 폴더")
    ap.add_argument("--interval", type=int, default=60, help="공유 폴더 확인 주기(초, 기본 60)")
    ap.add_argument("--allow", default="", help="접속 허용 대역, 쉼표로 구분 (예: 192.168.10.0/24,10.20.). 비우면 사내망 사설 IP 전체")
    ap.add_argument("--allow-any", action="store_true", help="접속 대역 제한 끄기 (권장하지 않음)")
    ap.add_argument("--key", default=os.environ.get("B365_UPLOAD_KEY", ""), help="업로드 비밀번호(영문·숫자)")
    a = ap.parse_args()

    if not PAGE.exists():
        sys.exit("cement_plant_3d.html이 없습니다. 같은 폴더에서 python build.py를 먼저 실행하세요.")
    STORE = Store(Path(a.data))
    USERS = Users(STORE.dir)
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
    n_users = sum(1 for u in USERS.data["users"].values() if u.get("status") == "active")
    n_pend = sum(1 for u in USERS.data["users"].values() if u.get("status") == "pending")
    print(f"  로그인      : 사용 (승인된 사용자 {n_users}명, 승인 대기 {n_pend}건)")
    print("  업로드      : 편집 권한 + 업로드할 때 본인 비밀번호 확인" + (" + 서버 업로드 암호(--key)" if KEY else ""))
    if not USERS.has_admin():
        print(f"  ★ 관리자 계정이 없습니다. 이 PC의 브라우저에서 http://localhost:{a.port} 로 접속해 먼저 만드세요.")
    shown = [str(n) for n in ALLOW if str(n) not in LOCAL_NETS and n.version == 4]
    print(f"  접속 허용   : {'제한 없음 (주의: 외부 접속 가능)' if not ALLOW else ('사내망 사설 IP 전체' if not a.allow else ', '.join(shown))}")
    odd = [ip for ip in ips if ALLOW and not allowed(ip)]
    if odd:
        print(f"  ※ 이 PC 주소({', '.join(odd)})가 허용 대역 밖입니다. 회사가 공인 IP를 사내망에 쓰는 경우이니")
        print(f"     --allow {odd[0].rsplit('.', 1)[0]}.  처럼 사내 대역을 지정하세요.")
    print(f"  공유 폴더   : {WATCH or '사용 안 함'}")
    print("  끝내려면 Ctrl+C")
    print("=" * 56, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


if __name__ == "__main__":
    main()
