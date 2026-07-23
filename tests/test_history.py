"""경보 이력 로그 테스트 (임시경로 픽스처)."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.monitoring.alerts import Alert, Level
from src.monitoring.history import load_history, log_statuses


@dataclass
class _FakeStatus:
    alias: str
    latest_time: str
    alerts: list = field(default_factory=list)


def _statuses():
    return {"신설": _FakeStatus("CNA", "2026-07-21 10:00",
            [Alert(Level.RED, "spec", "현재 CaO 46.0% 이탈")])}


def test_log_and_load(tmp_path):
    p = tmp_path / "alert_log.csv"
    added = log_statuses(_statuses(), path=p)
    assert added == 1
    h = load_history(p)
    assert len(h) == 1
    assert h.iloc[0]["level"] == "경고"


def test_dedup_no_duplicate(tmp_path):
    p = tmp_path / "alert_log.csv"
    log_statuses(_statuses(), path=p)
    added2 = log_statuses(_statuses(), path=p)  # 동일 경보 재기록
    assert added2 == 0
    assert len(load_history(p)) == 1
