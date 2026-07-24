"""대시보드 신규 기능 정적 미리보기 (Sankey·관리도·경보이력) [Synthesis-Agent].

실행: python scripts/make_dashboard_preview.py → outputs/dashboard_preview.html (로컬 전용)
실제 앱은 streamlit run streamlit_app.py.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np

from config import schema as S
from config.paths import OUTPUTS_DIR, ensure_dirs
from src.models.dataset import build_line_data, load_sources, load_yard_change
from src.monitoring import load_history, monitor_line
from src.monitoring.alerts import AlertConfig
from src.visualization import figures as V


def main() -> None:
    ensure_dirs()
    mine, osp_exp, yards = load_sources()
    lines = {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}
    cfg = AlertConfig()
    statuses = {ln: monitor_line(ld, cfg) for ln, ld in lines.items()}

    yc = load_yard_change()
    secs = [("", "<p>대시보드 신규 기능 미리보기. 실제 앱: "
                 "<code>streamlit run streamlit_app.py</code></p>")]
    if len(yc):
        secs.append(("★ 야드변경 기반 추적 Sankey (CaO/MgO 버튼 토글)",
                     V.build_yardchange_sankey(yc, default="CaO")))
        secs.append(("★ 변경일자별 CaO·MgO 추이", V.yardchange_trend(yc)))
    secs.append(("① 물류 개요 Sankey (광산→OSP→야드, 누적)", V.build_tracking_sankey(mine, osp_exp, yards)))
    for ln, stt in statuses.items():
        act = stt.series["actual"].values
        fin = act[np.isfinite(act)]
        insp = float(np.mean((fin >= cfg.lo) & (fin <= cfg.hi)) * 100) if len(fin) else 0.0
        secs.append((f"② 관리도 탭 — {ln}→{stt.alias} (규격내 {insp:.0f}%)",
                     V.control_chart(stt.series["datetime"], act, cfg.lo, cfg.hi, f"{ln} 관리도")))
    hist = load_history()
    secs.append(("③ 경보 이력 탭", V.alert_history_timeline(hist)))
    rows = "".join(f"<tr><td>{r.run_time}</td><td>{r.line}</td><td>{r.level}</td><td>{r.message}</td></tr>"
                   for r in hist.head(12).itertuples())
    secs.append(("", f"<table><tr><th>기록시각</th><th>라인</th><th>수준</th><th>내용</th></tr>{rows}</table>"))

    html = V.assemble_html("대시보드 신규 기능 미리보기 (Sankey·관리도·경보이력)", secs)
    out = OUTPUTS_DIR / "dashboard_preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out} ({out.stat().st_size // 1024} KB) · 이력행 {len(hist)}")


if __name__ == "__main__":
    main()
