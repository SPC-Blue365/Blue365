"""추적 연결 점수판 [Matching-Agent] — "데이터가 하나로 이어졌는가".

⭐️ **이 프로젝트의 성공 기준**이다 (2026-10-20 사용자 확정). 예측도 처방도 그다음 단계이며,
   먼저 광산 → OSP → 야드가 **끊김 없이 이어져야** 한다.

그동안 이 숫자들은 7개 문서에 흩어져 있었고, 각각 "무엇이 안 된다" 는 문제 보고로 쓰였다.
같은 숫자를 **점수판**으로 모으면 읽는 사람이 한눈에 "지금 어디까지 이어졌나" 를 안다.

이음매는 넷이며 **전부 라인 단위**다 — 구역 단위 추적은 포기했다(§6-0-28). 현장이 구역별
재고를 측정하지 않으므로 그 해상도는 원리적으로 가질 수 없고, 가진 척하면 숫자만 그럴듯해진다.

    ① 광산 품위 기록      적재 물량 중 품위가 적힌 비율
    ② OSP 더미 수지       적재 − 인출 이 실사 재고 변화와 맞는가
    ③ 야드 목적지 귀속     어느 야드로 갔는지가 야드 자체 기록과 맞는가
    ④ 인출 시각           시간축에 올릴 수 있는 물량 비율

그리고 이 넷을 통과한 결과가 **머릿줄**이다 —
"야드로 간 물량의 몇 % 가 '어느 더미에서 언제 쌓인 돌인지' 말할 수 있는가."
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import schema as S
from src.matching.pipeline import GRADE_SOURCE, TRUSTED_SOURCES

#: 이음매 판정 기준 — 넘으면 '이어짐', 못 미치면 '끊김'. 운전에 쓰려면 이 정도는 돼야 한다.
GOOD, FAIR = 95.0, 85.0


@dataclass
class Joint:
    """이음매 하나."""
    key: str
    name: str
    score: float              # 0~100, 클수록 이어짐
    label: str                # 화면에 쓰는 값 ("98.4%" · "격차 2.7%")
    why: str                  # 이 숫자가 무슨 뜻인지 한 줄
    gap: str = ""             # 못 이은 부분이 무엇인지 (있으면)

    @property
    def tone(self) -> str:
        return "good" if self.score >= GOOD else ("warn" if self.score >= FAIR else "bad")


@dataclass
class Chain:
    joints: list = field(default_factory=list)
    linked_pct: float = float("nan")      # 머릿줄 — 출처·시각을 다 아는 물량 비율
    linked_ton: float = float("nan")
    total_ton: float = float("nan")

    @property
    def weakest(self):
        return min(self.joints, key=lambda j: j.score) if self.joints else None

    def sentence(self) -> str:
        """사람이 읽는 한 문장 — 이 화면이 답해야 할 질문에 대한 답."""
        if not np.isfinite(self.linked_pct):
            return "연결 상태를 계산할 자료가 없습니다."
        w = self.weakest
        s = (f"야드로 간 물량의 <b>{self.linked_pct:.1f}%</b> 는 "
             f"<b>어느 더미에서 언제 쌓인 돌인지</b> 말할 수 있습니다.")
        if w is not None and w.tone != "good":
            s += f" 남은 약한 고리는 <b>{w.name}</b> 입니다."
        return s


def _mine_grade_recorded(mine: pd.DataFrame) -> Joint:
    m = mine[mine["line"].isin(S.YARD_PAIR)]
    tot = float(pd.to_numeric(m["tonnage"], errors="coerce").sum())
    ok = float(pd.to_numeric(m.dropna(subset=["cao"])["tonnage"], errors="coerce").sum())
    pct = ok / tot * 100 if tot else float("nan")
    return Joint(
        "mine", "광산 품위 기록", pct, f"{pct:.1f}%",
        "적재한 물량 중 CaO 가 적힌 비율입니다. 품위가 없으면 그 돌은 추적해도 값을 모릅니다.",
        "" if pct >= GOOD else f"품위 없는 적재 {tot - ok:,.0f}톤")


def _osp_balance(stock, mine, osp) -> Joint:
    """적재 − 인출 이 실사 재고 변화와 맞는가 (라인 단위 수지)."""
    from src.matching.balance import combined_mass_gap

    cm = combined_mass_gap(stock, mine, osp)
    if not cm:
        return Joint("osp", "OSP 더미 수지", float("nan"), "—",
                     "실사 재고가 없어 수지를 맞춰 볼 수 없습니다.")
    gap = abs(float(cm["gap_pct"]))
    return Joint(
        "osp", "OSP 더미 수지", max(0.0, 100 - gap * 2), f"격차 {gap:.1f}%",
        "적재에서 인출을 뺀 값이 실사 재고 변화와 얼마나 맞는지입니다. "
        "벌어질수록 '어디로 갔는지 모르는 물량' 이 생깁니다.",
        f"설명되지 않는 물량 {abs(float(cm['gap'])):,.0f}톤" if gap > 1 else "")


def _yard_attribution(osp, yard_change) -> Joint:
    """인출이 어느 야드로 갔는가 — 야드 자체 기록과 대조."""
    if yard_change is None or not len(yard_change) or "dest_line" not in osp.columns:
        return Joint("yard", "야드 목적지 귀속", float("nan"), "—",
                     "야드변경 기록이 없어 대조할 수 없습니다.")
    act = yard_change.groupby("line")["tonnage"].sum()
    dst = osp.groupby("dest_line")["withdrawn_ton"].sum()
    if not len(act) or not len(dst) or act.sum() <= 0 or dst.sum() <= 0:
        return Joint("yard", "야드 목적지 귀속", float("nan"), "—", "대조할 자료가 없습니다.")
    err = max(abs(dst.get(ln, 0.0) / dst.sum() - act.get(ln, 0.0) / act.sum()) * 100
              for ln in S.YARD_PAIR)
    # 1%p 안쪽이면 사실상 일치, 3%p 를 넘으면 라인 배분을 못 믿는다는 뜻
    return Joint(
        "yard", "야드 목적지 귀속", max(0.0, 100 - err * 5), f"오차 {err:.1f}%p",
        "인출을 라인별로 나눈 비율이 야드가 따로 적은 기록과 얼마나 맞는지입니다.",
        "" if err <= 2 else f"라인 배분이 {err:.1f}%p 어긋납니다")


def _time_known(osp) -> Joint:
    tot = float(pd.to_numeric(osp["withdrawn_ton"], errors="coerce").sum())
    ok = float(pd.to_numeric(
        osp.loc[osp["time_known"].fillna(True), "withdrawn_ton"], errors="coerce").sum())
    pct = ok / tot * 100 if tot else float("nan")
    return Joint(
        "time", "인출 시각", pct, f"{pct:.1f}%",
        "인출 시각을 아는 물량 비율입니다. 시각을 모르면 품위를 시간축에 올릴 수 없습니다.",
        "" if pct >= GOOD else f"시각 미상 {tot - ok:,.0f}톤")


def build_chain(mine, osp, stock=None, yard_change=None) -> Chain:
    """네 이음매를 재고 머릿줄을 만든다.

    머릿줄 = **출처(더미 품위)와 시각을 모두 아는 물량 비율**. 둘 중 하나라도 모르면
    그 돌은 '어디서 언제 온 것' 이라고 말할 수 없다.
    """
    tot = float(pd.to_numeric(osp["withdrawn_ton"], errors="coerce").sum())
    known = osp[osp[GRADE_SOURCE].isin(TRUSTED_SOURCES) & osp["time_known"].fillna(True)]
    lt = float(pd.to_numeric(known["withdrawn_ton"], errors="coerce").sum())
    return Chain(
        joints=[_mine_grade_recorded(mine), _osp_balance(stock, mine, osp),
                _yard_attribution(osp, yard_change), _time_known(osp)],
        linked_pct=(lt / tot * 100 if tot else float("nan")),
        linked_ton=lt, total_ton=tot)
