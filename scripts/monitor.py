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
from src.models.roadmap import readiness, summary_text
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
        icon, label = st.badge
        color = "#8a6d1a" if st.is_stale else BADGE[st.level][0]
        badge = f"{icon} {label}"
        print(f"[{badge}] {line}→{st.alias}: 최신 CaO={st.latest_actual:.2f}% "
              f"(예측 {st.latest_pred:.2f}), 최근MAE={st.recent_mae:.2f}, 경보 {len(st.alerts)}건")
        print(f"     📅 기준 {st.as_of} ({st.age_text})" + (f" · ⏸️ {st.note}" if st.note else ""))
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
                f'<p>📅 기준 {st.as_of} ({st.age_text})' + (f' · ⏸️ {st.note}' if st.note else '') + '</p>'
                f'<p>최신 CaO <b>{st.latest_actual:.2f}%</b> (예측 {st.latest_pred:.2f}) · 최근 MAE {st.recent_mae:.2f}</p>'
                f'<ul>{alert_html}</ul></div>')
        cards.append(card)
        sections.append(("", card))
        sections.append(("", fig))

    # ⭐️ 배합 최적화 착수 조건 알람 (사용자 요청) — 데이터 갱신 때마다 자동 판정
    from src.models.dataset import load_sources, load_yard_change
    try:
        _mine, _, _ = load_sources(validate=False, verbose=False)
        ready = print_roadmap_alarm(_mine, load_yard_change())
    except Exception as exc:                     # 알람 실패가 모니터를 막지 않게
        print(f"[로드맵] 준비도 계산 실패: {exc}")
        ready = False

    html = V.assemble_html("운영 모니터 — 야드 CaO 상태·경보", sections)
    out = OUTPUTS_DIR / "monitor_status.html"
    out.write_text(html, encoding="utf-8")
    print("=" * 60)
    print(f"[OK] 상태 리포트: {out}")



def print_roadmap_alarm(mine, yc) -> bool:
    """배합 최적화 착수 조건이 충족되면 **눈에 띄게 알린다** (사용자 요청 알람).

    세션은 매번 새로 시작하므로 상시 감시는 불가능하다. 대신 데이터를 갱신해
    이 스크립트(또는 run_all)를 돌릴 때마다 자동 판정해 알린다.
    """
    r = readiness(mine, yc)
    line = "=" * 60
    if r["ready"]:
        print(f"\n{line}\n🎉🎉  배합 최적화 착수 조건 충족  🎉🎉\n{line}")
        print(summary_text(r))
        print("→ 다음 행동: scripts/run_all.py 재실행 후 '섞기 계획' 탭 확인,")
        print("             구역별 배합 처방을 현장 검증 단계로 올릴 것.")
        print(line)
    else:
        c = r["cases"]
        print(f"\n[로드맵] 배합 최적화 준비도 — 검증 사례 {c['have']}/{c['need']}건"
              f" ({c['have']/max(c['need'],1)*100:.0f}%)"
              f" · 남은 기간 약 {c['months']:.1f}개월")
        print(f"         {summary_text(r)}")
    return bool(r["ready"])


if __name__ == "__main__":
    main()
