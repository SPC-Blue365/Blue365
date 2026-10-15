"""MS SQL Server 보안 중계(TLS relay) — 서버와의 암호화(TLS)를 QMS(파이썬 ssl)가 직접 맡는다.

왜 필요한가
  pymssql(FreeTDS)이 서버와 TLS 를 맺지 못하면 로그인 전에 20002 'TDS server connection failed' 로 끊긴다.
  대표 원인: ① 서버(Windows Server 2022 이상)가 TLS 1.3 을 켜 둔 상태에서 TDS 7.x 접속(SQL Server 2022 는
  TLS 1.3 을 TDS 8.0 에서만 지원) ② 오래된 서버 인증서(1024비트·SHA1)·TLS 1.0 전용 서버 ③ 서버가 암호화를 강제.
  이 중계는 TLS 버전·암호 목록을 직접 정해(TLS 1.2 고정, 필요하면 오래된 방식 허용) 서버와 암호화 연결을 맺고,
  같은 PC 안(127.0.0.1)에서만 pymssql 과 이어 준다. 서버까지 가는 구간은 계속 암호화된다.

구조
  pymssql ──(127.0.0.1, 이 PC 안)──▶ 중계 ──(TLS 암호화)──▶ SQL Server
  · PRELOGIN 의 ENCRYPTION 값을 서버 쪽에는 '사용(ON)', pymssql 쪽에는 '지원 안 함'으로 바꿔 전달한다.
  · TLS 핸드셰이크는 TDS PRELOGIN(0x12) 패킷에 싸서 주고받고, 끝나면 TLS 레코드를 그대로 흘린다(TDS 7.x 규칙).
"""

from __future__ import annotations

import select
import socket
import ssl
import threading

PRELOGIN, RESPONSE = 0x12, 0x04
ENC_OFF, ENC_ON, ENC_NOT_SUP, ENC_REQ = 0x00, 0x01, 0x02, 0x03

PROFILES = {
    "tls12": "TLS 1.2 고정",
    "legacy": "TLS 1.0~1.2 · 오래된 인증서 허용",
}
_TLS_ERR = {
    "unsupported protocol": "서버와 맞는 TLS 버전이 없습니다",
    "wrong version number": "TLS 버전이 맞지 않습니다",
    "ee key too small": "서버 인증서 키가 너무 짧습니다(1024비트 이하)",
    "dh key too small": "서버 암호 키(DH)가 너무 짧습니다",
    "ca md too weak": "서버 인증서 서명 방식이 오래됐습니다(SHA1·MD5)",
    "no ciphers available": "서버와 맞는 암호 방식이 없습니다",
    "handshake failure": "서버가 TLS 협상을 거절했습니다",
    "unsafe legacy renegotiation": "서버가 오래된 재협상 방식을 씁니다",
}


