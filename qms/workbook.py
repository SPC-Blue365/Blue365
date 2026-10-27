"""통합 업로드 양식(한 파일 = 공정 시트 + 출하시멘트 + 인수검사) 읽기·반영.

📥 데이터 관리 업로드, 폴더 자동 반영(--import-dir), 고정 파일 매일 반영(--sync-file)이 모두 이 모듈을 쓴다.
- 공정 시트(원료·킬른·클링커·클링커일일·시멘트·물성)와 LIMS 원본 공정 파일 → qms.store
- 출하시멘트 형식 시트(LIMS 시멘트성적·출하시멘트) → qms.shipment (공정 시트로는 다시 읽지 않음)
- 인수검사 시트(원료·부원료·석고·고령토) → qms.incoming
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import incoming, shipment
from .store import INFO_SHEETS, SHEET_ALIASES, SHEET_NAMES, UploadResult, parse_upload, save_raw

PROCESS_SHEETS = frozenset(SHEET_NAMES.values()) | frozenset(SHEET_ALIASES)


@dataclass
class WorkbookParts:
    process: UploadResult
    ships: list[tuple[str, shipment.ShipParse]] = field(default_factory=list)
    incomings: list[tuple[str, incoming.IncomingParse]] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)

    @property
    def is_template(self) -> bool:
        """통합 업로드 양식(공정 시트 이름이 있는 파일)인가."""
        return bool(set(self.sheet_names) & PROCESS_SHEETS)

    @property
    def kinds(self) -> list[str]:
        out = []
        if self.process.tables:
            out.append("공정 데이터")
        if any(len(p.records) for _, p in self.ships):
            out.append("출하시멘트")
        if any(len(p.rows) for _, p in self.incomings):
            out.append("인수검사")
        return out

    def summary(self) -> list[str]:
        lines = [m for m in self.process.messages if "데이터 행이 없습니다" not in m]
        lines += [f"[출하시멘트·{sn}] {len(p.records)}건 인식" for sn, p in self.ships if len(p.records)]
        lines += [m for _, p in self.incomings for m in p.messages]
        return lines

    @property
    def errors(self) -> list[str]:
        return list(self.process.errors) + [f"[출하시멘트·{sn}] {e}" for sn, p in self.ships for e in p.errors]


def analyze(content: bytes, filename: str) -> WorkbookParts:
    """파일 한 개를 시트별로 나눠 읽는다(저장하지 않음)."""
    if not filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return WorkbookParts(parse_upload(content, filename))
    ships: list[tuple[str, shipment.ShipParse]] = []
    incs: list[tuple[str, incoming.IncomingParse]] = []
    ship_sheets: set[str] = set()
    overrides = shipment.load_header_map()
    try:
        sheets = shipment.read_aoa(content, filename)
    except Exception:  # noqa: BLE001 - 읽지 못하면 공정 파서가 오류 메시지를 낸다
        sheets = []
    for sn, aoa in sheets:
        if sn in INFO_SHEETS or sn in PROCESS_SHEETS or not aoa:
            continue
        if shipment.detect(aoa):                                   # 출하시멘트 시트
            ship_sheets.add(sn)
            p = shipment.parse_aoa(aoa, overrides)
            p.sheet = sn
            if len(p.records):                                     # 머리글만 있는 빈 시트는 조용히 건너뜀
                ships.append((sn, p))
            continue
        ip = incoming.parse_incoming_df(pd.DataFrame(aoa))          # 인수검사 시트(제목에 '인수검사·석고·고령토')
        if not ip.errors and not ip.rows.empty:
            incs.append((sn, ip))
            ship_sheets.add(sn)
    proc = parse_upload(content, filename, skip_sheets=ship_sheets)
    if not proc.tables and (ships or incs):                        # 공정 시트가 없을 뿐이면 오류로 보지 않음
        proc = UploadResult({}, [], [])
    return WorkbookParts(proc, ships, incs, [sn for sn, _ in sheets])


def apply(parts: WorkbookParts) -> list[str]:
    """analyze() 결과를 저장하고 반영 내역을 돌려준다."""
    logs: list[str] = []
    if parts.process.tables:
        counts = save_raw(parts.process.tables, replace=False)
        names = {k: SHEET_NAMES.get(k, k) for k in counts}
        logs.append("공정 데이터: " + ", ".join(f"{names[k]} 누계 {v}행" for k, v in counts.items()))
    for sn, p in parts.ships:
        if len(p.records) and not p.errors:
            r = shipment.save_shipment(p.records)
            logs.append(f"출하시멘트({sn}): 추가 {r['added']}·갱신 {r['updated']}")
    for sn, p in parts.incomings:
        n = incoming.save_incoming(p.rows)
        logs.append(f"인수검사({sn}·{p.kind}): {len(p.rows)}행 → 누계 {n}행")
    return logs


def load_file(path) -> tuple[WorkbookParts, bytes]:
    with open(path, "rb") as f:
        content = f.read()
    return analyze(content, str(path)), content


