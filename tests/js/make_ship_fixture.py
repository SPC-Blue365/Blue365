"""e2e_ship.js 용 합성 출하시멘트 엑셀(실제 LIMS 내보내기와 같은 열 구조, 값은 난수). 사용: python make_ship_fixture.py <출력.xlsx>"""
import datetime as dt
import random
import sys

import openpyxl

H = ["", "전송", "ERP LOT.NO", "LIMS LOT.NO", "검사일", "채취일", "품명", "공정구분", "분석방법", "첨가재명칭", "석회석비율", "석회석CO2", "석회석품위", "첨가재비율", "LOI", "SiO2", "Al2O3", "Fe2O3", "CaO", "MgO",
     "SO3(XRF)", "SO3(C/S)", "Na2O", "K2O", "Cl(XRF)", "Cl(습식)", "F-CaO(XRF)", "F-CaO(습식)", "P2O5(XRF)", "TA", "압축강도1일(MPa)", "압축강도3일(MPa)", "압축강도7일(MPa)", "압축강도28일(MPa)",
     "밀도", "45㎛", "Blaine", "주도", "Flow", "간이Flow", "초결시간(분)", "종결시간(HH:MM)", "담당자", "비고"]
random.seed(7)
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sheet1"; ws.append(H)
SHIPS = ["수성1호", "수성3호", "리나호", "삼표1호", "삼표5호", "정진호"]
d0 = dt.date(2025, 10, 1)
for i in range(200):
    d = d0 + dt.timedelta(days=i)
    ships = random.sample(SHIPS, random.choice([1, 1, 2, 3]))
    note = ",".join(ships) + random.choice(["", ",", ".", "         ."])
    pending = i >= 195          # 최근 며칠은 강도 미시험(0)
    r = [i + 1, None, f"QC{i:06d}", str(15000000 + i), d.isoformat(), (d - dt.timedelta(days=1)).isoformat(), "1종시멘트 벌크", "P3", "Powder",
         "플라이 애시" if i < 120 else "고로슬래그", 5 if i % 40 < 30 else 3, 37.0, 84.0, 5, round(random.gauss(2.5, .3), 2), 21.2, round(random.gauss(5.8, .25), 2), 3.4, 58.0,
         round(random.gauss(3.9, .35), 2), round(random.gauss(2.6, .08), 2), 0, 0.22, 0.95, random.randint(300, 700), 0, 0, 0, .26, round(random.gauss(.85, .04), 2),
         round(random.gauss(16, 1), 1), round(random.gauss(36, 1.5), 1), 0 if pending else round(random.gauss(46, 1.7), 1), 0 if pending else round(random.gauss(55, 2), 1),
         0, round(random.gauss(7, .7), 1), round(random.gauss(3780, 100)), round(random.gauss(27.3, .3), 1), random.randint(88, 104), 0, str(random.randint(220, 280)),
         f"{random.randint(5, 6):02d}:{random.randint(0, 59):02d}", "", note]
    ws.append(r)
wb.save(sys.argv[1] if len(sys.argv) > 1 else "ship_fixture.xlsx")
print("saved")
