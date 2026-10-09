"""Blue365 통합 품질관리 시스템(QMS) — Streamlit 진입점.

실행:  streamlit run streamlit_app.py
"""

import streamlit as st

from qms.access import check_access
from qms.ui import enable_tilde_escape

st.set_page_config(page_title="Blue365 QMS", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
enable_tilde_escape()   # '8~20%' 같은 범위 표기가 마크다운 취소선으로 바뀌지 않게 처리
if not check_access():  # 공유 실행용 접속 비밀번호(설정한 경우에만)
    st.stop()

pages = {
    "모니터링": [
        st.Page("app_pages/overview.py", title="종합 현황", icon="🏠", default=True),
        st.Page("app_pages/monitor.py", title="공정 모니터링", icon="📈"),
        st.Page("app_pages/spc.py", title="SPC·공정능력", icon="📊"),
    ],
    "알림·분석": [
        st.Page("app_pages/alerts.py", title="알림 센터", icon="🚨"),
        st.Page("app_pages/diagnosis.py", title="원인 진단·솔루션", icon="🧪"),
        st.Page("app_pages/prediction.py", title="28일 강도 예측", icon="🔮"),
    ],
    "배합·품질설계": [
        st.Page("app_pages/rawmix.py", title="원료 배합·클링커 설계", icon="🧪"),
        st.Page("app_pages/chromium.py", title="시멘트 6가크롬", icon="☢️"),
    ],
    "도구·설정": [
        st.Page("app_pages/calculator.py", title="화학 계산기", icon="🧮"),
        st.Page("app_pages/reports.py", title="보고서", icon="📑"),
        st.Page("app_pages/data.py", title="데이터 관리", icon="📥"),
        st.Page("app_pages/lims.py", title="LIMS 연동", icon="🔗"),
        st.Page("app_pages/settings.py", title="기준·알림 설정", icon="⚙️"),
    ],
}

st.navigation(pages).run()
