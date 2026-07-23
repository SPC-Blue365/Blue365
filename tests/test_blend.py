"""배합 최적화 솔버 단위 테스트.

합성 소스는 로직 검증용 픽스처(분석수치 아님, CLAUDE.md §2 무관).
"""

from __future__ import annotations

from src.optimization.blend import BlendSource, recommend_blend


def test_feasible_hits_target():
    # 44.0 과 45.2 를 섞으면 44.6 달성 가능
    sources = [BlendSource("A", 44.0, 1000), BlendSource("B", 45.2, 1000)]
    r = recommend_blend(sources, demand_ton=1000, target_cao=44.6, tol=0.5)
    assert r.feasible
    assert abs(r.achieved_cao - 44.6) <= 0.5
    assert abs(sum(r.allocation.values()) - 1000) < 1e-6


def test_infeasible_too_high_reports_bottleneck():
    # 모든 소스가 목표보다 훨씬 낮음 → 목표 미달, 근접 배합 + 경고
    sources = [BlendSource("A", 40.0, 1000), BlendSource("B", 41.0, 1000)]
    r = recommend_blend(sources, demand_ton=1000, target_cao=44.6, tol=0.5)
    assert not r.feasible
    assert r.achieved_cao <= 41.0 + 1e-6  # 가능한 최고치 근처
    assert r.bottleneck  # 병목 보고


def test_insufficient_inventory():
    sources = [BlendSource("A", 44.6, 100)]
    r = recommend_blend(sources, demand_ton=1000, target_cao=44.6)
    assert not r.feasible
    assert "재고" in r.message


def test_allocation_within_capacity():
    sources = [BlendSource("A", 44.0, 300), BlendSource("B", 45.5, 900)]
    r = recommend_blend(sources, demand_ton=1000, target_cao=44.6)
    for s in sources:
        assert r.allocation[s.name] <= s.available_ton + 1e-6
