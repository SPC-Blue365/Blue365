"""Blue365 UI 스타일 화면 테마(밝은 바탕·흰 카드·파란 강조·밑줄 탭). 기능과 계산에는 영향이 없다. 기준: docs/UI_디자인_가이드.md"""

from __future__ import annotations

import streamlit as st

# Blue365 UI 스타일(docs/UI_디자인_가이드.md): 회색 바탕 + 흰 카드(둥근 20px) + 파란 강조 한 색 + 밑줄 탭 + 알약 꼬리표.
INK, INK2, MUTED, FAINT, LINE, BG, WELL, BLUE, BLUE_SOFT, BLUE_INK = (
    "#191f28", "#333d4b", "#6b7684", "#8b95a1", "#e5e8eb", "#f2f4f6", "#f7f8fa", "#3182f6", "#e8f3ff", "#1b64da")

THEME_CSS = f"""<style>
:root {{ --q-ink:{INK}; --q-ink2:{INK2}; --q-muted:{MUTED}; --q-faint:{FAINT}; --q-line:{LINE}; --q-bg:{BG}; --q-well:{WELL};
  --q-blue:{BLUE}; --q-blue-soft:{BLUE_SOFT}; --q-blue-ink:{BLUE_INK}; --q-pad:3rem;
  --q-shadow:0 1px 2px rgba(0,0,0,.03), 0 6px 20px rgba(0,0,0,.045); --q-glow:0 0 0 4px rgba(49,130,246,.14); --q-r:20px;
  --q-ok:#0ca30c; --q-warn:#fab219; --q-serious:#ec835a; --q-bad:#d03b3b; --q-ok-bg:#e8f7ec; --q-warn-bg:#fff4d9; --q-bad-bg:#fdecec; }}
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
.qms-tag.demo {{ background:#fff4d9; color:var(--q-ink2); }}
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
/* 세그먼트(st.segmented_control) = 회색 틀 + 고른 것만 흰 바탕 / 칩(st.pills) = 둥근 알약 + 선택 시 옅은 파랑·✓ */
[data-testid="stButtonGroup"] [role="radiogroup"]:has(> button[data-variant="segmented_control"]) {{ display:inline-flex; background:var(--q-line); padding:3px; border-radius:12px; gap:2px; }}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {{ border:0 !important; background:transparent !important; border-radius:9px !important; padding:4px 14px !important; min-height:32px; margin:0 !important; color:var(--q-muted) !important; box-shadow:none !important; }}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] p {{ font-weight:600; }}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"] {{ background:#fff !important; color:var(--q-ink) !important; box-shadow:0 1px 3px rgba(0,0,0,.12) !important; }}
[data-testid="stButtonGroup"] button[data-variant="pills"] {{ border-radius:999px !important; font-weight:600; border-color:var(--q-line) !important; background:#fff; }}
[data-testid="stButtonGroup"] button[data-variant="pills"][aria-checked="true"], [data-testid="stButtonGroup"] button[data-variant="pills"][aria-pressed="true"] {{ background:var(--q-blue-soft) !important; color:var(--q-blue-ink) !important; border-color:var(--q-blue) !important; }}
[data-testid="stButtonGroup"] button[data-variant="pills"][aria-checked="true"] p::before, [data-testid="stButtonGroup"] button[data-variant="pills"][aria-pressed="true"] p::before {{ content:"✓ "; font-weight:800; }}

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


# 보는용 현황판(qms/viewer_template.html)과 같은 부품 모양 — qms/uikit.py 가 이 클래스로 HTML 을 만든다.
KIT_CSS = """<style>
/* 테두리 컨테이너(st.container(border=True)) = 흰 카드 — qms.ui 가 자동으로 qms_card_N 키를 붙인다 */
[class*="st-key-qms_card_"] { background:#fff; border:0 !important; border-radius:var(--q-r) !important; box-shadow:var(--q-shadow);
  padding:1.1rem 1.25rem !important; }