def tls_context(profile: str = "tls12") -> ssl.SSLContext:
    """서버 인증서는 검증하지 않는다(사내 자체 서명 인증서 — pyodbc 의 TrustServerCertificate=yes 와 같은 수준)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2          # TDS 7.x 는 TLS 1.3 을 쓰지 않는다
    if profile == "legacy":
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("ALL:@SECLEVEL=0")
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    else:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def explain_tls(msg: str) -> str:
    low = (msg or "").lower()
    return next((v for k, v in _TLS_ERR.items() if k in low), "")


# ── TDS 패킷 ────────────────────────────────────────────────────────────
def _recv_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise EOFError("상대가 연결을 끊었습니다")
        buf += c
    return buf


def read_packet(s: socket.socket) -> tuple[bytes, bytes]:
    head = _recv_exact(s, 8)
    n = int.from_bytes(head[2:4], "big")
    if n < 8:
        raise ValueError("TDS 패킷 길이 오류")
    return head, _recv_exact(s, n - 8)


def read_message(s: socket.socket) -> tuple[int, bytes]:
    """EOM(상태 0x01) 까지 이어 읽는다 → (패킷 종류, 내용)."""
    kind, body = None, b""
    while True:
        head, b = read_packet(s)
        kind = head[0] if kind is None else kind
        body += b
        if head[1] & 0x01:
            return kind, body


def packets(kind: int, data: bytes, size: int = 4096) -> bytes:
    out, step = b"", size - 8
    chunks = [data[i:i + step] for i in range(0, len(data), step)] or [b""]
    for i, ch in enumerate(chunks):
        n = 8 + len(ch)
        out += bytes([kind, 0x01 if i == len(chunks) - 1 else 0x00, n >> 8, n & 0xFF, 0, 0, i + 1 & 0xFF, 0]) + ch
    return out


def _enc_offset(body: bytes) -> int | None:
    i = 0
    while i + 5 <= len(body) and body[i] != 0xFF:
        tok, off, ln = body[i], int.from_bytes(body[i + 1:i + 3], "big"), int.from_bytes(body[i + 3:i + 5], "big")
        if tok == 0x01 and ln >= 1 and off < len(body):
            return off
        i += 5
    return None


def get_enc(body: bytes) -> int | None:
    off = _enc_offset(body)
    return body[off] if off is not None else None


def set_enc(body: bytes, value: int) -> bytes:
    off = _enc_offset(body)
    return body if off is None else body[:off] + bytes([value]) + body[off + 1:]


def prelogin_body(enc: int = ENC_ON) -> bytes:
    opts = bytes([0x00, 0x00, 0x0B, 0x00, 0x06, 0x01, 0x00, 0x11, 0x00, 0x01, 0xFF])
    return opts + bytes([0x10, 0x00, 0x00, 0x00, 0x00, 0x00]) + bytes([enc])


def tls_handshake(srv: socket.socket, ctx: ssl.SSLContext) -> tuple[ssl.SSLObject, ssl.MemoryBIO, ssl.MemoryBIO]:
    """PRELOGIN 응답을 받은 직후의 서버 소켓에서 TDS 방식(0x12 패킷에 싸기)으로 TLS 를 맺는다."""
    inc, out = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = ctx.wrap_bio(inc, out, server_side=False)
    while True:
        try:
            tls.do_handshake()
            break
        except ssl.SSLWantReadError:
            d = out.read()
            if d:
                srv.sendall(packets(PRELOGIN, d))
            _, body = read_message(srv)
            inc.write(body)
    d = out.read()                                     # 마지막 Finished 등 남은 것
    if d:
        srv.sendall(packets(PRELOGIN, d))
    return tls, inc, out


def _pump_tls(cli: socket.socket, srv: socket.socket, tls: ssl.SSLObject, inc: ssl.MemoryBIO, out: ssl.MemoryBIO,
              login_only: bool = False) -> None:
    def flush():
        d = out.read()
        if d:
            srv.sendall(d)

    first_done = False
    while True:
        r, _, _ = select.select([cli, srv], [], [], 3600)
        if not r:
            return
        if cli in r:
            d = cli.recv(65536)
            if not d:
                return
            if login_only and first_done:
                srv.sendall(d)
            else:
                tls.write(d)
                flush()
                first_done = True
        if srv in r:
            d = srv.recv(65536)
            if not d:
                return
            if login_only and first_done:
                cli.sendall(d)
                continue
            inc.write(d)
            while True:
                try:
                    plain = tls.read(65536)
                except ssl.SSLWantReadError:
                    break
                except ssl.SSLZeroReturnError:
                    return
                if not plain:
                    break
                cli.sendall(plain)
            flush()


def _pump_plain(a: socket.socket, b: socket.socket) -> None:
    while True:
        r, _, _ = select.select([a, b], [], [], 3600)
        if not r:
            return
        for s in r:
            d = s.recv(65536)
            if not d:
                return
            (b if s is a else a).sendall(d)


class Relay:
    """127.0.0.1 의 빈 포트에서 기다리다가, 들어온 접속마다 서버와 TLS 를 맺어 이어 준다."""

    def __init__(self, host: str, port: int, profile: str = "tls12", timeout: float = 15.0):
        self.host, self.port_remote, self.profile, self.timeout = host, int(port), profile, timeout
        self.ctx = tls_context(profile)
        self.last_error = ""
        self.last_tls = ""                             # 마지막으로 맺은 TLS 버전·암호(진단용)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True, name=f"tds-relay-{self.port}").start()

    def _accept(self) -> None:
        while True:
            try:
                cli, addr = self.sock.accept()
            except OSError:
                return
            if addr[0] != "127.0.0.1":                 # 이 PC 안에서 온 접속만
                cli.close()
                continue
            threading.Thread(target=self._serve, args=(cli,), daemon=True).start()

    def _serve(self, cli: socket.socket) -> None:
        srv = None
        try:
            cli.settimeout(self.timeout)
            srv = socket.create_connection((self.host, self.port_remote), timeout=self.timeout)
            kind, body = read_message(cli)
            if kind != PRELOGIN:                       # TDS 7.0 등 PRELOGIN 없는 방식 → 그대로(암호화 없음)
                srv.sendall(packets(kind, body))
                cli.settimeout(None), srv.settimeout(None)
                _pump_plain(cli, srv)
                return
            srv.sendall(packets(PRELOGIN, set_enc(body, ENC_ON)))
            rkind, rbody = read_message(srv)
            senc = get_enc(rbody)
            cli.sendall(packets(rkind, set_enc(rbody, ENC_NOT_SUP)))
            if senc == ENC_NOT_SUP:                    # 서버가 암호화를 지원하지 않음 → 그대로 이어 줌
                cli.settimeout(None), srv.settimeout(None)
                _pump_plain(cli, srv)
                return
            try:
                tls, inc, out = tls_handshake(srv, self.ctx)
            except (ssl.SSLError, EOFError, OSError) as exc:
                why = explain_tls(str(exc))
                self.last_error = f"TLS 연결 실패({PROFILES.get(self.profile, self.profile)}): " + (why + " · " if why else "") + str(exc)[:200]
                return
            self.last_tls = f"{tls.version()} · {(tls.cipher() or ('',))[0]}"
            self.last_error = ""
            cli.settimeout(None), srv.settimeout(None)
            _pump_tls(cli, srv, tls, inc, out, login_only=(senc == ENC_OFF))
        except Exception as exc:  # noqa: BLE001 - 중계 오류는 진단 메시지로만 남긴다
            if not self.last_error:
                self.last_error = f"중계 오류: {type(exc).__name__}: {str(exc)[:200]}"
        finally:
            for s in (cli, srv):
                try:
                    if s:
                        s.close()
                except OSError:
                    pass

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


_RELAYS: dict[tuple, Relay] = {}
_LOCK = threading.Lock()


def get_relay(host: str, port: int, profile: str = "tls12") -> Relay:
    """같은 서버·방식이면 이미 띄운 중계를 다시 쓴다(앱이 켜져 있는 동안 유지)."""
    key = (host, int(port), profile)
    with _LOCK:
        r = _RELAYS.get(key)
        if r is None:
            r = _RELAYS[key] = Relay(host, port, profile)
        return r


# ── 진단: 서버가 받아 주는 TLS 버전·인증서 ───────────────────────────────────
_SIG_OIDS = {"1.2.840.113549.1.1.4": "MD5-RSA", "1.2.840.113549.1.1.5": "SHA1-RSA", "1.2.840.113549.1.1.11": "SHA256-RSA",
             "1.2.840.113549.1.1.12": "SHA384-RSA", "1.2.840.113549.1.1.13": "SHA512-RSA",
             "1.2.840.10045.4.3.2": "ECDSA-SHA256", "1.2.840.10045.4.3.3": "ECDSA-SHA384", "1.2.840.10045.4.1": "ECDSA-SHA1"}


def _tlv(b: bytes, i: int) -> tuple[int, int, int]:
    """DER 하나 → (태그, 값 시작, 값 끝)."""
    tag, ln = b[i], b[i + 1]
    i += 2
    if ln & 0x80:
        k = ln & 0x7F
        ln = int.from_bytes(b[i:i + k], "big")
        i += k
    return tag, i, i + ln


def _children(b: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    out, i = [], start
    while i < end:
        t, s, e = _tlv(b, i)
        out.append((t, s, e))
        i = e
    return out


def _oid(b: bytes) -> str:
    vals, v = [b[0] // 40, b[0] % 40], 0
    for x in b[1:]:
        v = (v << 7) | (x & 0x7F)
        if not x & 0x80:
            vals.append(v)
            v = 0
    return ".".join(map(str, vals))


def cert_info(der: bytes) -> dict:
    """서버 인증서의 서명 방식·키 길이·이름·만료일(검증용 아님, 안내용)."""
    info: dict = {}
    try:
        _, s, e = _tlv(der, 0)
        tbs, sigalg, _ = _children(der, s, e)[:3]
        info["서명 방식"] = _SIG_OIDS.get(_oid(der[_tlv(der, sigalg[1])[1]:_tlv(der, sigalg[1])[2]]), "기타")
        parts = _children(der, tbs[1], tbs[2])
        if parts and parts[0][0] == 0xA0:              # version [0]
            parts = parts[1:]
        spki = parts[5]
        alg, bits = _children(der, spki[1], spki[2])[:2]
        alg_oid = _oid(der[_tlv(der, alg[1])[1]:_tlv(der, alg[1])[2]])
        if alg_oid == "1.2.840.113549.1.1.1":
            rsa = der[bits[1] + 1:bits[2]]
            _, rs, re_ = _tlv(rsa, 0)
            mod = _children(rsa, rs, re_)[0]
            info["키"] = f"RSA {int.from_bytes(rsa[mod[1]:mod[2]], 'big').bit_length()}비트"
        else:
            info["키"] = "EC"
    except Exception:  # noqa: BLE001
        pass
    try:
        import os
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".pem")
        with os.fdopen(fd, "w") as f:
            f.write(ssl.DER_cert_to_PEM_cert(der))
        d = ssl._ssl._test_decode_cert(p)                  # 표준 라이브러리의 인증서 해석기
        os.unlink(p)
        cn = dict(x[0] for x in d.get("subject", ()) if x)
        info["이름(CN)"] = cn.get("commonName", "")
        info["만료"] = d.get("notAfter", "")
    except Exception:  # noqa: BLE001
        pass
    return info


def probe_tls(host: str, port: int, timeout: float = 8.0) -> dict:
    """PRELOGIN 으로 서버 암호화 설정을 묻고, TLS 버전별로 핸드셰이크만 시험(로그인 안 함)."""
    res: dict = {"encryption": None, "versions": [], "cert": {}}
    names = {ENC_OFF: "로그인만 암호화", ENC_ON: "사용", ENC_NOT_SUP: "지원 안 함", ENC_REQ: "필수(서버가 강제)"}
    import warnings
    vers = [("TLS 1.3", ssl.TLSVersion.TLSv1_3), ("TLS 1.2", ssl.TLSVersion.TLSv1_2), ("TLS 1.1", ssl.TLSVersion.TLSv1_1),
            ("TLS 1.0", ssl.TLSVersion.TLSv1)]
    for label, v in vers:
        try:
            with socket.create_connection((host, int(port)), timeout=timeout) as s:
                s.settimeout(timeout)
                s.sendall(packets(PRELOGIN, prelogin_body(ENC_ON)))
                _, body = read_message(s)
                enc = get_enc(body)
                res["encryption"] = names.get(enc, str(enc))
                if enc == ENC_NOT_SUP:
                    res["versions"].append((label, False, "서버가 암호화를 지원하지 않음"))
                    break
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    ctx.minimum_version = ctx.maximum_version = v
                ctx.set_ciphers("ALL:@SECLEVEL=0")
                ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
                tls, _, _ = tls_handshake(s, ctx)
                res["versions"].append((label, True, (tls.cipher() or ("",))[0]))
                if not res["cert"]:
                    der = tls.getpeercert(binary_form=True)
                    if der:
                        res["cert"] = cert_info(der)
        except (ssl.SSLError, EOFError, OSError, ValueError) as exc:
            why = explain_tls(str(exc))
            res["versions"].append((label, False, (why + " · " if why else "") + f"{type(exc).__name__}: {str(exc)[:140]}"))
    return res
