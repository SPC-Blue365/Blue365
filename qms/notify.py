"""알림 발송: 이메일(SMTP) · 웹훅(Slack / Microsoft Teams / 일반 JSON).

설정 위치
  - data/notify.json            : 수신자·심각도 기준 등 일반 설정(화면에서 저장)
  - .streamlit/secrets.toml [notify] 또는 환경변수 : 비밀번호·웹훅 URL 등 비밀값
      QMS_SMTP_PASSWORD, QMS_WEBHOOK_URL
  비밀값은 저장소(git)에 올리지 않는다(.gitignore 처리).

중복 발송 방지: 발송한 이벤트는 alert_status.notified = 1 로 기록한다.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.request
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from .alerts import SEVERITY_ICON, SEVERITY_ORDER, AlertEvent
from .standards import DATA_DIR

NOTIFY_PATH = DATA_DIR / "notify.json"
SECRETS_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"


@dataclass
class NotifyConfig:
    min_severity: str = "경고"
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_format: str = "slack"   # slack | teams | generic
    dashboard_url: str = ""

    def public_dict(self) -> dict:
        d = asdict(self)
        d.pop("smtp_password", None)
        d.pop("webhook_url", None)
        return d


def _read_secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    try:
        import tomllib
        return tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8")).get("notify", {})
    except Exception:  # noqa: BLE001 - 비밀 설정 파싱 실패는 무시하고 기본값 사용
        return {}


def load_config(path: Path = NOTIFY_PATH) -> NotifyConfig:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    secrets = _read_secrets()
    cfg = NotifyConfig(**{k: v for k, v in data.items() if k in NotifyConfig.__dataclass_fields__})
    cfg.smtp_password = os.environ.get("QMS_SMTP_PASSWORD", secrets.get("smtp_password", cfg.smtp_password))
    cfg.webhook_url = os.environ.get("QMS_WEBHOOK_URL", secrets.get("webhook_url", cfg.webhook_url))
    return cfg


def save_config(cfg: NotifyConfig, path: Path = NOTIFY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.public_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def format_message(event: AlertEvent, summary: str = "", actions: list[str] | None = None,
                   dashboard_url: str = "") -> tuple[str, str]:
    """(제목, 본문). 본문은 메일·메신저 공용 일반 텍스트."""
    prod = f"[{event.product}] " if event.product else ""
    subject = f"[QMS {event.severity}] {prod}{event.item_name} — {event.rule_desc}"
    lines = [f"{SEVERITY_ICON[event.severity]} {subject}", "", event.message]
    if event.patterns:
        lines.append(f"동반 SPC 패턴: {', '.join(event.patterns)}")
    if summary:
        lines += ["", "■ 자동 진단(요약)", summary]
    if actions:
        lines += ["", "■ 권장 단기 조치"] + [f" - {a}" for a in actions[:4]]
    if dashboard_url:
        lines += ["", f"대시보드: {dashboard_url}"]
    lines += ["", "※ 자동 진단은 데이터 기반 1차 판단입니다. 현장 확인 후 조치하십시오."]
    return subject, "\n".join(lines)


def send_email(cfg: NotifyConfig, subject: str, body: str) -> tuple[bool, str]:
    if not (cfg.smtp_host and cfg.recipients and (cfg.sender or cfg.smtp_user)):
        return False, "SMTP 서버·발신자·수신자 설정이 필요합니다."
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender or cfg.smtp_user
    msg["To"] = ", ".join(cfg.recipients)
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg.smtp_host, int(cfg.smtp_port), timeout=15) as server:
            if cfg.smtp_tls:
                server.starttls(context=ssl.create_default_context())
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
        return True, f"메일 발송 완료 ({len(cfg.recipients)}명)"
    except Exception as exc:  # noqa: BLE001 - 원인 메시지를 화면에 표시
        return False, f"메일 발송 실패: {exc}"


def send_webhook(cfg: NotifyConfig, subject: str, body: str) -> tuple[bool, str]:
    if not cfg.webhook_url:
        return False, "웹훅 URL 설정이 필요합니다."
    if cfg.webhook_format == "teams":
        payload = {"@type": "MessageCard", "@context": "http://schema.org/extensions", "summary": subject,
                   "title": subject, "text": body.replace("\n", "<br>")}
    elif cfg.webhook_format == "generic":
        payload = {"title": subject, "text": body}
    else:
        payload = {"text": body}
    req = urllib.request.Request(cfg.webhook_url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - 사용자가 설정한 URL
            return 200 <= resp.status < 300, f"웹훅 응답 {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"웹훅 발송 실패: {exc}"


def should_notify(event: AlertEvent, cfg: NotifyConfig) -> bool:
    return SEVERITY_ORDER[event.severity] >= SEVERITY_ORDER.get(cfg.min_severity, 2)


def dispatch(events: list[AlertEvent], status: pd.DataFrame, cfg: NotifyConfig, diagnose_fn=None,
             since: pd.Timestamp | None = None, dry_run: bool = False) -> list[dict]:
    """미발송 이벤트를 발송한다. 반환: 발송 결과 목록. 발송 상태 기록은 호출 측에서 처리."""
    notified = set(status.loc[status.get("notified", pd.Series(dtype=int)) == 1, "event_id"]) if len(status) else set()
    results = []
    for e in events:
        if e.event_id in notified or not should_notify(e, cfg):
            continue
        if since is not None and e.end < since:
            continue
        summary, actions = "", []
        if diagnose_fn is not None:
            try:
                dx = diagnose_fn(e)
                summary, actions = dx.summary, [a for a, _ in dx.short_term]
            except Exception as exc:  # noqa: BLE001 - 진단 실패해도 알림은 발송
                summary = f"(자동 진단 실패: {exc})"
        subject, body = format_message(e, summary, actions, cfg.dashboard_url)
        outcome = {"event_id": e.event_id, "subject": subject, "body": body, "channels": []}
        if not dry_run:
            if cfg.email_enabled:
                outcome["channels"].append(("email",) + send_email(cfg, subject, body))
            if cfg.webhook_enabled:
                outcome["channels"].append(("webhook",) + send_webhook(cfg, subject, body))
        outcome["sent"] = any(ok for _, ok, _ in outcome["channels"])
        results.append(outcome)
    return results
