"""업로드양식.xlsx 생성 (개발용 · openpyxl 필요).

사내망 PC에는 필요 없습니다. 만들어진 업로드양식.xlsx만 배포하면 됩니다.
  python make_template.py
설비코드·항목코드는 src.html 의 EQ 정의와 같아야 합니다.
"""
import datetime as dt
import math
import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent / "업로드양식.xlsx"
random.seed(20261110)

# (설비코드, 항목코드, 항목명, 단위, 하한, 상한, 예시값, 흔들림)
PARAMS = [
    ("QRY-1", "rate", "가동률", "%", None, None, 86, 1.5),
    ("QRY-1", "out", "채광량", "t/h", 600, None, 820, 20),
    ("QRY-1", "cao", "석회석 CaO 품위", "%", 47.5, None, 50.2, 0.2),
    ("QRY-1", "mgo", "석회석 MgO", "%", None, 3.0, 1.6, 0.05),
    ("CR-1", "load", "부하", "%", None, 95, 78, 2),
    ("CR-1", "feed", "처리량", "t/h", 800, None, 1150, 25),
    ("CR-1", "size", "출구 입도 (P90)", "mm", None, 80, 62, 2),
    ("CR-1", "cur", "모터 전류", "A", None, 380, 312, 6),
    ("PB-1", "fill", "저장률", "%", 25, 95, 64, 1),
    ("PB-1", "stock", "파일 재고", "t", None, None, 38400, 300),
    ("PB-1", "sd", "공급 CaO 표준편차", "%", None, 0.5, 0.32, 0.02),
    ("PB-1", "lsf", "파일 LSF", "", 95.0, 99.5, 97.1, 0.15),
    ("RM-1", "load", "부하", "%", None, 98, 88, 1.5),
    ("RM-1", "prod", "생산량", "t/h", 360, None, 410, 6),
    ("RM-1", "lsf", "원료 LSF", "", 96.0, 99.0, 97.6, 0.25),
    ("RM-1", "sm", "원료 SM", "", 2.35, 2.70, 2.52, 0.02),
    ("RM-1", "im", "원료 IM", "", 1.40, 1.75, 1.58, 0.02),
    ("RM-1", "r90", "90 µm 잔분", "%", None, 16, 13.2, 0.3),
    ("CF-1", "level", "레벨", "%", 30, 92, 71, 1),
    ("CF-1", "stock", "저장량", "t", None, None, 12800, 100),
    ("CF-1", "lsf", "공급 원료 LSF", "", 96.0, 99.0, 97.4, 0.1),
    ("CS-1", "level", "레벨", "%", 20, 95, 58, 0.5),
    ("CS-1", "stock", "재고", "t", None, None, 34800, 150),
    ("CM-1", "load", "부하", "%", None, 97, 84, 1.5),
    ("CM-1", "prod", "생산량", "t/h", 160, None, 182, 3),
    ("CM-1", "r45", "45 µm 잔분", "%", None, 12, 8.4, 0.2),
    ("CM-1", "temp", "밀 출구 온도", "℃", None, 120, 104, 1.5),
    ("QC-LAB", "queue", "분석 대기 시료", "건", None, 10, 4, 1),
    ("QC-LAB", "xrf", "XRF 표준시료 편차", "%", None, 0.30, 0.12, 0.02),
    ("QC-LAB", "tat", "평균 분석 소요", "분", None, 30, 18, 1.5),
]
# 킬른 3~7호 설계 용량(t/d) — 화면 src.html 의 KILN_DEF 와 같아야 함. 3호는 가동 중단
KILNS = [(3, 2500), (4, 2549), (5, 2678), (6, 7100), (7, 7100)]
STOPPED = {3}
CLK_FACTOR = 1.55  # 원료/클링커 환산계수
for n, cap in KILNS:
    sc = cap / 5000
    feed = round(cap * CLK_FACTOR / 24 * 0.995)
    c = f"KL-{n}"
    PARAMS += [
        (c, "calc", "킬른 입구 하소율", "%", 90, 97, 93.5, 0.4),
        (c, "c1", "C1 출구 가스 온도", "℃", None, 345, 318, 3),
        (c, "pc", "하소로 출구 온도", "℃", 860, 900, 878, 4),
        (c, "press", "C1 출구 정압", "mmAq", None, None, -520, 8),
        (c, "bzt", "소성대 온도 (고온계)", "℃", 1400, 1500, 1452, 6),
        (c, "cur", "주모터 전류", "A", round(520 * sc), round(720 * sc), round(612 * sc), 10 * sc),
        (c, "o2", "킬른 입구 O₂", "%", 1.5, 4.0, 2.6, 0.1),
        (c, "co", "킬른 입구 CO", "ppm", None, 800, 180, 40),
        (c, "nox", "킬른 입구 NOx", "ppm", None, 1200, 820, 25),
        (c, "rpm", "회전수", "rpm", None, None, 4.0, 0.03),
        (c, "feed", "원료 투입량", "t/h", round(feed * 0.9), round(feed * 1.07), feed, 3 * sc),
        (c, "mload", "주모터 부하", "%", None, 95, 74, 1.5),
        (c, "eff", "냉각 효율", "%", 65, None, 72, 0.6),
        (c, "tout", "클링커 출구 온도", "℃", None, 130, 108, 3),
        (c, "sec", "2차 공기 온도", "℃", 1000, None, 1080, 10),
        (c, "grate", "그레이트 속도", "spm", None, None, 11.2, 0.2),
    ]