/* 숫자 카드(st.metric) = 위 회색 미리보기(값) + 아래 '01 제목' */
[data-testid="stMetric"] { padding:12px !important; }
[data-testid="stMetric"] > div { display:flex; flex-direction:column; }
[data-testid="stMetricValue"] { order:1; background:var(--q-well); border-radius:14px; padding:22px 16px; font-size:1.9rem !important; font-weight:800; }
[data-testid="stMetric"] > div:has([data-testid="stMetricDelta"]) [data-testid="stMetricValue"] { border-radius:14px 14px 0 0; padding-bottom:6px; }
[data-testid="stMetric"] > div > :not(label):not([data-testid="stMetricValue"]) { order:2; background:var(--q-well); border-radius:0 0 14px 14px; padding:0 16px 16px; margin:0 !important; }
[data-testid="stMetricDelta"] { margin:0 !important; }
[data-testid="stMetricLabel"] { order:3; padding:12px 6px 2px; }
[data-testid="stMetricLabel"] p { font-size:15px !important; font-weight:800 !important; color:var(--q-ink) !important; }
[data-testid="stMetricLabel"] p::before { color:var(--q-blue); font-weight:800; font-size:14px; }
/* 번호(01, 02 …)는 칸 순서로 — 숫자 카드 칸은 크기 기준(container)이라 CSS 카운터가 칸 밖으로 이어지지 않음 */
[data-testid="stColumn"]:nth-child(1) [data-testid="stMetricLabel"] p::before { content:"01\\00a0"; }
[data-testid="stColumn"]:nth-child(2) [data-testid="stMetricLabel"] p::before { content:"02\\00a0"; }
[data-testid="stColumn"]:nth-child(3) [data-testid="stMetricLabel"] p::before { content:"03\\00a0"; }
[data-testid="stColumn"]:nth-child(4) [data-testid="stMetricLabel"] p::before { content:"04\\00a0"; }
[data-testid="stColumn"]:nth-child(5) [data-testid="stMetricLabel"] p::before { content:"05\\00a0"; }
[data-testid="stColumn"]:nth-child(6) [data-testid="stMetricLabel"] p::before { content:"06\\00a0"; }
[data-testid="stColumn"]:nth-child(7) [data-testid="stMetricLabel"] p::before { content:"07\\00a0"; }
[data-testid="stColumn"]:nth-child(8) [data-testid="stMetricLabel"] p::before { content:"08\\00a0"; }

/* 가로 라디오 = 세그먼트(회색 틀 안에서 고른 것만 흰 바탕) */
[data-testid="stRadio"] div[role="radiogroup"]:has(> label + label) { display:inline-flex !important; flex-wrap:wrap; background:var(--q-line); padding:3px; border-radius:12px; gap:2px !important; }
[data-testid="stRadio"] div[role="radiogroup"]:has(> label + label) > label { margin:0 !important; padding:6px 14px; border-radius:9px; }
[data-testid="stRadio"] div[role="radiogroup"]:has(> label + label) > label > div:first-child { display:none; }
[data-testid="stRadio"] div[role="radiogroup"]:has(> label + label) > label:has(input:checked) { background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.12); }
[data-testid="stRadio"] div[role="radiogroup"]:has(> label + label) > label p { font-weight:600; }

/* 알림 목록 한 줄(qms_li_N): 리스트 행 + 오른쪽 '진단 ›' */
[class*="st-key-qms_li_"] { border-bottom:1px solid var(--q-line); padding:4px 0 10px; }
[class*="st-key-qms_li_"]:last-child { border-bottom:0; }
[class*="st-key-qms_li_"] button { border:0 !important; background:var(--q-blue-soft) !important; color:var(--q-blue-ink) !important; border-radius:999px !important; }

/* st.info / st.warning = 배너 */
.stAlert > div { border-radius:14px; }
[data-testid="stAlertContentInfo"] { color:var(--q-ink2); }

