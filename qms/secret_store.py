"""비밀값(LIMS DB 비밀번호·API 토큰) 암호화 저장소 — data/secrets.enc.json.

Windows : DPAPI(CryptProtectData, 현재 사용자 범위) — **이 PC의 이 Windows 계정**에서만 풀 수 있다.
          파일을 다른 PC·계정으로 복사하거나 백업에서 되살리면 풀리지 않으므로 비밀번호를 다시 입력한다.
그 외   : Fernet(AES-128-CBC + HMAC-SHA256, cryptography 패키지) — 키는 data/.secret.key(소유자만 읽기)에 따로 둔다.
화면·설정 파일(lims.json)·로그에는 비밀값을 쓰지 않는다. 저장된 값은 다시 화면에 보여주지 않는다(바꾸기·지우기만 가능).
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .standards import DATA_DIR

STORE_PATH = DATA_DIR / "secrets.enc.json"
KEY_PATH = DATA_DIR / ".secret.key"
IS_WIN = sys.platform == "win32"
_ENTROPY = b"Blue365-QMS/secret-store/v1"


# ── Windows DPAPI ───────────────────────────────────────────────────────
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src, _keep = _blob(data)
    ent, _keep2 = _blob(_ENTROPY)
    out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = ((ctypes.byref(src), "Blue365 QMS", ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)) if protect else
            (ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)))   # 0x1 = UI 표시 안 함
    if not fn(*args):
        raise OSError(f"DPAPI {'암호화' if protect else '복호화'} 실패(오류 {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


# ── Fernet(Windows 외) ──────────────────────────────────────────────────
def _fernet():
    from cryptography.fernet import Fernet

    if KEY_PATH.exists():
        key = KEY_PATH.read_bytes().strip()
    else:
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    return Fernet(key)


def method() -> str:
    return "dpapi" if IS_WIN else "fernet"


def method_label(m: str | None = None) -> str:
    return {"dpapi": "Windows 계정 암호화(DPAPI) — 이 PC의 이 계정에서만 풀림",
            "fernet": "암호화(Fernet) — 키 파일 data/.secret.key 를 따로 보관"}.get(m or method(), m or "")


def _encrypt(value: str) -> tuple[str, str]:
    raw = value.encode("utf-8")
    if IS_WIN:
        return "dpapi", base64.b64encode(_dpapi(raw, True)).decode()
    return "fernet", _fernet().encrypt(raw).decode()


def _decrypt(m: str, v: str) -> str:
    if m == "dpapi":
        if not IS_WIN:
            raise OSError("Windows에서 암호화한 값입니다.")
        return _dpapi(base64.b64decode(v), False).decode("utf-8")
    if m == "fernet":
        return _fernet().decrypt(v.encode()).decode("utf-8")
    raise ValueError(f"알 수 없는 암호화 방식: {m}")


# ── 저장소 ───────────────────────────────────────────────────────────────
def _load(path: Path | None = None) -> dict:
    path = path or STORE_PATH
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        d = {}
    return d if isinstance(d, dict) else {}


def _save(d: dict, path: Path | None = None) -> None:
    path = path or STORE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    if not IS_WIN:
        os.chmod(path, 0o600)


def set_secret(name: str, value: str, path: Path | None = None) -> None:
    if not value:
        raise ValueError("빈 값은 저장하지 않습니다.")
    m, v = _encrypt(value)
    d = _load(path)
    d[name] = {"m": m, "v": v, "at": f"{datetime.now():%Y-%m-%d %H:%M}"}
    _save(d, path)


def get_secret(name: str, path: Path | None = None) -> str:
    e = _load(path).get(name)
    if not isinstance(e, dict):
        return ""
    try:
        return _decrypt(e.get("m", ""), e.get("v", ""))
    except Exception:  # noqa: BLE001 - 다른 PC·계정에서 복사된 값 등은 풀 수 없음 → 없는 것으로 처리
        return ""


def delete_secret(name: str, path: Path | None = None) -> None:
    d = _load(path)
    if d.pop(name, None) is not None:
        _save(d, path)


def status(name: str, path: Path | None = None) -> dict:
    """{'saved': 저장 여부, 'usable': 이 PC·계정에서 풀리는지, 'method': 방식, 'at': 저장 일시} — 값 자체는 돌려주지 않음."""
    e = _load(path).get(name)
    if not isinstance(e, dict):
        return {"saved": False, "usable": False, "method": "", "at": ""}
    return {"saved": True, "usable": bool(get_secret(name, path)), "method": e.get("m", ""), "at": e.get("at", "")}