# 관리기준 시트에만 넣는 항목 (값은 다른 시트에서 들어옴)
EXTRA_LIMITS = [(f"KL-{n}", "fcao", "f-CaO", "%", 0.8, 1.8) for n, _ in KILNS] + [
    ("CM-1", "blaine", "분말도 (Blaine)", "cm²/g", 3200, 3500),
    ("CM-1", "so3", "SO₃", "%", 1.9, 2.6),
    ("SL-1~4", "s1", "S-1 · 1종 보통", "%", 15, 95),
    ("SL-1~4", "s2", "S-2 · 1종 보통", "%", 15, 95),
    ("SL-1~4", "s3", "S-3 · 슬래그 시멘트", "%", 15, 95),
    ("SL-1~4", "s4", "S-4 · 1종 보통", "%", 15, 95),
]

BLUE = "3182F6"
HEAD = PatternFill("solid", fgColor=BLUE)
SOFT = PatternFill("solid", fgColor="E8F3FF")
GREY = PatternFill("solid", fgColor="F2F4F6")
THIN = Side(style="thin", color="E5E8EB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = "맑은 고딕"


def sheet(wb, title, headers, rows, widths, fmts=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BOX
    for r in rows:
        ws.append(list(r))
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name=FONT)
            c.border = BOX
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for col, f in (fmts or {}).items():
        for c in ws[col][1:]:
            c.number_format = f
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22
    return ws


def main():
    today = dt.datetime(2026, 11, 10)
    wb = Workbook()
    g = wb.active
    g.title = "안내"
    lines = [
        ("Blue365 시멘트 공정 3D · 데이터 업로드 양식", "title"),
        ("", None),
        ("사용 방법", "h"),
        ("1. 필요한 시트만 채웁니다. 5개 시트를 모두 채울 필요는 없습니다.", None),
        ("2. 첫 줄(파란 머리글)의 열 이름은 바꾸지 마세요. 시트 이름은 바꿔도 됩니다.", None),
        ("3. 들어 있는 값은 예시입니다. 지우고 실제 값을 넣으세요.", None),
        ("4. 화면 오른쪽 위 ‘데이터’ 버튼 → 파일을 끌어다 놓기 → 결과 확인 → 적용.", None),
        ("5. 팀 공유 서버(server.py)로 접속했다면 ‘팀에 공유하고 적용’을 누르면 모든 접속자 화면에 20초 안에 반영됩니다.", None),
        ("", None),
        ("시트 설명", "h"),
        ("공정값       일시·설비코드·항목코드·값. 같은 항목을 여러 시각으로 넣으면 추이 그래프와 알람 이력이 만들어집니다.", None),
        ("클링커XRF    호기(3호~7호)별 클링커 산화물(%)과 f-CaO. LSF·SM·IM과 Bogue 광물(C₃S 등)을 호기별로 계산합니다.", None),
        ("시멘트품질   품종별 분말도·SO₃·MgO·강열감량·압축강도. KS L 5201 대비 판정에 씁니다. 강도는 비워도 됩니다.", None),
        ("생산출하     일자별 클링커 생산(공장 합계)·시멘트 출하·출하계획, 킬른 가동률(선택), 제품 사일로 S-1~S-4 레벨(선택).", None),
        ("관리기준     설비·항목별 하한·상한(사내 관리기준). 들어 있는 값은 예시이니 사내 기준으로 고치세요. 한쪽만 있는 기준은 다른 칸을 비워 둡니다.", None),
        ("", None),
        ("입력 규칙", "h"),
        ("· 일시: 2026-11-10 09:00 형식 또는 엑셀 날짜·시간 서식. 일자: 2026-11-10.", None),
        ("· 숫자 칸에는 숫자만 넣습니다(단위·기호 없이). 천 단위 쉼표는 괜찮습니다.", None),
        ("· 설비코드·항목코드는 ‘관리기준’ 시트 목록을 참고하세요. 킬른은 KL-3 ~ KL-7 (3호~7호). 가동 중단 호기는 원료 투입량(feed)을 0으로 넣으면 ‘가동 중단’으로 표시됩니다. 예) KL-5 / bzt = 5호 킬른 소성대 온도. ‘5호’, ‘5호기’로 적어도 됩니다.", None),
        ("· 저장 형식은 ‘Excel 통합 문서(.xlsx)’. CSV로 올릴 때는 시트마다 따로 저장하면 됩니다.", None),
        ("", None),
        ("참고", "h"),
        ("· KS 기준값은 화면에 KS L 5201 1종 기준으로 표시합니다. 최신 개정판 원문과 대조 후 사용하세요.", None),
    ]
    for i, (t, kind) in enumerate(lines, 1):
        c = g.cell(row=i, column=1, value=t)
        c.font = Font(name=FONT, size=16 if kind == "title" else 11, bold=kind in ("title", "h"),
                      color=BLUE if kind == "h" else "191F28")
        if kind == "h":
            c.fill = SOFT
    g.column_dimensions["A"].width = 120

    # 공정값: 오늘 06~09시 매시
    rows = []
    for h in range(6, 10):
        t = today.replace(hour=h)
        for code, key, name, unit, lo, hi, v, n in PARAMS:
            if code in {f"KL-{k}" for k in STOPPED}:
                if key == "feed":  # 가동 중단 호기: 원료 투입량 0 → 화면에서 '가동 중단'으로 표시
                    rows.append((t, code, key, name, unit, 0))
                continue
            val = v + random.uniform(-1, 1) * n
            rows.append((t, code, key, name, unit, round(val, 2 if abs(v) < 10 else 1 if abs(v) < 1000 else 0)))
    sheet(wb, "공정값", ["일시", "설비코드", "항목코드", "항목명", "단위", "값"], rows,
          [18, 11, 11, 22, 8, 12], {"A": "yyyy-mm-dd hh:mm"})

    # 클링커XRF: 호기별 2시간 간격 2일
    rows = []
    for n, _cap in KILNS:
        if n in STOPPED:
            continue
        for i in range(24):
            t = today.replace(hour=8) - dt.timedelta(hours=2 * (23 - i))
            fca = 1.2 + random.gauss(0, 0.15) + (0.6 if (n == 7 and i == 15) else 0)
            rows.append((t, f"{n}호", round(65.8 + random.gauss(0, 0.15), 2), round(21.6 + random.gauss(0, 0.1), 2),
                         round(5.2 + random.gauss(0, 0.05), 2), round(3.3 + random.gauss(0, 0.04), 2),
                         round(3.1 + random.gauss(0, 0.04), 2), round(0.8 + random.gauss(0, 0.05), 2), round(max(0.3, fca), 2)))
    rows.sort(key=lambda r: (r[0], r[1]))
    sheet(wb, "클링커XRF", ["일시", "호기", "CaO(%)", "SiO2(%)", "Al2O3(%)", "Fe2O3(%)", "MgO(%)", "SO3(%)", "f-CaO(%)"], rows,
          [18, 8, 10, 10, 10, 10, 10, 10, 10], {"A": "yyyy-mm-dd hh:mm"})

    # 시멘트품질: 최근 35일 일 1회 (강도는 재령이 지난 것만)
    rows = []
    for d in range(35, -1, -1):
        t = (today - dt.timedelta(days=d)).replace(hour=10)
        prod = "슬래그 시멘트" if d % 6 == 0 else "1종 보통 포틀랜드"
        b = 3350 + random.gauss(0, 40)
        s28 = 52 + random.gauss(0, 1.2) if d >= 28 else None
        s7 = 37 + random.gauss(0, 1) if d >= 7 else None
        s3 = 26 + random.gauss(0, 1) if d >= 3 else None
        rows.append((t, prod, round(b), round(2.3 + random.gauss(0, 0.06), 2), round(2.95 + random.gauss(0, 0.05), 2),
                     round(2.1 + random.gauss(0, 0.1), 2), s3 and round(s3, 1), s7 and round(s7, 1), s28 and round(s28, 1)))
    sheet(wb, "시멘트품질", ["일시", "품종", "Blaine(cm²/g)", "SO3(%)", "MgO(%)", "강열감량(%)", "3일강도(MPa)", "7일강도(MPa)", "28일강도(MPa)"],
          rows, [18, 18, 14, 9, 9, 11, 13, 13, 13], {"A": "yyyy-mm-dd hh:mm"})

    # 생산출하: 최근 30일
    rows = []
    for d in range(29, -1, -1):
        t = today - dt.timedelta(days=d)
        clk = 19150 + random.gauss(0, 200) - (900 if d == 9 else 0)
        run = 100.0 - (17.5 if d == 9 else 0) - abs(random.gauss(0, 0.6))
        ship = 5200 + random.gauss(0, 260)
        lv = [72 - d * 0.3, 61 + math.sin(d) * 8, 44 + math.cos(d) * 6, 16.6 + d * 0.5]
        rows.append((t, round(clk), round(ship), 5200, round(run, 1), *[round(x, 1) for x in lv]))
    sheet(wb, "생산출하", ["일자", "클링커생산(t)", "시멘트출하(t)", "출하계획(t)", "킬른가동률(%)", "S-1(%)", "S-2(%)", "S-3(%)", "S-4(%)"],
          rows, [13, 14, 14, 12, 14, 9, 9, 9, 9], {"A": "yyyy-mm-dd"})

    # 관리기준
    rows = [(c, k, n, u, lo, hi) for c, k, n, u, lo, hi, _v, _n in PARAMS if lo is not None or hi is not None]
    rows += EXTRA_LIMITS
    sheet(wb, "관리기준", ["설비코드", "항목코드", "항목명", "단위", "하한", "상한"], rows, [11, 11, 22, 9, 10, 10])

    for w in wb.worksheets[1:]:
        w.sheet_properties.tabColor = BLUE
    wb.save(OUT)
    print(f"생성: {OUT}")


if __name__ == "__main__":
    main()
