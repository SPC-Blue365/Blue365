"""경보 이력 로그 [ML-Engineer].

모니터 실행 시의 경보를 로컬 CSV에 누적한다(로컬 전용). 동일 (data_time,line,kind,message)는
중복 저장하지 않아 재실행/새로고침에도 이력이 오염되지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from config.paths import OUTPUTS_DIR

LOG_PATH = OUTPUTS_DIR / "alert_log.csv"
COLUMNS = ["run_time", "data_time", "line", "alias", "level", "kind", "message"]


def load_history(path: Path = LOG_PATH) -> pd.DataFrame:
    if Path(path).exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=COLUMNS)


def log_statuses(statuses: dict, path: Path = LOG_PATH) -> int:
    """상태들의 경보를 이력에 추가(중복 제외). 추가된 행 수 반환."""
    run_time = datetime.now().isoformat(timespec="seconds")
    rows = []
    for line, st in statuses.items():
        dt = str(st.latest_time)
        for a in st.alerts:
            rows.append(dict(run_time=run_time, data_time=dt, line=line, alias=st.alias,
                             level=a.level.label, kind=a.kind, message=a.message))
    new = pd.DataFrame(rows, columns=COLUMNS)
    hist = load_history(path)
    combined = pd.concat([hist, new], ignore_index=True)
    key = ["data_time", "line", "kind", "message"]
    before = len(hist)
    combined = combined.drop_duplicates(subset=key, keep="first").reset_index(drop=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return len(combined) - before
