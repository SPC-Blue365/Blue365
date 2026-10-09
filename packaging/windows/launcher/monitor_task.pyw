"""작업 스케줄러용 자동 감시 실행기 - 창 없이(pythonw.exe) 실행된다.

LIMS 동기화 → 이상 감지 → 알림 발송(app\\qms_monitor.py)을 실행하고 결과를 logs\\monitor.log 에 남긴다.
  --console  : 결과를 창에도 표시(5_MONITOR_TASK.bat 의 '지금 1회 실행')
  그 밖의 인자 : qms_monitor.py 에 그대로 전달(기본 --sync-lims --since-hours 24)
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
LOG = ROOT / "logs" / "monitor.log"
MAX_LOG_BYTES = 2_000_000
DEFAULT_ARGS = ["--sync-lims", "--since-hours", "24"]


class _Tee:
    """여러 출력 대상에 함께 쓰기(pythonw 에서는 sys.__stdout__ 이 None)."""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, text):
        for s in self.streams:
            try:
                s.write(text)
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except (OSError, ValueError):
                pass


def main() -> int:
    console = "--console" in sys.argv
    extra = [a for a in sys.argv[1:] if a != "--console"]
    os.environ.setdefault("QMS_DATA_DIR", str(ROOT / "data"))      # qms 모듈을 불러오기 전에 지정
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:
        LOG.replace(LOG.with_suffix(".old.log"))
    with LOG.open("a", encoding="utf-8", errors="replace") as log:
        out = _Tee(log, sys.__stdout__ if console else None)
        sys.stdout = sys.stderr = out
        print(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} 자동 감시 시작 =====")
        os.chdir(APP)
        sys.path.insert(0, str(APP))
        try:
            import qms_monitor
            rc = qms_monitor.main(extra or DEFAULT_ARGS)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        except Exception:  # noqa: BLE001 - 무인 실행이므로 원인을 기록에 남긴다
            traceback.print_exc()
            rc = 1
        print(f"----- 종료(코드 {rc}) {datetime.now():%H:%M:%S} -----")
        out.flush()
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    return rc


if __name__ == "__main__":
    sys.exit(main())
