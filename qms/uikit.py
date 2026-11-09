"""관리용 앱(Streamlit)에서 보는용 현황판과 같은 모양을 그리는 HTML 조각 (docs/UI_디자인_가이드.md).

카드 = 흰 카드 + 회색 미리보기(well) + '01 제목 / 보조 설명', 결론형 큰 제목, 상태 칩, 진행 링, 평점 요약형 막대.
CSS 는 qms/theme.py 의 KIT_CSS(.qk 아래로 범위 제한).
"""

from __future__ import annotations

import html
import re

import streamlit as st

SEV_CLS = {"위험": "bad", "경고": "warn", "주의": "warn", "정상": "ok"}
TONE = {"ok": ("ok", "양호"), "warn": ("warn", "확인 필요"), "bad": ("bad", "기준 이탈"), "mute": ("mute", "기준 없음")}


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def em(text: str) -> str:
    """'**강조**' → 파란 글자, 줄바꿈(\\n) → <br>. 나머지는 이스케이프."""
    out = esc(text).replace("\n", "<br>")
    return re.sub(r"\*\*(.+?)\*\*", r"<em>\1</em>", out)


def pill(cls: str, text: str) -> str:
    return f'<span class="pill {cls}">{esc(text)}</span>'


def sev_pill(sev: str) -> str:
    return pill(SEV_CLS.get(sev, "mute"), sev)


def headline(text: str, lead: str | None = None) -> str:
    return f'<h1 class="qk-hl">{em(text)}</h1>' + (f'<p class="qk-lead">{esc(lead)}</p>' if lead else "")


def ring(pct: float, ok: bool = True) -> str:
    r, p = 40, max(0.0, min(100.0, float(pct)))
    c = 2 * 3.14159265 * r
    color = "var(--q-ok)" if ok else "var(--q-bad)"
    return (f'<div class="ring" role="img" aria-label="{p:.0f}%"><svg viewBox="0 0 92 92">'
            f'<circle cx="46" cy="46" r="{r}" fill="none" stroke="var(--q-line)" stroke-width="9"/>'
            f'<circle cx="46" cy="46" r="{r}" fill="none" stroke="{color}" stroke-width="9" stroke-linecap="round" '
            f'stroke-dasharray="{c:.1f}" stroke-dashoffset="{c * (1 - p / 100):.1f}"/></svg><b>{p:.0f}%</b></div>')


def status_icon(status: str) -> str:
    color = {"정상": "--q-ok", "주의": "--q-warn", "경고": "--q-warn", "위험": "--q-bad"}.get(status, "--q-faint")
    path = ('<path d="m7 12.5 3.2 3.2L17 9"/>' if status == "정상" else
            '<path d="m8 8 8 8M16 8l-8 8"/>' if status == "위험" else '<path d="M12 7v6"/><path d="M12 17h.01"/>')
    return (f'<svg viewBox="0 0 24 24" width="36" height="36" aria-hidden="true" style="flex:none"><circle cx="12" cy="12" r="11" fill="var({color})"/>'
            f'<g fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">{path}</g></svg>')


def card(no: str | None, title: str, sub: str = "", well: str = "", i: int = 0, cls: str = "") -> str:
    """흰 카드 1장(HTML). well 은 이미 만든 HTML."""
    return (f'<div class="card {cls}" style="--i:{i}"><div class="well">{well}</div><div class="cap">'
            f'<div class="t">{f"<span class=no>{esc(no)}</span>" if no else ""}{title}</div>'
            f'{f"<small>{sub}</small>" if sub else ""}</div></div>')


def kpi_card(i: int, label: str, value: str, unit: str = "", sub: str = "", note: str = "", tone: str | None = None,
             ring_pct: float | None = None) -> str:
    chip = f'<span class="corner">{pill(*TONE[tone])}</span>' if tone else ""
    top = ring(ring_pct, ring_pct >= 100) if ring_pct is not None else ""
    big = f'<div class="big"{" style=text-align:center;font-size:20px" if ring_pct is not None else ""}>{esc(value)}' \
          f'{f"<span>{esc(unit)}</span>" if unit else ""}</div>'
    return card(f"{i + 1:02d}", esc(label), esc(sub), top + big + (f'<div class="note">{esc(note)}</div>' if note else "") + chip, i)


def grid(cards: list[str], kind: str = "auto") -> None:
    """카드 바둑판을 화면에 그린다. kind: auto(넓은 카드) | stage(좁은 카드)."""
    st.html(f'<div class="qk"><div class="grid g-{kind}">{"".join(cards)}</div></div>')


def sev_summary(counts: dict, days: int = 14) -> str:
    tot = sum(counts.values())
    mx = max([1, *counts.values()])
    rows = "".join(
        f'<div class="r"><span>{k}</span><div class="pbar"><i style="width:{100 * counts.get(k, 0) / mx:.0f}%;'
        f'background:var(--q-{"bad" if k == "위험" else "warn"})"></i></div><span class="n">{counts.get(k, 0)}</span></div>'
        for k in ("위험", "경고", "주의"))
    return (f'<div class="qk"><h3 class="qk-h3">최근 {days}일 알림</h3><div class="sum"><div class="tot"><div class="big">{tot}</div>'
            f'<small>건</small></div><div class="rows">{rows}</div></div>'
            '<p class="note" style="margin-top:12px">같은 항목이 이어지면 한 건으로 묶어 셉니다.</p></div>')


def section(title: str, sub: str = "") -> None:
    st.html(f'<div class="qk"><h2 class="qk-sec">{esc(title)}{f" <small>{esc(sub)}</small>" if sub else ""}</h2></div>')


def banner(text: str, kind: str = "info") -> None:
    ic = "!" if kind == "warn" else "i"
    st.html(f'<div class="qk"><div class="banner {kind}"><span class="ic">{ic}</span><p>{em(text)}</p></div></div>')


def empty(text: str) -> None:
    st.html(f'<div class="qk"><div class="empty">{em(text)}</div></div>')
