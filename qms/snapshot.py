"""HTML 현황판(조회 전용 스냅샷) — 설치·실행 권한이 없는 PC에서 브라우저로 보는 단일 HTML 파일.

매일 자동반영(qms_monitor --sync-file … --snapshot <폴더>) 직후 만들어 공유 드라이브에 둔다.
그래프 라이브러리(plotly.js)를 파일 안에 넣으므로 인터넷이 없어도 열린다(약 5MB).
내용: 요약 KPI · 핵심 공정 지표 · 28일 강도 · 출하시멘트(품종별 판정) · 인수검사 · 최근 알림.
"""

from __future__ import annotations

import html
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

LATEST_NAME = "Blue365_현황_최신.html"
ARCHIVE_DIR = "기록"
SEV_ICON = {"위험": "🔴", "경고": "🟠", "주의": "🟡"}

CSS = """
:root{--navy:#1f3a5f;--ink:#1c2430;--muted:#6b7686;--line:#dfe5ee;--bg:#f4f6fa;--card:#fff;
--red:#d03b3b;--orange:#e07b17;--yellow:#c9a000;--green:#2e8b57}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo","Noto Sans KR",sans-serif;font-size:14px}
.wrap{max-width:1280px;margin:0 auto;padding:0 16px 48px}
header{background:var(--navy);color:#fff;padding:22px 0 26px;margin-bottom:20px}
header .wrap{padding-bottom:0}header h1{margin:4px 0 6px;font-size:26px}
header .meta{color:rgba(255,255,255,.8);font-size:13px}
.stamp{display:inline-block;background:rgba(255,255,255,.15);border-radius:6px;padding:3px 10px;font-size:13px;margin-top:8px}
h2{font-size:19px;margin:30px 0 10px;padding-left:10px;border-left:4px solid var(--navy)}
h3{font-size:15px;margin:16px 0 6px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--navy);border-radius:10px;padding:12px 14px}
.card .l{color:var(--muted);font-size:12.5px}.card .v{font-size:24px;font-weight:700;margin-top:4px}
.card .s{color:var(--muted);font-size:12px;margin-top:2px}
.card.red{border-left-color:var(--red)}.card.orange{border-left-color:var(--orange)}.card.green{border-left-color:var(--green)}
.grid2{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:14px}
.grid2>*{min-width:0}
@media (max-width:600px){.grid2{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;overflow:hidden}
.tbl{width:100%;overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 9px;border-bottom:1px solid var(--line);
text-align:left;white-space:nowrap}th{background:#eef2f8;color:#3a4657;font-weight:600;position:sticky;top:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}tr:hover td{background:#f8fafd}
.note{color:var(--muted);font-size:12.5px;margin:6px 2px}
.empty{color:var(--muted);background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:14px}
footer{color:var(--muted);font-size:12px;margin-top:36px;border-top:1px solid var(--line);padding-top:12px}
"""


def _esc(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (pd.Timestamp, datetime)):
        return f"{v:%Y-%m-%d}" if getattr(v, "hour", 0) == 0 and getattr(v, "minute", 0) == 0 else f"{v:%Y-%m-%d %H:%M}"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.0f}"
    return html.escape(str(v))


def _table(df: pd.DataFrame, max_rows: int = 200) -> str:
    if df is None or df.empty:
        return '<div class="empty">자료가 없습니다.</div>'
    df = df.head(max_rows)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for v in r.tolist():
            cls = ' class="num"' if isinstance(v, (int, float)) and not isinstance(v, bool) else ""
            cells.append(f"<td{cls}>{_esc(v)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _card(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return (f'<div class="card {tone}"><div class="l">{html.escape(label)}</div><div class="v">{html.escape(value)}</div>'
            + (f'<div class="s">{html.escape(sub)}</div>' if sub else "") + "</div>")


class _FigWriter:
    """첫 그래프에만 plotly.js 를 넣고 나머지는 참조만 — 파일 크기 최소화."""

    def __init__(self):
        self.first = True

    def __call__(self, fig) -> str:
        if fig is None:
            return '<div class="empty">최근 자료가 없습니다.</div>'
        fig.update_layout(dragmode=False, autosize=True, margin=dict(l=60, r=24, b=48),
                          font=dict(family="Malgun Gothic, 맑은 고딕, Apple SD Gothic Neo, Noto Sans KR, sans-serif"))
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)
        out = fig.to_html(full_html=False, include_plotlyjs="inline" if self.first else False,
                          config={"displaylogo": False, "responsive": True, "scrollZoom": False,
                                  "modeBarButtonsToRemove": ["select2d", "lasso2d"]})
        self.first = False
        return f'<div class="panel">{out}</div>'


def load_context():
    """화면(ui.Ctx)과 같은 분석 결과를 Streamlit 없이 만든다."""
    from .alerts import detect_events
    from .prediction import attach_predictions
    from .standards import load_registry, load_settings
    from .store import DB_PATH, load_store
    from .ui import Ctx

    store = load_store()
    registry = load_registry()
    settings = load_settings()
    models = attach_predictions(store, registry)
    events = detect_events(store, registry, settings)
    demo = (DB_PATH.parent / ".demo").exists()
    return Ctx(store, registry, settings, models, events, demo)