/* ── .qk 부품 ── */
.qk { font-variant-numeric:tabular-nums; color:var(--q-ink); }
.qk .qk-hl { font-size:clamp(28px,3.4vw,40px); font-weight:800; letter-spacing:-.025em; line-height:1.25; margin:.5rem 0 0; padding:0; color:var(--q-ink); }
.qk .qk-hl em { font-style:normal; color:var(--q-blue); }
.qk .qk-lead { color:var(--q-muted); font-size:14.5px; margin:.45rem 0 0; }
.qk .qk-sec { font-size:18px; font-weight:800; letter-spacing:-.01em; margin:.6rem 0 0; padding:0; display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
.qk .qk-sec small { font-size:13px; font-weight:500; color:var(--q-muted); }
.qk .qk-h3 { font-size:16px; font-weight:800; margin:0 0 10px; padding:0; }
.qk .grid { display:grid; gap:14px; }
.qk .g-auto { grid-template-columns:repeat(auto-fill, minmax(min(100%, 240px), 1fr)); }
.qk .g-stage { grid-template-columns:repeat(auto-fit, minmax(min(100%, 210px), 1fr)); }
.qk .card { background:#fff; border-radius:var(--q-r); padding:12px; box-shadow:var(--q-shadow); min-width:0; animation:qrise .34s cubic-bezier(.2,.8,.2,1) both; animation-delay:calc(var(--i,0) * 35ms); }
.qk .well { background:var(--q-well); border-radius:14px; padding:16px; min-height:112px; display:grid; align-content:center; gap:4px; position:relative; }
.qk .cap { padding:12px 6px 4px; }
.qk .cap .t { font-size:16px; font-weight:800; letter-spacing:-.01em; display:flex; gap:6px; align-items:baseline; flex-wrap:wrap; }
.qk .no { color:var(--q-blue); font-weight:800; font-size:14px; }
.qk .cap small { display:block; color:var(--q-faint); font-size:13px; margin-top:2px; }
.qk .big { font-size:30px; font-weight:800; letter-spacing:-.02em; line-height:1.15; }
.qk .big span { font-size:15px; font-weight:700; color:var(--q-muted); margin-left:3px; }
.qk .corner { position:absolute; top:12px; right:12px; }
.qk .note { font-size:13px; color:var(--q-muted); margin:0; }
.qk .pill, .pill { display:inline-flex; align-items:center; gap:5px; height:24px; padding:0 10px; border-radius:999px; font-size:12.5px; font-weight:700; white-space:nowrap; color:var(--q-ink2); vertical-align:middle; }
.pill::before { content:""; width:7px; height:7px; border-radius:50%; }
.pill.ok { background:var(--q-ok-bg); } .pill.ok::before { background:var(--q-ok); }
.pill.warn { background:var(--q-warn-bg); } .pill.warn::before { background:var(--q-warn); }
.pill.bad { background:var(--q-bad-bg); } .pill.bad::before { background:var(--q-bad); }
.pill.mute { background:var(--q-bg); } .pill.mute::before { background:var(--q-faint); }
.qk .items { display:grid; gap:3px; font-size:13.5px; }
.qk .items div { display:flex; gap:6px; align-items:baseline; }
.qk .items i { flex:none; width:7px; height:7px; border-radius:50%; transform:translateY(-1px); }
.qk .items b { font-weight:700; }
.qk .ring { display:grid; place-items:center; position:relative; width:92px; height:92px; margin:0 auto; }
.qk .ring svg { position:absolute; inset:0; transform:rotate(-90deg); }
.qk .ring b { font-size:21px; font-weight:800; }
.qk .pbar { height:8px; border-radius:999px; background:var(--q-line); overflow:hidden; }
.qk .pbar > i { display:block; height:100%; border-radius:999px; background:var(--q-blue); }
.qk .sum { display:grid; grid-template-columns:auto minmax(0,1fr); gap:18px; align-items:center; }
.qk .sum .tot { text-align:center; } .qk .sum .tot .big { font-size:40px; } .qk .sum .tot small { color:var(--q-muted); font-size:12.5px; display:block; }
.qk .sum .rows { display:grid; gap:7px; }
.qk .sum .r { display:grid; grid-template-columns:34px minmax(0,1fr) 30px; gap:8px; align-items:center; font-size:13px; color:var(--q-muted); }
.qk .sum .r .n { color:var(--q-ink2); font-weight:700; text-align:right; }
.qk .banner { display:flex; gap:10px; align-items:flex-start; background:var(--q-blue-soft); color:var(--q-ink2); border-radius:14px; padding:11px 14px; font-size:14px; }
.qk .banner.warn { background:var(--q-warn-bg); }
.qk .banner .ic { flex:none; width:20px; height:20px; border-radius:50%; background:var(--q-blue); color:#fff; display:grid; place-items:center; font-size:12px; font-weight:800; margin-top:1px; }
.qk .banner.warn .ic { background:var(--q-warn); color:#1d1d1d; }
.qk .banner p { margin:0; }
.qk .banner em { font-style:normal; font-weight:700; }
.qk .empty { display:grid; place-items:center; text-align:center; gap:6px; color:var(--q-muted); background:var(--q-well); border-radius:14px; padding:24px 16px; font-size:14px; }
.li-t b { font-weight:700; } .li-t small { display:block; color:var(--q-muted); font-size:13px; margin-top:2px; }
@media (prefers-reduced-motion: reduce) { .qk .card, [data-testid="stMetric"] { animation:none !important; } }
</style>"""


def apply_theme() -> None:
    """매 실행마다 호출(streamlit_app.py)."""
    st.html(THEME_CSS + KIT_CSS)
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
