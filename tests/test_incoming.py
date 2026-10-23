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


def test_incoming_standards_auto_judge(tmp_path, monkeypatch):
    """사내 기준(항목·최소/최대)으로 LIMS 합부판정이 빈 건을 자동 합/불 판정한다."""
    monkeypatch.setattr(I, "STD_PATH", tmp_path / "std.json")
    I.save_standards([{"대상": "규석", "항목": "SiO2", "min": 88, "max": None},
                      {"대상": "", "항목": "수분", "min": None, "max": 5},
                      {"대상": "", "항목": "엉뚱", "min": 1, "max": 2}])        # 목록 밖 항목은 저장에서 제외
    assert len(I.load_standards()) == 2
    # 규석 SiO2 85 → 불합격
    assert I.judge_one({"SiO2": 85.0, "수분": 3.0}, "규석", I.load_standards())[0] == I.FAIL
    # 규석 SiO2 90, 수분 6 → 불합격(수분 초과, SO3(XRF) 변형도 매칭 확인은 아래)
    assert I.judge_one({"SiO2": 90.0, "수분": 6.0}, "규석", I.load_standards())[0] == I.FAIL
    # 규석 SiO2 90, 수분 3 → 합격
    assert I.judge_one({"SiO2": 90.0, "수분": 3.0}, "규석", I.load_standards())[0] == I.PASS
    # 기준이 안 걸리는 품목 → 보류('')
    assert I.judge_one({"CaO": 50.0}, "석회석", I.load_standards())[0] == ""

    import pandas as pd
    df = pd.DataFrame([{"검사종류": "원료·부원료", "채취일": pd.Timestamp("2026-10-01"), "거래처": "A", "품명": "규석",
                        "합부판정": "", "비고": "", "성분": '{"SiO2": 85.0, "수분": 2.0}'},
                       {"검사종류": "원료·부원료", "채취일": pd.Timestamp("2026-10-02"), "거래처": "B", "품명": "규석",
                        "합부판정": "합격", "비고": "", "성분": '{"SiO2": 80.0}'}])  # LIMS 판정 우선
    j = I.judge_frame(df, I.load_standards())
    assert list(j["자동판정"]) == [I.FAIL, I.FAIL]
    assert list(j["최종판정"]) == [I.FAIL, "합격"]       # 2행은 LIMS '합격'이 우선
