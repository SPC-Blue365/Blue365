"""Blue365 통합 품질관리 시스템(QMS) — Streamlit 진입점.

실행:  streamlit run streamlit_app.py
"""

from pathlib import Path

import streamlit as st

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

pages = [
    st.Page("app_pages/overview.py", title="종합 현황", icon="🏠", default=True),
    st.Page("app_pages/shipment.py", title="출하시멘트", icon="🚢"),
    st.Page("app_pages/monitor.py", title="공정 모니터링", icon="📈"),
    st.Page("app_pages/spc.py", title="SPC", icon="📊"),
    st.Page("app_pages/alerts.py", title="알림 센터", icon="🚨"),
    st.Page("app_pages/diagnosis.py", title="원인 진단", icon="🧪"),
    st.Page("app_pages/prediction.py", title="강도 예측", icon="🔮"),
    st.Page("app_pages/rawmix.py", title="배합 설계", icon="⚗️"),
    st.Page("app_pages/chromium.py", title="6가크롬", icon="☢️"),
    st.Page("app_pages/calculator.py", title="화학 계산기", icon="🧮"),
    st.Page("app_pages/reports.py", title="보고서", icon="📑"),
    st.Page("app_pages/data.py", title="데이터 관리", icon="📥"),
    st.Page("app_pages/lims.py", title="LIMS", icon="🔗"),
    st.Page("app_pages/settings.py", title="설정", icon="⚙️"),
]

st.navigation(pages, position="top").run()
