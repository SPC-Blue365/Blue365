"""사내망 공유 주소·QR 코드 — 태블릿·휴대폰 접속 안내용(Streamlit에 의존하지 않는 부분).

QR 코드는 segno(순수 파이썬)가 있으면 만들고, 없으면 주소만 보여준다.
"""

from __future__ import annotations

import io
import socket

LOCAL_ONLY = {"127.0.0.1", "localhost", "::1"}      # 이 PC에서만 접속되는 실행 주소
ALL_INTERFACES = {"", "0.0.0.0", "::"}               # 모든 네트워크에서 접속을 받는 실행 주소
TABLET_QUERY = "/?view=tablet"                        # 태블릿 보기 자동 켜짐(QR 주소에 포함)


def lan_ipv4() -> list[str]:
    """이 PC의 사내망 IPv4 주소(루프백·자동 사설 주소 제외)."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # 기본 경로의 IP(실제 패킷은 보내지 않음)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.", "0.")))


def is_shared(address: str | None) -> bool:
    """실행 주소가 다른 PC·태블릿의 접속을 받는지(127.0.0.1·localhost 로 실행하면 이 PC 전용)."""
    return (address or "").strip().lower() not in LOCAL_ONLY


def share_urls(port: int, address: str | None = None, ips: list[str] | None = None,
               hostname: str | None = None) -> list[str]:
    """다른 기기에서 입력할 주소 목록 — IP 주소를 먼저, 컴퓨터 이름 주소를 마지막에."""
    if not is_shared(address):
        return []
    addr = (address or "").strip()
    if addr not in ALL_INTERFACES:                     # 특정 IP로만 실행한 경우
        return [f"http://{addr}:{port}"]
    ips = lan_ipv4() if ips is None else ips
    host = socket.gethostname() if hostname is None else hostname
    return [f"http://{ip}:{port}" for ip in ips] + ([f"http://{host}:{port}"] if host else [])


def qr_png(text: str, scale: int = 6) -> bytes | None:
    try:
        import segno
    except ImportError:
        return None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()
