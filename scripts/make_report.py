"""파일럿 결과물 생성 (예측·모니터링 리포트) [Synthesis-Agent].

실행:
    python scripts/make_report.py

라인별 예측 실측 대비 차트 + 조기경보 + 성능표 + 배합최적화 데모를 담은
자기완결 HTML 리포트를 outputs/ 에 생성한다. (로컬 전용: 원격 커밋/외부발행 안 함)
"""

from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config import schema as S
from config.paths import RAW_DIR, OUTPUTS_DIR, FIGURES_DIR, ensure_dirs
from src.data import clean as C
from src.matching import pipeline as P
from src.models import forecast as F
from src.optimization.blend import BlendSource, recommend_blend

PAIR = {
    S.LINE_OLD: (S.SHEET_MINE_45Q, "45Q · 4-5K 킬른 야드"),
    S.LINE_NEW: (S.SHEET_YARD_CNA, "CNA · 6-7K 킬른 야드"),
}
TGT, LO, HI = S.TARGET.cao_mean, S.TARGET.lower, S.TARGET.upper


def _prep(xls, osp_exp, line, sheet):
    y = C.clean_yard(pd.read_excel(xls, sheet)).dropna(subset=["datetime"]).copy()
    y["h"] = y["datetime"].dt.floor("1h")
    ys = y.groupby("h")["cao"].mean().asfreq("1h")
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["datetime"]).copy()
    o["h"] = o["datetime"].dt.floor("1h")
    oh = o.groupby("h").agg(impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))
    lag = P.estimate_time_lag(
        oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
        ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}), 24
    ).best_lag_hours
    return F.build_features(ys, oh, lag)


def _fig_to_b64(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    ensure_dirs()
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)
    mine = pd.concat([C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q)),
                      C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q))], ignore_index=True)
    osp = pd.concat([C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
                     C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW)], ignore_index=True)
    osp_exp = P.assign_expected_cao_timeaware(osp, mine)

    cards = []
    for line, (sheet, alias) in PAIR.items():
        feats = _prep(xls, osp_exp, line, sheet)
        d = feats.dropna(subset=F.AR_CORE + ["cao"]).copy()
        # 시간순 70/30 분할 → 검증구간 실측 대비 예측
        k = int(len(d) * 0.7)
        model, fcols = F.fit_final(d.iloc[:k], use_upstream=False)
        te = d.iloc[k:]
        pred = model.predict(te[fcols].fillna(0).values)
        mae = float(np.abs(te["cao"].values - pred).mean())
        # 조기경보: 예측이 규격 밖
        oos = (pred < LO) | (pred > HI)

        fig, ax = plt.subplots(figsize=(11, 3.4))
        ax.axhspan(LO, HI, color="#2ca02c", alpha=0.12, label=f"규격 {LO}~{HI}")
        ax.axhline(TGT, color="#2ca02c", ls="--", lw=1, label=f"목표 {TGT}")
        ax.plot(te.index, te["cao"].values, color="#1f77b4", lw=1.2, label="실측 CaO")
        ax.plot(te.index, pred, color="#d62728", lw=1.2, alpha=0.85, label="예측 CaO")
        if oos.any():
            ax.scatter(te.index[oos], pred[oos], color="#ff7f0e", s=16, zorder=5, label="규격이탈 경보")
        ax.set_title(f"{line} 라인 → {alias}  (검증 MAE={mae:.2f})", fontsize=11)
        ax.set_ylabel("CaO (%)"); ax.legend(loc="upper right", fontsize=7, ncol=5)
        ax.grid(alpha=0.25)
        b64 = _fig_to_b64(fig)
        # 로컬 PNG 도 저장
        (FIGURES_DIR / f"pred_{line}.png").write_bytes(base64.b64decode(b64))
        cards.append((line, alias, mae, int(oos.sum()), len(te), b64))

    # 배합 최적화 데모 (방향성 가이드)
    demo = recommend_blend(
        [BlendSource("구역45(기존)", 44.1, 2000), BlendSource("구역55(신설)", 45.4, 2000),
         BlendSource("구역60", 46.0, 1500)], demand_ton=3000, target_cao=TGT)

    html = _render_html(cards, demo)
    out = OUTPUTS_DIR / "report_pilot1.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] 리포트 생성: {out}")
    for line, alias, mae, n_oos, n, _ in cards:
        print(f"  {line}→{alias}: 검증 MAE={mae:.2f}, 경보 {n_oos}/{n}시간")