def build_snapshot(ctx=None, trend_days: int = 14, strength_days: int = 120, ship_days: int = 180) -> str:
    from . import incoming as INC
    from . import shipment as S
    from .alerts import events_frame
    from .store import load_alert_status
    from .ui import trend_figure

    ctx = ctx or load_context()
    reg, store = ctx.registry, ctx.store
    period = store.period()
    now = datetime.now()
    fig = _FigWriter()
    parts: list[str] = []

    # ── 머리글 ──
    meta = []
    if period:
        meta.append(f"공정 데이터 {period[0]:%Y-%m-%d} ~ {period[1]:%Y-%m-%d}")
    if ctx.demo:
        meta.append("⚠️ 데모 데이터")
    end = period[1] if period else pd.Timestamp(now)
    recent = [e for e in ctx.events if e.end >= end - pd.Timedelta(days=7)]
    counts = {k: sum(e.severity == k for e in recent) for k in ("위험", "경고", "주의")}

    # ── 요약 KPI ──
    parts.append("<h2>요약 (최근 7일)</h2><div class='cards'>")
    parts.append(_card("🔴 위험(KS 이탈)", f"{counts['위험']}건", "제품 규격 이탈 — 출하 판정 필요", "red" if counts["위험"] else "green"))
    parts.append(_card("🟠 경고(사내기준)", f"{counts['경고']}건", "사내 관리기준 이탈", "orange" if counts["경고"] else "green"))
    parts.append(_card("🟡 주의(SPC)", f"{counts['주의']}건", "공정 불안정 징후"))
    phy = store.tables.get("physical", pd.DataFrame())
    for prod in ("1종", "3종"):
        if len(phy) and "product" in phy:
            s = phy[(phy["product"] == prod) & (phy["timestamp"] >= end - pd.Timedelta(days=60))]["phy_s28"].dropna()
            if len(s):
                parts.append(_card(f"28일 강도 평균({prod})", f"{s.mean():.1f} MPa", f"최근 60일 n={len(s)} · 최소 {s.min():.1f}"))
    inc = INC.load_incoming()
    if len(inc):
        j = INC.judge_frame(inc)
        rec = j[pd.to_datetime(j["채취일"]) >= end - pd.Timedelta(days=30)]
        nf = int((rec["최종판정"] == INC.FAIL).sum())
        parts.append(_card("📦 인수검사 불합격(30일)", f"{nf}건", f"검사 {len(rec)}건", "red" if nf else "green"))
    parts.append("</div>")

    # ── 핵심 공정 지표 ──
    parts.append(f"<h2>핵심 공정 지표 (최근 {trend_days}일 · 8시간 평균)</h2><div class='grid2'>")
    for key, prod in (("rm_lsf", None), ("clk_fcao", None), ("cem_blaine", "1종"), ("cem_blaine", "3종"),
                      ("cem_so3", "1종"), ("clk_c3s", None)):
        if key not in reg:
            continue
        f = trend_figure(ctx, key, prod, start=end - pd.Timedelta(days=trend_days), resample="8h", height=360,
                         title=reg[key].name + (f" [{prod}]" if prod else ""), show_target=False)
        if f is not None:
            f.update_xaxes(range=[end - pd.Timedelta(days=trend_days), end + pd.Timedelta(hours=6)])
            parts.append(fig(f))
    parts.append("</div>")

    # ── 28일 강도 ──
    parts.append(f"<h2>28일 압축강도 (최근 {strength_days}일, 점선 = 예측)</h2><div class='grid2'>")
    for prod in ("1종", "3종"):
        if "phy_s28" in reg:
            f = trend_figure(ctx, "phy_s28", prod, start=end - pd.Timedelta(days=strength_days), height=360,
                             title=f"28일 압축강도 [{prod}]")
            parts.append(fig(f) if f is not None else f'<div class="empty">{prod} 28일 강도 자료가 없습니다.</div>')
    parts.append("</div>")

    # ── 출하시멘트 ──
    ship = S.load_shipment()
    parts.append(f"<h2>출하시멘트 품종별 판정 (최근 {ship_days}일)</h2>")
    if ship.empty:
        parts.append('<div class="empty">출하시멘트 자료가 없습니다.</div>')
    else:
        std = S.load_ship_standards()
        last = ship["date"].max()
        for prod in S.PRODUCTS:
            sub = S.apply_filters(ship, start=last - pd.Timedelta(days=ship_days), end=last, kind="저염 포함 전체",
                                  product=prod)
            parts.append(f"<h3>{html.escape(prod)} — {len(sub)}건</h3>")
            if sub.empty:
                parts.append(f'<div class="empty">{html.escape(prod)} 출하 자료가 아직 없습니다.</div>')
                continue
            sm = S.summary_table(sub, std)
            cols = [c for c in ("판정", "항목", "단위", "최근값", "최근 채취일", "평균", "최소", "최대", "KS 하한", "KS 상한",
                                "사내 하한", "사내 상한", "KS 이탈(건)", "사내 이탈(건)", "시험 건수") if c in sm.columns]
            parts.append(_table(sm[cols]))

    # ── 인수검사 ──
    parts.append("<h2>원료 인수검사 (최근 30일)</h2>")
    if inc.empty:
        parts.append('<div class="empty">인수검사 자료가 없습니다.</div>')
    else:
        j = INC.judge_frame(inc)
        j["채취일"] = pd.to_datetime(j["채취일"])
        rec = j[j["채취일"] >= end - pd.Timedelta(days=30)]
        fin = rec["최종판정"]
        by = (rec.assign(합격=(fin == INC.PASS).astype(int), 불합격=(fin == INC.FAIL).astype(int))
              .groupby("검사종류").agg(건수=("최종판정", "size"), 합격=("합격", "sum"), 불합격=("불합격", "sum")).reset_index())
        parts.append(_table(by))
        fails = rec[fin == INC.FAIL].sort_values("채취일", ascending=False)[["채취일", "검사종류", "거래처", "품명", "판정사유"]]
        parts.append("<h3>불합격 내역</h3>" + (_table(fails) if len(fails) else '<div class="empty">불합격 없음</div>'))

    # ── 최근 알림 ──
    parts.append("<h2>최근 7일 알림</h2>")
    edf = events_frame(recent, load_alert_status())
    if len(edf):
        order = {"위험": 0, "경고": 1, "주의": 2}
        edf = edf.assign(_o=edf["severity"].map(order)).sort_values(["_o", "end"], ascending=[True, False])
        show = pd.DataFrame({"심각도": edf["severity"].map(lambda s: f"{SEV_ICON.get(s, '')} {s}"),
                             "공정": edf["stage"], "품종": edf["product"].fillna(""), "항목": edf["item_name"],
                             "내용": edf["rule_desc"], "시작": edf["start"], "종료": edf["end"],
                             "최악값": edf["worst_value"], "처리상태": edf["status"]})
        parts.append(_table(show, max_rows=150))
        if len(edf) > 150:
            parts.append(f'<div class="note">※ 150건까지만 표시(전체 {len(edf)}건) — 전체는 QMS 알림 센터에서.</div>')
    else:
        parts.append('<div class="empty">최근 7일 알림이 없습니다.</div>')

    body = "\n".join(parts)
    return f"""<!doctype html><html lang="ko" translate="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="google" content="notranslate">
<title>Blue365 품질 현황판</title><style>{CSS}</style></head><body>
<header><div class="wrap"><div class="meta">Blue365 QMS · 조회 전용 현황판</div><h1>품질 현황판</h1>
<div class="meta">{html.escape(' · '.join(meta))}</div>
<div class="stamp">기준 시각 {now:%Y-%m-%d %H:%M} 자동 생성</div></div></header>
<div class="wrap">{body}
<footer>이 파일은 QMS PC가 자동으로 만든 <b>조회 전용</b> 현황판입니다. 그래프는 마우스를 올리면 값이 보이고, 드래그로 확대할 수 없도록 고정했습니다.
데이터 업로드·기준 설정·상세 분석은 QMS 프로그램에서 하세요. 관리기준이 '예시'로 남아 있는 항목은 판정이 실제와 다를 수 있습니다.</footer>
</div>
<script>/* 모든 칸이 배치된 뒤 그래프 폭을 칸에 다시 맞춘다(첫 그래프가 전체 폭으로 그려지는 문제 방지) */
function fitPlots(){{if(!window.Plotly)return;document.querySelectorAll('.js-plotly-plot').forEach(function(d){{Plotly.Plots.resize(d);}});}}
window.addEventListener('load',function(){{fitPlots();setTimeout(fitPlots,300);}});window.addEventListener('resize',fitPlots);</script>
</body></html>"""


def write_snapshot(out_dir: Path, keep: int = 30, ctx=None) -> list[Path]:
    """out_dir 에 최신본 + 기록/날짜본 저장. 오래된 날짜본은 keep 개만 남긴다. → [최신본, 날짜본]."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = build_snapshot(ctx)
    latest = out_dir / LATEST_NAME
    tmp = latest.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(latest)                                   # 보는 사람이 열고 있어도 반쯤 쓴 파일이 보이지 않게
    arch = out_dir / ARCHIVE_DIR
    arch.mkdir(exist_ok=True)
    dated = arch / f"Blue365_현황_{datetime.now():%Y%m%d}.html"
    shutil.copyfile(latest, dated)
    olds = sorted(arch.glob("Blue365_현황_*.html"))
    for p in olds[:-keep] if keep and len(olds) > keep else []:
        p.unlink(missing_ok=True)
    return [latest, dated]
