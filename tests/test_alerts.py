"""경보 엔진 단위 테스트 (합성 시계열=검증 픽스처)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.monitoring.alerts import AlertConfig, Level, evaluate_alerts, overall_level


def _series(vals):
    idx = pd.date_range("2026-07-01", periods=len(vals), freq="1h")
    return pd.Series(vals, index=idx)


def test_in_spec_is_green():
    a = _series([44.6, 44.5, 44.7, 44.6])
    alerts = evaluate_alerts(a, a)
    assert overall_level(alerts) == Level.GREEN


def test_current_out_of_spec_red():
    a = _series([44.6, 44.6, 46.0])  # 마지막 이탈
    alerts = evaluate_alerts(a, a)
    assert any(al.kind == "spec" and al.level == Level.RED for al in alerts)


def test_sustained_violation_red():
    a = _series([46.0, 46.1, 46.2, 46.3])  # 4시간 연속 이탈
    alerts = evaluate_alerts(a, a, AlertConfig(sustain_hours=3))
    assert any(al.kind == "sustain" and al.level == Level.RED for al in alerts)


def test_model_deviation_warns():
    a = _series([44.6, 44.6, 44.6])
    p = _series([44.6, 44.6, 46.0])  # 예측이 실측과 크게 괴리
    alerts = evaluate_alerts(a, p, AlertConfig(deviation_warn=1.0))
    assert any(al.kind == "deviation" for al in alerts)


def test_trend_warns():
    a = _series([44.0, 44.4, 44.8, 45.2, 45.6, 46.0])  # 급상승
    alerts = evaluate_alerts(a, a, AlertConfig(trend_warn=0.3))
    assert any(al.kind == "trend" for al in alerts)
