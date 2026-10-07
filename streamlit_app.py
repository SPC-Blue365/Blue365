"""Blue365 통합 품질관리 시스템(QMS) — Streamlit 진입점.

실행:  streamlit run streamlit_app.py
"""

import streamlit as st

st.set_page_config(page_title="Blue365 QMS", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")

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
    "도구·설정": [
        st.Page("app_pages/calculator.py", title="화학 계산기", icon="🧮"),
        st.Page("app_pages/reports.py", title="보고서", icon="📑"),
        st.Page("app_pages/data.py", title="데이터 관리", icon="📥"),
        st.Page("app_pages/settings.py", title="기준·알림 설정", icon="⚙️"),
    ],
}

st.navigation(pages).run()
