"""HTML 대시보드용 항목 정의(기준·단위)와 샘플 데이터를 JSON으로 내보낸다 → dashboard/src/data.json

사용:  python scripts/export_dashboard_data.py
- SPEC   : 관리항목 key·이름·공정·단위·소수자리·핵심여부·품종별 기준(LSF·SM·f-CaO 등) + 표/열/품종/열이름 매핑
- SAMPLE : 데모 데이터(최근 N일) — 첫 화면 시연용. 실제 사용은 '데이터 불러오기'로 LIMS·실험실 내보내기 파일을 올린다.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QMS_DATA_DIR", tempfile.mkdtemp(prefix="qms_dash_"))

import pandas as pd

from qms.demo import generate_demo_data
from qms.standards import PRODUCTS, SpecRegistry
from qms.store import RAW_COLUMNS, SHEET_NAMES, TABLES, TEXT_COLUMNS

END = date(2026, 10, 10)
SAMPLE_DAYS = 75
RESAMPLE = {"raw_meal": "4h", "kiln": "4h"}      # 추이용으로 솎아 임베드 크기를 줄임(나머지는 native)


def spec_payload() -> dict:
    reg = SpecRegistry()
    items = []
    for it in reg.all():
        lims = {}
        for prod, lm in it.limits.items():
            d = {k: getattr(lm, k) for k in ("lsl", "usl", "target") if getattr(lm, k) is not None}
            if d:
                lims[prod] = d
        items.append({"key": it.key, "name": it.name, "stage": it.stage, "table": it.table, "unit": it.unit,
                      "decimals": it.decimals, "keyItem": it.key_item, "ksLabel": it.ks_label,
                      "byProduct": TABLES[it.table]["by_product"], "limits": lims})
    # 테이블별 열 순서·한글 열이름(파일 불러오기 매핑용), 시트명
    labels = {it.key: it.name for it in reg.all()}
    tables = {}
    for t, cols in RAW_COLUMNS.items():
        tables[t] = {"label": TABLES[t]["label"], "sheet": SHEET_NAMES.get(t, t),
                     "byProduct": TABLES[t]["by_product"],
                     "columns": [c for c in cols if c != "product"],
                     "labels": {c: labels.get(c, c) for c in cols if c != "product"}}
    return {"products": list(PRODUCTS), "textColumns": sorted(TEXT_COLUMNS), "items": items, "tables": tables,
            "stages": list(dict.fromkeys(it.stage for it in reg.all()))}


def sample_payload() -> dict:
    raw = generate_demo_data(end=END, days=120, seed=7)
    start = pd.Timestamp(END) - pd.Timedelta(days=SAMPLE_DAYS)
    out = {}
    for t, df in raw.items():
        if t not in RAW_COLUMNS or len(df) == 0:
            continue
        d = df[df["timestamp"] >= start].copy()
        if t in RESAMPLE and "product" not in d:
            num = [c for c in d.columns if c != "timestamp" and c not in TEXT_COLUMNS]
            d = d.set_index("timestamp")[num].resample(RESAMPLE[t]).mean().dropna(how="all").reset_index()
        cols = list(dict.fromkeys(c for c in RAW_COLUMNS[t] if c in d.columns and c not in ("timestamp", "product")))
        by_product = bool(TABLES[t]["by_product"] and "product" in d.columns)
        d = d.loc[:, ~d.columns.duplicated()].sort_values("timestamp")
        ts = d["timestamp"].dt.strftime("%Y-%m-%dT%H:%M").tolist()
        prod = d["product"].tolist() if by_product else None
        series = {c: d[c].tolist() for c in cols}
        rows = []
        for i in range(len(d)):
            row = [ts[i]] + ([prod[i]] if by_product else [])
            for c in cols:
                v = series[c][i]
                row.append(None if pd.isna(v) else (str(v) if c in TEXT_COLUMNS else round(float(v), 3)))
            rows.append(row)
        out[t] = {"byProduct": by_product, "columns": cols, "rows": rows}
    return out


def main(out: Path) -> None:
    payload = {"spec": spec_payload(), "sample": sample_payload(),
               "generated": pd.Timestamp.now().strftime("%Y-%m-%d"), "sampleEnd": str(END)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(len(t["rows"]) for t in payload["sample"].values())
    print(f"저장: {out}  ({out.stat().st_size / 1024:.0f} KB, 샘플 {n:,}행, 항목 {len(payload['spec']['items'])}개)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dashboard" / "src" / "data.json")
