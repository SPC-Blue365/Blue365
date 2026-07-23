"""운영 모니터 CLI [ML-Engineer].

실행: python scripts/monitor.py
최신 데이터로 라인별 예측·경보를 산출해 콘솔 요약 + outputs/monitor_status.html 생성.
(새 데이터가 data/raw/ 에 들어오면 다시 실행하면 됨 → '실시간' 갱신 패턴)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings

warnings.filterwarnings("ignore")

from config.paths import OUTPUTS_DIR, ensure_dirs
from src.models.dataset import all_lines
from src.monitoring import log_statuses, monitor_all
from src.monitoring.alerts import Level
from src.visualization import figures as V

BADGE = {Level.GREEN: ("#2ca02c", "🟢 정상"), Level.YELLOW: ("#f0a500", "🟡 주의"), Level.RED: ("#d62728", "🔴 경고")}


def main() -> None:
    ensure_dirs()
    lines = all_lines()
    statuses = monitor_all(lines)
    added = log_statuses(statuses)  # 경보 이력 누적

    print("=" * 60)
    print("운영 모니터 — 라인별 야드 CaO 상태")
    print("=" * 60)
    sections, cards = [], []
    for line, st in statuses.items():
        color, badge = BADGE[st.level]
        print(f"[{badge}] {line}→{st.alias}: 최신 CaO={st.latest_actual:.2f}% "
              f"(예측 {st.latest_pred:.2f}), 최근MAE={st.recent_mae:.2f}, 경보 {len(st.alerts)}건")
        for a in st.alerts:
            print(f"     - [{a.level.label}] {a.message}")

        # 차트
        s = st.series
        oos = ((s["pred"] < V.TARGET - 0.5) | (s["pred"] > V.TARGET + 0.5)).values
        fig = V.prediction_timeseries(s["datetime"], s["actual"].values, s["pred"].values, oos,
                                      f"{line} → {st.alias} · 최근 {st.n_monitored}h (MAE {st.recent_mae:.2f})")
        alert_html = "".join(
            f'<li><b style="color:{BADGE[a.level][0]}">[{a.level.label}]</b> {a.message}</li>'
            for a in st.alerts) or "<li>경보 없음</li>"
        card = (f'<div style="border-left:6px solid {color};padding:8px 14px;margin:10px 0;background:#fafafa">'
                f'<h3 style="margin:4px 0">{badge} · {line} 라인 → {st.alias}</h3>'
                f'<p>최신 CaO <b>{st.latest_actual:.2f}%</b> (예측 {st.latest_pred:.2f}) · 최근 MAE {st.recent_mae:.2f}</p>'
                f'<ul>{alert_html}</ul></div>')
        cards.append(card)
        sections.append(("", card))
        sections.append(("", fig))

    html = V.assemble_html("운영 모니터 — 야드 CaO 상태·경보", sections)
    out = OUTPUTS_DIR / "monitor_status.html"
    out.write_text(html, encoding="utf-8")
    print("=" * 60)
    print(f"[OK] 상태 리포트: {out}")


if __name__ == "__main__":
    main()
