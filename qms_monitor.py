"""무인 감시 스크립트: 데이터 자동 반영 → 이상 감지 → 알림 발송.

사용 예 (10~30분 주기로 cron / Windows 작업 스케줄러에 등록)
  python qms_monitor.py --since-hours 24
  python qms_monitor.py --import-dir ./inbox --since-hours 24
  python qms_monitor.py --dry-run          # 발송하지 않고 대상만 출력
  python qms_monitor.py --sync-lims        # LIMS 결과 증분 동기화 후 감시(🔗 LIMS 연동 화면에서 설정)

--import-dir: LIMS·DCS가 내보낸 엑셀/CSV를 넣어두는 폴더. 처리한 파일은 processed/ 로 옮긴다.
--sync-lims : data/lims.json 설정(SQL·REST·파일)으로 승인된 시험 결과를 가져와 열 단위로 병합 저장한다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

from qms.alerts import detect_events
from qms.diagnosis import diagnose
from qms.lims import load_lims_config, sync
from qms.notify import dispatch, load_config
from qms.prediction import attach_predictions
from qms.standards import load_registry, load_settings
from qms.store import (
    load_alert_status,
    load_store,
    parse_upload,
    save_raw,
    update_alert_status,
)


def import_folder(folder: Path) -> list[str]:
    logs = []
    done = folder / "processed"
    done.mkdir(parents=True, exist_ok=True)
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in (".xlsx", ".xls", ".csv") or not f.is_file():
            continue
        res = parse_upload(f.read_bytes(), f.name)
        if res.errors:
            logs.append(f"[오류] {f.name}: {'; '.join(res.errors)}")
            continue
        counts = save_raw(res.tables, replace=False)
        shutil.move(str(f), done / f.name)
        logs.append(f"[반영] {f.name}: " + ", ".join(f"{k} {v}행" for k, v in counts.items()))
    return logs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Blue365 QMS 무인 감시")
    ap.add_argument("--import-dir", type=Path, help="자동 반영할 데이터 파일 폴더")
    ap.add_argument("--since-hours", type=float, default=24, help="최근 N시간 내 종료된 이벤트만 발송(기본 24)")
    ap.add_argument("--dry-run", action="store_true", help="발송하지 않고 대상만 출력")
    ap.add_argument("--sync-lims", action="store_true", help="LIMS 결과 증분 동기화 후 감시")
    args = ap.parse_args(argv)

    if args.sync_lims:
        cfg = load_lims_config()
        if not cfg.enabled:
            print("[LIMS] 연동이 꺼져 있습니다(🔗 LIMS 연동 화면에서 사용 설정).")
        else:
            rep = sync(cfg, dry_run=args.dry_run)
            print(f"[LIMS] {rep.summary_text()}")
            for code in rep.unmapped[:10]:
                print(f"    미매핑 시험코드: {code[0]}/{code[1]} {code[2]}건")

    if args.import_dir:
        for line in import_folder(args.import_dir):
            print(line)

    store = load_store()
    if store.is_empty():
        print("데이터가 없습니다.")
        return 0
    registry, settings = load_registry(), load_settings()
    attach_predictions(store, registry)
    events = detect_events(store, registry, settings)
    period = store.period()
    since = period[1] - pd.Timedelta(hours=args.since_hours)
    cfg = load_config()
    results = dispatch(events, load_alert_status(), cfg, diagnose_fn=lambda e: diagnose(e, store, registry, settings),
                       since=since, dry_run=args.dry_run)
    print(f"이벤트 {len(events)}건 중 발송 대상 {len(results)}건 (기준 {cfg.min_severity} 이상, {since:%Y-%m-%d %H:%M} 이후)")
    for r in results:
        print("-", r["subject"])
        for ch, ok, msg in r["channels"]:
            print(f"    {ch}: {'성공' if ok else '실패'} — {msg}")
        if r["sent"]:
            update_alert_status(r["event_id"], notified=1)
    if not args.dry_run and results and not (cfg.email_enabled or cfg.webhook_enabled):
        print("※ 이메일·웹훅이 모두 꺼져 있어 실제 발송은 되지 않았습니다(⚙️ 기준·알림 설정).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