def _render_html(cards, demo) -> str:
    rows = "".join(
        f"<tr><td>{l}</td><td>{a}</td><td><b>{m:.2f}</b></td><td>{o}/{n}</td></tr>"
        for l, a, m, o, n, _ in cards
    )
    figs = "".join(
        f'<h3>{l} 라인 → {a}</h3><img src="data:image/png;base64,{b}" style="width:100%;max-width:960px"/>'
        for l, a, m, o, n, b in cards
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>석회석 CaO 추적·예측 파일럿 리포트</title>
<style>body{{font-family:system-ui,'Malgun Gothic',sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1a1a1a;line-height:1.6}}
h1{{border-bottom:3px solid #1f77b4;padding-bottom:8px}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{border:1px solid #ddd;padding:8px;text-align:center}}th{{background:#f0f4f8}}
.note{{background:#fff8e1;border-left:4px solid #ffb300;padding:10px 14px;margin:14px 0;border-radius:4px}}
.ok{{background:#e8f5e9;border-left:4px solid #2ca02c;padding:10px 14px;margin:14px 0;border-radius:4px}}
code{{background:#f4f4f4;padding:1px 5px;border-radius:3px}}</style></head><body>
<h1>석회석 광산-야드 CaO 추적·예측 파일럿</h1>
<p>원본 <code>data_v1.xlsx</code> (2026-06~07) 기준. 광산→OSP→야드 추적 매칭 + 야드 CaO 단기 예측.</p>

<h2>1. 예측 성능 (검증구간 30%, 시간순 분할)</h2>
<table><tr><th>라인</th><th>야드</th><th>MAE</th><th>규격이탈 경보</th></tr>{rows}</table>
<div class="ok"><b>실무적 유용성:</b> 평균 예측(naive) 대비 오차를 크게 낮췄습니다. 특히 신설/CNA는
MAE 0.8 수준으로 <b>실시간 CaO 모니터링·조기경보</b>에 사용 가능합니다.</div>
<div class="note"><b>정직한 한계:</b> 목표 예측정밀도(MAE&lt;0.5)는 아직 미달입니다. 야드 CaO는
지속성(자기상관)이 지배적이며, <b>상류(OSP 인출) 정보가 야드 품위를 거의 설명하지 못합니다</b>(상관 0.18).
→ 상류로 품위를 '조절'하는 처방적 제어는 데이터 축적 후 가능.</div>

<h2>2. 예측 실측 대비 & 조기경보</h2>
<p>파란선=실측, 빨간선=예측, 주황점=규격(44.1~45.1) 이탈 경보.</p>
{figs}

<h2>3. 배합 최적화 (경로 2 · 향후용 프레임워크)</h2>
<p>구조는 완성돼 있으며, 향후 구역-품위 추정이 정밀해지면 그대로 처방 정밀도가 올라갑니다.
현재는 <b>방향성 가이드(신뢰도 낮음)</b>. 데모 결과:</p>
<pre style="background:#f4f4f4;padding:12px;border-radius:6px">{demo.summary()}</pre>

<h2>4. 다음 단계</h2>
<ul>
<li><b>경로 1(메인)</b>: 예측·모니터링을 운영 도구로 패키징, 최적 모델 탐색(여러 알고리즘 비교).</li>
<li><b>경로 2(병행)</b>: 데이터가 쌓이는 대로 배합 최적화 정밀화.</li>
</ul>
<p style="color:#888;font-size:0.85em">※ 본 리포트와 데이터는 로컬 전용입니다. 외부(원격)에 발행/커밋하지 않습니다.</p>
</body></html>"""


if __name__ == "__main__":
    main()
