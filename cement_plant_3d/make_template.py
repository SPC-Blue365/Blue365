"""업로드양식.xlsx 생성 — QMS 통합 업로드 양식(LIMS 원본 형식) (개발용 · openpyxl 필요).

시트·머리글·단위는 qms_template_spec.json(현장 QMS 파일에서 추출, 2026-11 양식 개정 반영)을 그대로 씁니다.
  python make_template.py
"""
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
OUT = HERE / "업로드양식.xlsx"
SPEC = json.loads((HERE / "qms_template_spec.json").read_text(encoding="utf-8"))

BLUE, ORANGE, GREY, INK = "3182F6", "F59E0B", "EEF1F4", "191F28"
FONT = "맑은 고딕"
THIN = Side(style="thin", color="E5E8EB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
DATA_ROWS = 20000   # 목록 선택이 적용되는 행 수 (5행부터)

# 공정구분 코드표 — 이 공장 설비 기준 (열: 이름, 값 목록)
CODES = [
    ("킬른(호기)", ["3K", "4K", "5K", "6K", "7K"]),
    ("원료밀", ["3R/M", "4R/M", "5R/M", "5-1R/M", "6R/M", "7R/M"]),
    ("시멘트밀", ["2C/M", "3C/M", "4C/M", "5C/M", "6C/M", "7C/M"]),
    ("시멘트 품종", ["1종", "3종", "고로슬래그 2종", "고로슬래그 3종"]),
    ("원료 종류(품명)", ["1종조합원료", "1/2종조합원료", "2종조합원료", "3종조합원료"]),
    ("클링커 종류(품명)", ["내수", "수출클링커", "3종", "1종크링커", "1/2종크링커"]),
    ("시멘트 종류(품명)", ["1종시멘트 벌크", "3종시멘트 벌크", "2종고로슬래그시멘트 벌크", "3종고로슬래그시멘트 벌크"]),
    ("킬른·원료밀(원료 시트용)", ["3K", "4K", "5K", "6K", "7K", "3R/M", "4R/M", "5R/M", "5-1R/M", "6R/M", "7R/M"]),
    ("클링커 투입사일로", ["2호", "4호", "5호", "6-1호", "6-2호", "6-3호", "6-4호", "6-5호", "6-6호"]),
    ("시멘트 투입사일로", ["구내1호", "구내2호", "구내5호", "구내6호", "구내7호", "구내8호", "구내9호", "구내10호", "구내11호",
                       "부두1호", "부두2호", "부두3호", "부두4호", "부두5호", "부두6호"]),
    ("원료 투입사일로", ["기존3호", "기존4호", "6-1", "6-2", "7-1", "7-2"]),
    ("클링커 구분", ["내수", "수출클링커"]),
    ("시멘트 구분", ["내수", "3종", "S/C2종", "S/C3종"]),
    ("고령토 구분", ["기존", "신설"]),
]
CODE_COL = {name: get_column_letter(i + 2) for i, (name, _v) in enumerate(CODES)}
CODE_LEN = {name: len(v) for name, v in CODES}


def code_range(name):
    c = CODE_COL[name]
    return f"=공정구분!${c}$4:${c}${3 + CODE_LEN[name]}"


def group_of(sheet):
    if sheet.startswith("원료"):
        return "원료"
    if sheet.startswith("클링커일일"):
        return "클링커일일"
    if sheet.startswith("클링커"):
        return "클링커"
    if sheet.startswith("출하시멘트"):
        return "출하시멘트"
    return sheet


REQUIRED = {}
for row in SPEC["dict"]:
    if len(row) >= 3 and row[2] == "필수":
        REQUIRED.setdefault(row[0], set()).add(row[1])


def lists_for(sheet, header):
    """머리글 → 목록 선택 범위"""
    if header == "공정구분":
        if sheet == "원료 잔사":
            return code_range("원료밀")
        if sheet.startswith("원료"):
            return code_range("킬른·원료밀(원료 시트용)")
        if sheet.startswith("시멘트"):
            return code_range("시멘트밀")
        if sheet == "인수검사(고령토)":
            return code_range("고령토 구분")
        return code_range("킬른(호기)")
    if header == "품명":
        if sheet.startswith("원료"):
            return code_range("원료 종류(품명)")
        if sheet.startswith("클링커"):
            return code_range("클링커 종류(품명)")
        if sheet.startswith("시멘트") or sheet.startswith("출하시멘트"):
            return code_range("시멘트 종류(품명)")
    if header == "클링커 투입사일로":
        return code_range("클링커 투입사일로")
    if header == "클링커 구분":
        return code_range("클링커 구분")
    if header in ("시멘트구분", "시멘트 구분"):
        return code_range("시멘트 구분")
    if header == "시멘트 투입사일로":
        return code_range("시멘트 투입사일로")
    if header in ("투입사일로", "투입SILO"):
        return code_range("원료 투입사일로")
    return None


def main():
    wb = Workbook()
    # ---- 사용법 ----
    g = wb.active
    g.title = "사용법"
    lines = [
        ("Blue365 시멘트 공정 3D · QMS 통합 업로드 양식 (LIMS 원본 형식)", "title"),
        ("", None),
        ("■ 쓰는 순서", "h"),
        ("  1) LIMS에서 공정별 결과를 내려받아, 맞는 시트의 5행부터 붙여넣습니다 (1~4행 제목·안내·머리글·단위는 그대로).", None),
        ("  2) ‘공정구분’(호기·밀), ‘품명’, ‘클링커 구분’·‘시멘트구분’ 칸은 목록에서 고릅니다. 예: 킬른 5K·6K·7K / 원료밀 5-1R/M / 시멘트밀 3C/M.", None),
        ("  3) 화면 오른쪽 위 [데이터] 버튼 → 이 파일을 끌어다 놓기 → 결과 확인 → 적용. 팀 공유 서버로 접속했다면 ‘팀에 공유하고 적용’.", None),
        ("", None),
        ("■ 꼭 지킬 것", "h"),
        ("  · 주황색 머리글 = 필수 칸입니다. ‘채취일’이 빈 행은 읽지 않습니다. 채취일은 실제 채취한 날짜(YYYY-MM-DD)로 넣으세요.", None),
        ("  · 공정구분(호기·밀)을 꼭 넣으세요. 화면은 호기·밀별로 따로 보여 줍니다 (모르는 코드의 행은 건너뜁니다).", None),
        ("  · 머리글 이름은 바꾸지 마세요(LIMS 이름 그대로여야 자동 연결). 시트 이름·열 순서는 바꿔도 되고, 안 쓰는 열은 지워도 됩니다.", None),
        ("  · 분석값의 0 또는 빈 칸 = 결과가 아직 안 나왔거나 시험하지 않은 값(미시험)으로 처리합니다. 음수(검출한계 아래 등)도 빼고 계산합니다.", None),
        ("  · 운전값(킬른·시멘트 시트, DCS)의 0은 실제 값(정지)으로 봅니다. 측정하지 않은 칸은 0이 아니라 빈 칸으로 두세요.", None),
        ("  · LSF·SM·IM·C₃S 등 계산값은 LIMS 값을 그대로 씁니다. 그 열이 없으면 화면이 산화물로 같은 식으로 계산합니다.", None),
        ("  · 3호 킬른·3호 R/M 결과는 ‘원료(4~5-1호)’·‘클링커(4K,5K)’ 시트에 3K·3R/M으로 넣으면 됩니다.", None),
        ("  · 시멘트밀 시트의 Blaine·45㎛ 값이 LIMS에서 서로 바뀌어 나와도 화면이 값 크기로 알아보고 바로잡습니다.", None),
        ("  · 앞뒤 행과 동떨어진 날짜(오타로 보이는 날짜)는 불러오기 결과에 ‘확인해 주세요’로 알려 줍니다. 미래 날짜는 읽지 않습니다.", None),
        ("", None),
        ("■ 시트와 화면 연결", "h"),
        ("  · 원료(4~5-1호)·원료(6~7호)  원료밀 출구(R/M)·킬른 요입(K) 조합원료 XRF → 원료밀·원료 사일로·킬른 상세, 요입 LSF", None),
        ("  · 원료 잔사                 90㎛·200㎛ 잔사 → 원료밀 상세", None),
        ("  · 킬른                      DCS 시간 평균값(원료·석탄 투입량, 소성대 온도, O₂·CO, 주모터 부하 등) → 킬른·예열기 운전값, 생산량·가동률 (비우면 가상값)", None),
        ("  · 클링커(6K,7K)·클링커(4K,5K) 호기별 클링커 XRF·f-CaO·LIMS 계산값 → 킬른 품질, f-CaO 관리도, 클링커 사일로 최근 투입(내수·수출)", None),
        ("  · 클링커일일                XRD 광물상·크롬 (분석하는 경우만)", None),
        ("  · 시멘트                    시멘트밀 운전 DCS(투입량·밀 출구 온도) → C/M 운전값 (비우면 가상값)", None),
        ("  · 시멘트밀                  시멘트밀(C/M)별 공정 시료 → C/M 분말도·SO₃, 현재 생산 품종·투입 사일로, 시멘트 사일로 최근 투입", None),
        ("  · 출하시멘트(1종·3종·고로슬래그2종)  출하 로트 물성·강도 → 경영진 요약의 출하 강도·KS 판정", None),
        ("  · 인수검사(원료·석고·고령토)  인수검사 로트 → 경영진 요약의 인수검사 현황", None),
        ("  · 공정구분                  목록 선택에 쓰는 코드표 (설비가 바뀌면 이 시트만 고치세요)", None),
        ("  · 항목사전                  모든 열의 뜻·단위·필수 여부", None),
        ("", None),
        ("■ 데이터가 없는 공정은?  해당 시트를 비워 두면 됩니다 (머리글만 있는 시트는 건너뜀).", None),
        ("■ 설비 운전값(생산량·부하·레벨 등)은 이 파일에 없으면 화면에서 가상값으로 표시합니다.", None),
    ]
    for i, (t, kind) in enumerate(lines, 1):
        c = g.cell(row=i, column=2, value=t)
        c.font = Font(name=FONT, size=15 if kind == "title" else 11, bold=kind in ("title", "h"), color=BLUE if kind == "h" else INK)
    g.column_dimensions["A"].width = 2
    g.column_dimensions["B"].width = 130

    # ---- 공정구분 ----
    cs = wb.create_sheet("공정구분")
    cs["A1"] = "공정구분·품명 코드표 — 각 시트의 목록 선택에 쓰입니다 (값을 고치면 목록도 바뀜)"
    cs["A2"] = "3행이 구분 이름, 4행부터 코드입니다. 칸을 늘리면 각 시트의 목록 범위도 함께 늘려야 하니, 설비 변경 시 관리자에게 알려 주세요."
    cs["A1"].font = Font(name=FONT, bold=True, size=12, color=INK)
    cs["A2"].font = Font(name=FONT, color="8B95A1")
    for i, (name, vals) in enumerate(CODES):
        col = i + 2
        h = cs.cell(row=3, column=col, value=name)
        h.font = Font(name=FONT, bold=True, color="FFFFFF")
        h.fill = PatternFill("solid", fgColor=BLUE)
        h.alignment = Alignment(horizontal="center")
        for j, v in enumerate(vals):
            c = cs.cell(row=4 + j, column=col, value=v)
            c.font = Font(name=FONT)
            c.border = BOX
        cs.column_dimensions[get_column_letter(col)].width = 22
    cs.column_dimensions["A"].width = 3

    # ---- 데이터 시트 (원본 머리글 그대로) ----
    for sp in SPEC["sheets"]:
        ws = wb.create_sheet(sp["name"])
        n = len(sp["headers"])
        ws.cell(row=1, column=1, value=sp["title"]).font = Font(name=FONT, bold=True, size=12, color=INK)
        if sp.get("guide"):
            ws.cell(row=2, column=1, value=sp["guide"]).font = Font(name=FONT, color="4E5968")
        req = REQUIRED.get(group_of(sp["name"]), set()) | {"채취일"}
        for i, h in enumerate(sp["headers"], 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = Font(name=FONT, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=ORANGE if h in req else BLUE)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = BOX
            u = ws.cell(row=4, column=i, value=sp["units"][i - 1] or None)
            u.font = Font(name=FONT, italic=True, color="8B95A1", size=9)
            u.fill = PatternFill("solid", fgColor=GREY)
            u.alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(i)].width = max(9, min(26, len(str(h)) * 1.6 + 3))
            rng = lists_for(sp["name"], h)
            if rng:
                dv = DataValidation(type="list", formula1=rng, allow_blank=True, showErrorMessage=True, errorStyle="warning",
                                    errorTitle="목록에 없는 값", error="목록에 없는 코드입니다. 그래도 넣으려면 ‘예’를 누르세요.")
                dv.add(f"{get_column_letter(i)}5:{get_column_letter(i)}{DATA_ROWS}")
                ws.add_data_validation(dv)
        ws.row_dimensions[3].height = 30
        ws.freeze_panes = "A5"
        ws.sheet_properties.tabColor = BLUE
        ws.cell(row=1, column=max(1, n)).alignment = Alignment()

    # ---- 항목사전 ----
    ds = wb.create_sheet("항목사전")
    ds["A1"] = "항목사전 — 모든 열의 뜻·단위·필수 여부"
    ds["A1"].font = Font(name=FONT, bold=True, size=12, color=INK)
    for r, row in enumerate(SPEC["dict"], 2):
        for c, v in enumerate(row[:6], 1):
            cell = ds.cell(row=r, column=c, value=v or None)
            cell.font = Font(name=FONT, bold=(r == 2), color="FFFFFF" if r == 2 else INK)
            if r == 2:
                cell.fill = PatternFill("solid", fgColor=BLUE)
            cell.border = BOX
    for c, w in zip("ABCDEF", (14, 22, 7, 14, 24, 70)):
        ds.column_dimensions[c].width = w
    ds.freeze_panes = "A3"
    wb.save(OUT)
    print(f"생성: {OUT}")


if __name__ == "__main__":
    main()
