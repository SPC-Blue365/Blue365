"""Blue365 UI 스타일 화면 테마(밝은 바탕·흰 카드·파란 강조·밑줄 탭). 기능과 계산에는 영향이 없다. 기준: docs/UI_디자인_가이드.md"""

from __future__ import annotations

import streamlit as st

# Blue365 UI 스타일(docs/UI_디자인_가이드.md): 회색 바탕 + 흰 카드(둥근 20px) + 파란 강조 한 색 + 밑줄 탭 + 알약 꼬리표.
INK, INK2, MUTED, FAINT, LINE, BG, WELL, BLUE, BLUE_SOFT, BLUE_INK = (
    "#191f28", "#333d4b", "#6b7684", "#8b95a1", "#e5e8eb", "#f2f4f6", "#f7f8fa", "#3182f6", "#e8f3ff", "#1b64da")

THEME_CSS = f"""<style>
:root {{ --q-ink:{INK}; --q-ink2:{INK2}; --q-muted:{MUTED}; --q-faint:{FAINT}; --q-line:{LINE}; --q-bg:{BG}; --q-well:{WELL};
  --q-blue:{BLUE}; --q-blue-soft:{BLUE_SOFT}; --q-blue-ink:{BLUE_INK}; --q-pad:3rem;
  --q-shadow:0 1px 2px rgba(0,0,0,.03), 0 6px 20px rgba(0,0,0,.045); --q-glow:0 0 0 4px rgba(49,130,246,.14); --q-r:20px; }}
.stApp {{ background: var(--q-bg); }}
html, body, .stApp, button, input, textarea {{ font-family: "Pretendard", "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif; }}
.stApp {{ font-variant-numeric: tabular-nums; }}

/* 상단 메뉴(고정 헤더): 반투명 + 흐림, 선택 메뉴는 진하게 */
[data-testid="stHeader"] {{ background:color-mix(in srgb, var(--q-bg) 86%, transparent); backdrop-filter:saturate(1.4) blur(12px);
  border-bottom:1px solid var(--q-line); box-shadow:none; }}
[data-testid="stHeader"] a, [data-testid="stHeader"] button {{ font-weight:700; }}
/* 메뉴 15개가 넓은 화면(1600px 이상)에서 한 줄에 다 보이도록 간격을 줄이고, 넘치면 영어 'N more' 대신 '더보기' */
[data-testid="stTopNavLink"] {{ padding:0 4px !important; }}
[data-testid="stTopNavLink"] p, [data-testid="stTopNavLink"] span {{ font-size:13.5px; }}
[data-testid="stHeader"] .rc-overflow {{ gap:0 !important; }}
[data-testid="stHeader"] .rc-overflow-item-rest [data-testid="stTopNavSection"] p {{ font-size:0 !important; }}
[data-testid="stHeader"] .rc-overflow-item-rest [data-testid="stTopNavSection"] p::after {{ content:"더보기"; font-size:14px; }}

/* 본문 폭·여백 */
[data-testid="stMainBlockContainer"] {{ max-width:1480px !important; margin-left:auto !important; margin-right:auto !important; padding:3.75rem var(--q-pad) 3rem !important; }}

/* 화면 머리: 알약 꼬리표 + 큰 제목(어두운 띠 대신 밝은 바탕) */
.st-key-qms_hero {{ padding:.6rem 0 .4rem; margin-bottom:.6rem; }}
.st-key-qms_hero h1 {{ font-size:2.35rem; font-weight:800; letter-spacing:-.025em; color:var(--q-ink); padding:.35rem 0 .15rem; margin:0; }}
.st-key-qms_hero [data-testid="stCaptionContainer"] * {{ color:var(--q-muted) !important; }}
.qms-today {{ display:flex; flex-wrap:wrap; gap:.4rem; align-items:center; margin-top:.4rem; font-size:.8rem; color:var(--q-muted); }}
.qms-tag {{ display:inline-flex; align-items:center; height:26px; padding:0 11px; border-radius:999px; background:var(--q-blue-soft); color:var(--q-blue-ink); font-weight:700; font-size:12.5px; }}
.qms-tag.gray {{ background:#e9ecef; color:var(--q-ink2); }}
.st-key-qms_hero button {{ background:#fff; border:1px solid var(--q-line); border-radius:12px; font-weight:600; }}
.st-key-qms_hero button:hover {{ background:var(--q-well); border-color:var(--q-line); }}

/* 카드: 흰 바탕 · 둥근 20px · 옅은 그림자(테두리 컨테이너·숫자 카드·펼침 영역) */
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:transparent; background:#fff; border-radius:var(--q-r); box-shadow:var(--q-shadow); }}
.st-key-qms_hero div[data-testid="stVerticalBlockBorderWrapper"] {{ background:transparent; box-shadow:none; border:0; }}
[data-testid="stMetric"] {{ background:#fff; border:0; border-radius:var(--q-r); padding:1rem 1.1rem; box-shadow:var(--q-shadow); }}
[data-testid="stMetricLabel"] {{ color:var(--q-muted); }}
[data-testid="stMetricLabel"] p {{ font-weight:700; }}
[data-testid="stMetricValue"] {{ font-weight:800; letter-spacing:-.02em; color:var(--q-ink); }}
[data-testid="stExpander"] {{ background:#fff; border:0; border-radius:var(--q-r); box-shadow:var(--q-shadow); }}
[data-testid="stExpander"] details {{ border:0; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ border-radius:14px; overflow:hidden; }}
.stAlert {{ border-radius:14px; border:0; }}
h2, h3 {{ letter-spacing:-.015em; font-weight:800 !important; }}

/* 탭 = 밑줄 탭(선택 탭만 진하게 + 밑줄), 탭 내용 = 흰 카드 */
[role="tablist"] {{ background:transparent; padding:0 !important; gap:1.4rem; border-bottom:1px solid var(--q-line) !important; }}
[data-testid="stTab"] {{ color:var(--q-faint) !important; padding:.55rem 0 .7rem !important; margin:0 !important; background:transparent; border-radius:0; }}
[data-testid="stTab"] p, [data-testid="stTab"] * {{ color:inherit !important; font-weight:700; font-size:15px; }}
[data-testid="stTab"][aria-selected="true"] {{ color:var(--q-ink) !important; box-shadow:inset 0 -2.5px 0 var(--q-ink); }}
[data-testid="stTab"] .react-aria-SelectionIndicator, [role="tablist"] .react-aria-SelectionIndicator {{ display:none !important; }}
[data-testid="stTabPanel"] {{ background:#fff; border-radius:var(--q-r); margin-top:.8rem; padding:1.2rem 1.4rem 1.4rem !important; box-shadow:var(--q-shadow); }}

/* 버튼: 주 버튼 = 파랑 꽉 찬 둥근 버튼, 보조 = 흰 바탕 */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{ border-radius:12px; font-weight:700; }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{ background:var(--q-blue); border-color:var(--q-blue); }}
.stButton > button[kind="primary"]:hover {{ background:var(--q-blue-ink); border-color:var(--q-blue-ink); }}
.stButton > button[kind="primary"]:disabled {{ background:#b9d4fb; border-color:#b9d4fb; color:#fff; opacity:.9; }}

/* 입력 칸: 둥근 12px · 선택 시 파란 테두리 + 옅은 빛 */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{ border-radius:12px !important; }}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {{ box-shadow:var(--q-glow); }}

/* 가로 라디오 = 세그먼트 모양(짧은 선택지 하나 고르기) */
[data-testid="stRadio"] [role="radiogroup"][aria-orientation="horizontal"], [data-testid="stRadio"] div[role="radiogroup"]:has(> label:nth-child(2)) {{ gap:.25rem; }}
/* 칩(st.pills)·세그먼트(st.segmented_control) 선택 상태 */
[data-testid="stButtonGroup"] button {{ border-radius:999px; font-weight:600; }}
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[kind$="Active"] {{ background:var(--q-blue-soft); color:var(--q-blue-ink); border-color:var(--q-blue); }}

/* 토스트: 어두운 알약 */
[data-testid="stToast"] {{ border-radius:999px; background:#191f28; color:#fff; }}
[data-testid="stToast"] * {{ color:#fff !important; }}

@media (max-width: 1100px) {{ :root {{ --q-pad:1.2rem; }} .st-key-qms_hero h1 {{ font-size:1.8rem; }} }}
@media (prefers-reduced-motion: no-preference) {{
  [data-testid="stMetric"], div[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stTabPanel"] {{ animation:qrise .3s cubic-bezier(.2,.8,.2,1) both; }}
}}
@keyframes qrise {{ from {{ opacity:0; transform:translateY(8px); }} to {{ opacity:1; transform:none; }} }}
.st-key-qms_notranslate {{ display:none !important; }}
</style>"""


def apply_theme() -> None:
    """매 실행마다 호출(streamlit_app.py)."""
    st.html(THEME_CSS)
    _no_translate()


@st.cache_resource(show_spinner=False)
def _patch_index_once() -> str:
    from . import notranslate
    try:
        return notranslate.ensure()
    except Exception:  # noqa: BLE001 - 번역 차단은 보조 기능이라 실패해도 앱은 계속
        return "error"


def _no_translate() -> None:
    """브라우저 자동 번역(크롬·엣지) 때문에 한국어 메뉴·제목이 엉뚱하게 바뀌는 것을 막는다(qms/notranslate.py)."""
    from .notranslate import RUNTIME_JS
    _patch_index_once()                                  # 다음 접속부터: 시작 페이지 자체를 한국어·번역 금지로
    with st.container(key="qms_notranslate"):            # 지금 화면: 보이지 않는 칸에서 한국어·번역 금지 지정
        st.html(RUNTIME_JS, unsafe_allow_javascript=True)
