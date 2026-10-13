"""화면에 보이는 이름(메뉴·화면 제목·항목 이름·단위)을 사용자가 직접 바꿔 저장하는 기능.

저장 위치: data/labels.json  (예: {"menu": {"출하시멘트": "출하 품질"}, "pages": {...}, "items": {"cem_blaine": {"name": "분말도"}},
                                   "ship_items": {"s28": {"name": "28일 강도"}}})
기본값은 코드에 그대로 두고, 바꾼 것만 저장한다(지우면 기본값으로 돌아감). 계산·판정에는 영향이 없다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .standards import DATA_DIR

LABELS_PATH = DATA_DIR / "labels.json"
SECTIONS = ("menu", "pages", "items", "ship_items")


def labels_mtime(path: Path = LABELS_PATH) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def load_labels(path: Path = LABELS_PATH) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        d = {}
    return {k: dict(d.get(k) or {}) for k in SECTIONS}


def save_labels(labels: dict, path: Path = LABELS_PATH) -> None:
    clean = {}
    for sec in SECTIONS:
        vals = labels.get(sec) or {}
        if sec in ("menu", "pages"):
            clean[sec] = {k: str(v).strip() for k, v in vals.items() if isinstance(v, str) and v.strip() and v.strip() != k}
        else:
            out = {}
            for k, v in vals.items():
                e = {f: str(v.get(f)).strip() for f in ("name", "unit") if isinstance(v, dict) and v.get(f) is not None
                     and str(v.get(f)).strip() != ""}
                if e:
                    out[k] = e
            clean[sec] = out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def menu(title: str, labels: dict | None = None) -> str:
    return (labels or load_labels())["menu"].get(title, title)


def page(title: str, labels: dict | None = None) -> str:
    return (labels or load_labels())["pages"].get(title, title)


def apply_registry(reg, labels: dict | None = None):
    """공정 항목(SpecRegistry) 이름·단위 바꾸기 — 바꾼 값만 덮어쓴다."""
    labels = labels or load_labels()
    for key, e in labels["items"].items():
        try:
            it = reg[key]
        except KeyError:
            continue
        if e.get("name"):
            it.name = e["name"]
        if "unit" in e:
            it.unit = e["unit"]
    return reg


def apply_shipment(labels: dict | None = None) -> None:
    """출하시멘트 항목 이름·단위 바꾸기(기본값에서 다시 계산하므로 지운 항목은 기본값으로 돌아감)."""
    from . import shipment as S
    labels = labels or load_labels()
    S.set_item_labels(labels["ship_items"])
