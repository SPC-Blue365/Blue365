"""원료·석고·고령토 인수검사: LIMS 파일 인식·파싱·저장·요약, 공정 파일은 제외."""

import io

import openpyxl

from qms import incoming as I


def _book(title, headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([title])
    ws.append(["검사일 : 2026-09-01 ~ 2026-10-23"])
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_incoming_parse_judge_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "INCOMING_DB_PATH", tmp_path / "incoming.db")
    gyp = _book("석고류 인수검사", ["로트번호", "검사일", "채취일", "거래처", "품명", "SO3(XRF)", "순도", "합부판정", "비고"],
                [["L1", "2026-09-01", "2026-09-01", "정도개발", "탈황석고", 44.0, 95.0, "합격", ""],
                 ["L2", "2026-09-02", "2026-09-02", "GS동해", "탈황석고", 43.0, 94.0, "불합격", "수분초과"],
                 ["", "", "", "", "", "", "", "", ""]])          # 날짜 없는 행 → 건너뜀
    p = I.parse_incoming(gyp, "석고.xlsx")
    assert not p.errors and p.kind == "석고" and len(p.rows) == 2
    assert list(p.rows["합부판정"]) == ["합격", "불합격"]
    assert (p.rows["비고"].astype(str).str.lower() == "nan").sum() == 0      # 빈 값이 'nan' 문자열이 되지 않음
    assert I.save_incoming(p.rows) == 2

    # 판정 표기 다양성 + 성분 JSON 보존
    kao = _book("삼척고령토", ["로트번호", "검사일", "채취일", "품명", "LOI", "SiO2", "Al2O3", "합부판정"],
                [["K1", "2026-09-30", "2026-09-30", "고령토", 1.2, 48.0, 36.0, "OK"]])
    pr = I.parse_incoming(kao, "고령토.xlsx")
    assert pr.rows.iloc[0]["합부판정"] == "합격"
    import json
    comp = json.loads(pr.rows.iloc[0]["성분"])
    assert comp.get("SiO2") == 48.0 and comp.get("Al2O3") == 36.0
    I.save_incoming(pr.rows)

    s = I.summary()
    assert s["total"] == 3 and s["pass"] == 2 and s["fail"] == 1
    assert set(s["by_kind"]["검사종류"]) == {"석고", "고령토"}
    assert len(s["fails"]) == 1 and s["fails"].iloc[0]["거래처"] == "GS동해"


def test_process_file_is_not_incoming():
    """시멘트성적 등 공정 파일은 인수검사로 오인하지 않는다."""
    proc = _book("시멘트성적", ["채취일", "품명", "압축강도28일(MPa)"], [["2026-09-01", "1종시멘트 벌크", 57.1]])
    assert not I.looks_like_incoming(proc, "시멘트성적.xlsx")
    assert I.parse_incoming(proc, "x.xlsx").errors
