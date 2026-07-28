"""야드변경 구간 정의 [Matching-Agent].

⭐️ 구간은 **반드시 라인별**로 정의한다.
   기존(9회·96~228h)과 신설(24회·42~100h)은 변경 시점이 거의 겹치지 않아
   (공통 4일) '두 라인 공통의 야드변경 기간'은 존재하지 않는다. 한 라인 기준으로
   자른 구간을 다른 라인에 적용하면 그 라인의 야드 기간을 중간에서 자르게 된다.

⭐️ 구간 경계
   - 시작: 변경 시각을 '시' 단위로 내림 → 그 시각대의 물류 집계까지 포함
   - 끝  : 다음 변경 **1분 전**(분 단위) → 다음 구간의 변경 이벤트를 확실히 배제
     (그러지 않으면 야드변경 물량이 한 건 통째로 더 섞여 최대 2배로 보인다)

정본은 이 모듈 하나뿐 — 리포트·대시보드가 함께 쓴다(중복 정의 금지).
"""

from __future__ import annotations

import pandas as pd


def yard_change_segments(yc, mine=None, osp_exp=None, yards=None) -> list[dict]:
    """라인별 야드변경 구간 목록 + 구간별 실제 데이터 건수.

    반환 항목: key/line/yard/s/e/hours/label/link/n_mine/n_osp/n_own/cao/mgo
      s, e   : 문자열 경계 (JS 사전순 비교와 pandas 양쪽에서 그대로 쓸 수 있다)
      start, end : pandas Timestamp 경계 (end 는 배타적 — 다음 변경 시각)
      link   : 야드변경 Sankey 의 링크 키 ('라인|야드')
    """
    if yc is None or len(yc) == 0:
        return []
    yards = yards or {}
    segs: list[dict] = []
    for ln, d in yc.sort_values("datetime").groupby("line"):
        d = d.reset_index(drop=True)
        y = yards.get(ln)
        tail = (pd.to_datetime(y["datetime"]).max()
                if y is not None and len(y) else d["datetime"].max())
        for i, r in d.iterrows():
            s = r["datetime"]
            e = d.loc[i + 1, "datetime"] if i + 1 < len(d) else max(tail, s)
            # 마지막 변경 뒤에 야드 데이터가 없으면(가동 중지 직전 변경 등) 구간이 빈다.
            # 조용히 버리면 '변경이 있었다'는 사실 자체가 사라지므로, 최소 1시간 구간으로
            # 남겨 두고 n_own=0 경고가 뜨게 한다 (§2-1 숨기지 않는다).
            if pd.isna(e) or e <= s:
                e = s + pd.Timedelta(hours=1)
            n_mine = _count(mine, ln, s.normalize(), e, "date")
            n_osp = _count(osp_exp, ln, s, e, "datetime")
            n_own = int(((y["datetime"] >= s) & (y["datetime"] < e)).sum()) \
                if y is not None and len(y) else 0
            e_excl = e - pd.Timedelta(minutes=1)
            segs.append(dict(
                key=f"{ln}|{i}", line=ln, yard=r["yard"],
                s=f"{s:%Y-%m-%dT%H}", e=f"{e_excl:%Y-%m-%dT%H:%M}",
                start=s.floor("1h"), end=e,          # end 는 배타적
                hours=round((e - s).total_seconds() / 3600),
                label=f"{ln} · {r['yard']} · {s:%m/%d %H시}~{e:%m/%d %H시}",
                link=f"{ln}|{r['yard']}",
                n_mine=n_mine, n_osp=n_osp, n_own=n_own,
                cao=None if pd.isna(r["cao"]) else round(float(r["cao"]), 2),
                mgo=None if pd.isna(r["mgo"]) else round(float(r["mgo"]), 2),
            ))
    return segs


def _count(df, line, s, e, col) -> int:
    """구간 [s, e) 안의 해당 라인 행 수."""
    if df is None or len(df) == 0 or col not in df.columns:
        return 0
    t = pd.to_datetime(df[col], errors="coerce")
    m = (t >= s) & (t < e)
    if "line" in df.columns:
        m &= df["line"] == line
    return int(m.sum())


def segment_warnings(seg: dict) -> list[str]:
    """구간을 해석할 때 반드시 함께 보여야 할 주의사항 (없으면 빈 리스트)."""
    w = []
    if seg["n_own"] == 0:
        w.append(f"이 구간에 {seg['line']} 야드 측정이 없습니다 (가동 중지 또는 측정 간격).")
    if seg["n_mine"] < 10:
        w.append(f"광산 기록이 {seg['n_mine']}건뿐이라 평균이 몇 건에 좌우됩니다.")
    return w


#: 구간을 볼 때 항상 함께 표시하는 고정 주의문 (Time-Lag)
LAG_CAUTION = ("이송 지연(3~6시간)이 있어 구간 끝에 캔 광석은 다음 구간 야드에 실립니다. "
               "짧은 구간에서 광산 품위와 야드 품위를 같은 물질로 보면 안 됩니다.")
