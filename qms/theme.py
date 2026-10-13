"""사내 포털 느낌의 화면 테마(상단 메뉴·남색 제목 띠·카드·탭 머리글). 기능과 계산에는 영향이 없다."""

from __future__ import annotations

import streamlit as st

NAVY, BLUE, BLUE2, CYAN, TEAL, BG, LINE, INK, MUTED = (
    "#353a51", "#0b4a8f", "#3b71ab", "#00aed4", "#5ec3ad", "#edf2fa", "#e3e8f2", "#2b2f3a", "#7a8194")

THEME_CSS = f"""<style>
:root {{ --q-navy:{NAVY}; --q-blue:{BLUE}; --q-blue2:{BLUE2}; --q-cyan:{CYAN}; --q-teal:{TEAL}; --q-bg:{BG}; --q-line:{LINE};
  --q-ink:{INK}; --q-muted:{MUTED}; --q-pad:3rem; --q-shadow:0 4px 14px rgba(40,60,110,.09); }}
.stApp {{ background: var(--q-bg); }}

/* 상단 메뉴(헤더) */
[data-testid="stHeader"] {{ background:#fff; border-bottom:1px solid var(--q-line); box-shadow:none; }}
[data-testid="stHeader"] a, [data-testid="stHeader"] button {{ font-weight:600; }}

/* 본문 폭·여백: 제목 띠가 화면 끝까지 닿도록 좌우 여백을 변수로 관리 */
[data-testid="stMainBlockContainer"] {{ max-width:100% !important; padding:3.75rem var(--q-pad) 3rem !important; }}
.st-key-qms_hero {{ background:var(--q-navy); color:#fff; margin:0 calc(-1 * var(--q-pad)) 1.2rem; width:calc(100% + 2 * var(--q-pad)) !important; max-width:none !important; padding:1.1rem var(--q-pad) 1.5rem; }}
.st-key-qms_hero * {{ color:#fff; }}
.st-key-qms_hero h1 {{ font-size:2rem; font-weight:800; padding:.15rem 0 .2rem; margin:0; }}
.st-key-qms_hero [data-testid="stCaptionContainer"] * {{ color:rgba(255,255,255,.78) !important; }}
.qms-today {{ font-size:.82rem; letter-spacing:.02rem; margin-top:.4rem; }}
.qms-today:before {{ content:""; display:inline-block; width:.5rem; height:.5rem; border:2px solid var(--q-cyan); border-radius:50%; margin-right:.5rem; }}
/* 제목 띠 안의 도구 버튼 */
.st-key-qms_hero button {{ background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.35); border-radius:20px; }}
.st-key-qms_hero button:hover {{ background:rgba(255,255,255,.22); }}

/* 카드: 테두리 컨테이너·숫자 카드·펼침 영역 */
[data-testid="stVerticalBlockBorderWrapper"]:has(> [data-testid="stVerticalBlock"]) {{ border-radius:14px; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:var(--q-line); background:#fff; border-radius:14px; box-shadow:var(--q-shadow); }}
.st-key-qms_hero div[data-testid="stVerticalBlockBorderWrapper"] {{ background:transparent; box-shadow:none; border:0; }}
[data-testid="stMetric"] {{ background:#fff; border:1px solid var(--q-line); border-left:5px solid var(--q-blue2); border-radius:14px;
  padding:.8rem 1rem; box-shadow:var(--q-shadow); }}
[data-testid="stMetricLabel"] {{ color:var(--q-muted); }}
[data-testid="stExpander"] {{ background:#fff; border:1px solid var(--q-line); border-radius:14px; box-shadow:var(--q-shadow); }}
[data-testid="stExpander"] details {{ border:0; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ border-radius:10px; overflow:hidden; }}
.stAlert {{ border-radius:12px; }}

/* 탭 = 카드 머리글(파란 띠 + 흰 선택 탭), 탭 내용 = 흰 카드 */
[role="tablist"] {{ background:var(--q-blue); border-radius:14px 14px 0 0; padding:.45rem .5rem 0 !important; gap:.15rem; border:0 !important; }}
[data-orientation="horizontal"]:has(> [role="tablist"]) {{ border:0 !important; box-shadow:none !important; }}
[data-testid="stTab"] {{ color:rgba(255,255,255,.9) !important; border-radius:10px 10px 0 0; padding:.55rem 1.1rem !important; margin:0 !important; background:transparent; }}
[data-testid="stTab"] p, [data-testid="stTab"] * {{ color:inherit !important; font-weight:700; }}
[data-testid="stTab"][data-selected="true"], [data-testid="stTab"][aria-selected="true"] {{ background:#fff !important; color:var(--q-blue) !important; }}
[data-testid="stTab"] .react-aria-SelectionIndicator, [role="tablist"] .react-aria-SelectionIndicator {{ display:none !important; }}
[data-testid="stTabPanel"] {{ background:#fff; border-radius:0 0 14px 14px; padding:1.1rem 1.3rem 1.3rem !important; box-shadow:var(--q-shadow); }}

/* 버튼 */
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{ background:var(--q-blue); border-color:var(--q-blue); }}
.stButton > button[kind="primary"]:disabled {{ background:#9fb3cc; border-color:#9fb3cc; color:#fff; opacity:.8; }}

@media (max-width: 1100px) {{ :root {{ --q-pad:1.2rem; }} .st-key-qms_hero h1 {{ font-size:1.55rem; }} }}
</style>"""


def apply_theme() -> None:
    """매 실행마다 호출(streamlit_app.py)."""
    st.html(THEME_CSS)
