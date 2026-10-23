"""Blue365 통합 품질관리 시스템(QMS) — Streamlit 진입점.

실행:  streamlit run streamlit_app.py
"""

from pathlib import Path

import streamlit as st

from qms import labels as L
from qms.access import check_access
from qms.theme import apply_theme
from qms.ui import apply_responsive_css, enable_tilde_escape, enable_touch_charts

APP_DIR = Path(__file__).resolve().parent

# 상단 메뉴 구조(왼쪽 사이드바는 쓰지 않음)
ICON = APP_DIR / "assets" / "icon.png"
st.set_page_config(page_title="Blue365 QMS", page_icon=str(ICON) if ICON.exists() else "🏭", layout="wide",
                   initial_sidebar_state="collapsed")
try:                                    # 상단 메뉴 왼쪽 로고(그림을 못 읽어도 프로그램은 계속 실행)
    st.logo(str(APP_DIR / "assets" / "logo.png"), size="large")
except Exception:  # noqa: BLE001
    pass
enable_tilde_escape()   # '8~20%' 같은 범위 표기가 마크다운 취소선으로 바뀌지 않게 처리
enable_touch_charts()   # 태블릿 보기: 그래프 위에서도 손가락 스크롤
apply_responsive_css()  # 태블릿·좁은 창: 숫자 카드 잘림·그래프 비좁음 방지
apply_theme()           # 사내 포털 느낌의 화면 테마(상단 메뉴·제목 띠·카드·탭 머리글)
if not check_access():  # 공유 실행용 접속 비밀번호(설정한 경우에만)
    st.stop()

LABELS = L.load_labels()   # 사용자가 바꾼 메뉴·제목·항목 이름(설정 → 용어·제목)
L.apply_shipment(LABELS)
pages = [
    st.Page("app_pages/overview.py", title=L.menu("종합 현황", LABELS), icon="🏠", default=True),
    st.Page("app_pages/shipment.py", title=L.menu("출하시멘트", LABELS), icon="🚢"),
    st.Page("app_pages/incoming.py", title=L.menu("인수검사", LABELS), icon="📦"),
    st.Page("app_pages/charts.py", title=L.menu("그래프 보기", LABELS), icon="📉"),
    st.Page("app_pages/monitor.py", title=L.menu("공정 모니터링", LABELS), icon="📈"),
    st.Page("app_pages/spc.py", title=L.menu("SPC", LABELS), icon="📊"),
    st.Page("app_pages/alerts.py", title=L.menu("알림 센터", LABELS), icon="🚨"),
    st.Page("app_pages/diagnosis.py", title=L.menu("원인 진단", LABELS), icon="🧪"),
    st.Page("app_pages/prediction.py", title=L.menu("강도 예측", LABELS), icon="🔮"),
    st.Page("app_pages/rawmix.py", title=L.menu("배합 설계", LABELS), icon="⚗️"),
    st.Page("app_pages/chromium.py", title=L.menu("6가크롬", LABELS), icon="☢️"),
    st.Page("app_pages/calculator.py", title=L.menu("화학 계산기", LABELS), icon="🧮"),
    st.Page("app_pages/reports.py", title=L.menu("보고서", LABELS), icon="📑"),
    st.Page("app_pages/data.py", title=L.menu("데이터 관리", LABELS), icon="📥"),
    st.Page("app_pages/lims.py", title=L.menu("LIMS", LABELS), icon="🔗"),
    st.Page("app_pages/settings.py", title=L.menu("설정", LABELS), icon="⚙️"),
]

st.navigation(pages, position="top").run()
