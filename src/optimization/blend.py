"""배합 최적화 솔버 (선형계획법) [ML-Engineer].

목표 CaO(44.6±0.5)를 맞추기 위해 각 인출 지점/구역에서 몇 톤을 가져와 배합할지 역산·추천한다.

⚠️ 현재 상태(정직 고지): 상류 인출→야드 상관이 약해(0.18) 구역별 품위 추정 신뢰도가 낮다.
   따라서 지금은 '방향성 가이드'로만 사용한다. 데이터가 축적되어 구역-품위 추정이 정밀해지면
   동일 인터페이스로 그대로 정밀 처방이 된다.

수학(총 수요 D 고정 시 배합은 x에 선형):
    결정변수 x_i = 소스 i 인출톤,  blend_cao = Σ(x_i·g_i)/D
    목표: |Σ(x_i·g_i) − target·D| 최소화  (보조변수 t 로 LP화)
    제약: Σx_i = D,  0 ≤ x_i ≤ available_i
달성 불가(재고로 목표범위 물리적 불가) 시: 억지 답 대신 '가장 근접한 배합 + 경고 + 병목' 반환.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linprog


@dataclass
class BlendSource:
    """배합 후보 소스(인출 지점/구역)."""

    name: str
    grade_cao: float      # 추정 CaO 품위(%)
    available_ton: float  # 가용 재고(톤)


@dataclass
class BlendResult:
    feasible: bool                       # 목표범위(±tol) 달성 여부
    achieved_cao: float                  # 추천 배합의 CaO
    allocation: dict[str, float]         # 소스별 인출톤
    demand_ton: float
    target_cao: float
    message: str = ""
    bottleneck: list[str] = field(default_factory=list)

    def summary(self) -> str:
        head = "✅ 목표 달성" if self.feasible else "⚠️ 목표 미달(근접 배합)"
        lines = [f"{head}: 배합 CaO={self.achieved_cao:.2f}% (목표 {self.target_cao}), 총 {self.demand_ton:.0f}톤"]
        for k, v in self.allocation.items():
            if v > 1e-6:
                lines.append(f"  - {k}: {v:.1f}톤")
        if self.message:
            lines.append(f"  ※ {self.message}")
        return "\n".join(lines)


def recommend_blend(
    sources: list[BlendSource],
    demand_ton: float,
    target_cao: float = 44.6,
    tol: float = 0.5,
) -> BlendResult:
    """목표 CaO에 맞는 소스별 인출톤을 추천한다.

    달성 불가 시 가장 근접한 배합을 반환하고 feasible=False + 병목을 보고한다(CLAUDE.md §3).
    """
    n = len(sources)
    if n == 0 or demand_ton <= 0:
        return BlendResult(False, float("nan"), {}, demand_ton, target_cao, "소스/수요 없음")

    g = np.array([s.grade_cao for s in sources], dtype=float)
    cap = np.array([s.available_ton for s in sources], dtype=float)
    names = [s.name for s in sources]

    # 재고 총량 부족 체크
    if cap.sum() < demand_ton - 1e-9:
        return BlendResult(
            False, float("nan"), {}, demand_ton, target_cao,
            f"총 재고 {cap.sum():.0f}톤 < 수요 {demand_ton:.0f}톤 (재고 부족)",
            bottleneck=["총 재고 부족"],
        )

    # 물리적 달성 가능 범위 [min blend, max blend] (수요를 채우는 조합 기준)
    # 최소/최대 CaO: 저품위/고품위 소스부터 채워 D톤 구성
    def extreme(order):
        rem, acc = demand_ton, 0.0
        for i in order:
            take = min(cap[i], rem)
            acc += take * g[i]
            rem -= take
            if rem <= 1e-9:
                break
        return acc / demand_ton

    lo = extreme(np.argsort(g))         # 저품위 우선 → 최저 배합
    hi = extreme(np.argsort(g)[::-1])   # 고품위 우선 → 최고 배합

    # LP: min t  s.t.  Σx_i g_i − target·D ≤ t ; −(Σx_i g_i − target·D) ≤ t ; Σx_i = D ; 0≤x_i≤cap
    # 변수: [x_0..x_{n-1}, t]
    c = np.concatenate([np.zeros(n), [1.0]])
    A_ub = np.array([
        np.concatenate([g, [-1.0]]),      #  Σx g − t ≤ target·D
        np.concatenate([-g, [-1.0]]),     # −Σx g − t ≤ −target·D
    ])
    b_ub = np.array([target_cao * demand_ton, -target_cao * demand_ton])
    A_eq = np.array([np.concatenate([np.ones(n), [0.0]])])
    b_eq = np.array([demand_ton])
    bounds = [(0, cap[i]) for i in range(n)] + [(0, None)]

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        return BlendResult(False, float("nan"), {}, demand_ton, target_cao, f"LP 실패: {res.message}")

    x = res.x[:n]
    achieved = float((x * g).sum() / demand_ton)
    feasible = abs(achieved - target_cao) <= tol + 1e-6
    alloc = {names[i]: float(x[i]) for i in range(n)}

    msg, bott = "", []
    if not feasible:
        if target_cao > hi:
            msg = f"재고 최고 품위로도 {hi:.2f}%까지만 가능(목표 {target_cao}). 고품위 재고 부족."
            bott = ["고품위 재고 부족"]
        elif target_cao < lo:
            msg = f"재고 최저 품위로도 {lo:.2f}%까지만 가능(목표 {target_cao}). 저품위 재고 부족."
            bott = ["저품위 재고 부족"]
        else:
            msg = "수치 오차 범위 내 근접."
    return BlendResult(feasible, achieved, alloc, demand_ton, target_cao, msg, bott)
