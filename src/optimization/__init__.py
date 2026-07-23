"""배합 최적화 [ML-Engineer].

향후 데이터 축적 시 정밀 처방을 위한 프레임워크. 현재 상류 신호가 약해(상관 0.18)
'방향성 가이드(신뢰도 낮음)'로 사용하되, 구조는 완성해 둔다.
"""

from src.optimization.blend import (
    BlendSource,
    BlendResult,
    recommend_blend,
)

__all__ = ["BlendSource", "BlendResult", "recommend_blend"]
