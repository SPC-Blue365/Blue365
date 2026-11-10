#!/usr/bin/env python3
"""Blue365 시멘트 공정 3D — 사내망 팀 공유 서버

파이썬 표준 라이브러리만 사용합니다(추가 설치 없음, 인터넷 불필요).

  python server.py                         → http://<이 PC 이름>:8365 로 팀원 접속
  python server.py --watch "\\\\서버\\품질\\업로드"   → 공유 폴더의 최신 .xlsx 자동 반영
  python server.py --key 비밀번호            → 업로드할 때 비밀번호 요구

하는 일
  GET  /                 화면(cement_plant_3d.html)
  GET  /업로드양식.xlsx    업로드 양식
  GET  /api/status       서버 상태와 최신 데이터 버전
  GET  /api/dataset      최신 데이터(JSON)
  POST /api/dataset      화면에서 올린 데이터 저장 → 모든 접속자에게 20초 안에 반영
  저장 위치: data/latest.json, 이력은 data/history/ (최근 200개 보관)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hmac
import io
import json
import os
import socket
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
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
class Handler(BaseHTTPRequestHandler):
    server_version = "Blue365/1.0"

    def log_message(self, fmt, *args):  # 접속 기록은 요약해서
        if not self.path.startswith("/api/status"):
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
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html", "/cement_plant_3d.html"):
            if not PAGE.exists():
                return self._send(500, {"error": "cement_plant_3d.html이 없습니다. build.py를 먼저 실행하세요."})
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path in ("/업로드양식.xlsx", "/template.xlsx"):
            if not TEMPLATE.exists():
                return self._send(404, {"error": "업로드양식.xlsx가 없습니다"})
            return self._send(200, TEMPLATE.read_bytes(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": "attachment; filename*=UTF-8''" + quote("업로드양식.xlsx")})
        if path == "/api/status":
            m = STORE.meta or {}
            return self._send(200, {"app": "blue365", "version": m.get("version"), "meta": STORE.meta,
                                    "needKey": bool(KEY), "watch": bool(WATCH)})
        if path == "/api/dataset":
            b = STORE.read()
            return self._send(200, b) if b else self._send(404, {"error": "아직 올라온 데이터가 없습니다"})
        self._send(404, {"error": "없는 주소입니다"})

    def do_POST(self):
        if unquote(urlparse(self.path).path) != "/api/dataset":
            return self._send(404, {"error": "없는 주소입니다"})
        if KEY and not hmac.compare_digest(self.headers.get("X-Upload-Key", "").encode(), KEY.encode()):
            return self._send(401, {"error": "업로드 비밀번호가 맞지 않습니다"})
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
            if body.get("qms") is not None:
                meta = STORE.save(body.get("qms"), body.get("meta") or {}, "qms")
            else:
                meta = STORE.save(body.get("sheets"), body.get("meta") or {}, "sheets")
        except (ValueError, UnicodeDecodeError, AttributeError) as e:
            return self._send(400, {"error": f"데이터 형식 오류: {e}"})
        log(f"업로드 저장: {meta['fileName']} · {meta['uploadedBy']} (버전 {meta['version']})")
        self._send(200, {"ok": True, "meta": meta})


def main() -> None:
    global STORE, KEY, WATCH
    ap = argparse.ArgumentParser(description="Blue365 시멘트 공정 3D 팀 공유 서버")
    ap.add_argument("--host", default="0.0.0.0", help="받을 주소 (기본: 모든 네트워크)")
    ap.add_argument("--port", type=int, default=8365, help="포트 (기본 8365)")
    ap.add_argument("--data", default=str(ROOT / "data"), help="데이터 저장 폴더")
    ap.add_argument("--watch", help="최신 .xlsx를 자동으로 읽을 공유 폴더")
    ap.add_argument("--interval", type=int, default=60, help="공유 폴더 확인 주기(초, 기본 60)")
    ap.add_argument("--key", default=os.environ.get("B365_UPLOAD_KEY", ""), help="업로드 비밀번호(영문·숫자)")
    a = ap.parse_args()

    if not PAGE.exists():
        sys.exit("cement_plant_3d.html이 없습니다. 같은 폴더에서 python build.py를 먼저 실행하세요.")
    STORE = Store(Path(a.data))
    KEY = a.key
    if a.watch:
        folder = Path(a.watch)
        if not folder.is_dir():
            sys.exit(f"공유 폴더를 찾을 수 없습니다: {folder}")
        WATCH = str(folder)
        threading.Thread(target=watch_loop, args=(folder, max(10, a.interval)), daemon=True).start()

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    host = socket.gethostname()
    print("=" * 56)
    print(" Blue365 시멘트 공정 3D · 팀 공유 서버")
    print(f"  이 PC에서   : http://localhost:{a.port}")
    print(f"  팀원 접속   : http://{host}:{a.port}")
    print(f"  데이터 저장 : {STORE.dir}")
    print(f"  업로드 암호 : {'사용' if KEY else '사용 안 함'}")
    print(f"  공유 폴더   : {WATCH or '사용 안 함'}")
    print("  끝내려면 Ctrl+C")
    print("=" * 56, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


if __name__ == "__main__":
    main()
