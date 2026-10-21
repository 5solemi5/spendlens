"""의존성 주입 — 노드 함수가 쓰는 모든 외부 자원을 하나에 담아 functools.partial로 넘긴다(수업 Wave 13 패턴).
테스트에서는 가짜 LLM·가짜 MCP로 갈아 끼운다."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Deps:
    fast_llm: Any          # 라우팅·의도 보충·가맹점 분류·잡담·요약 (작은 모델)
    quality_llm: Any       # 최종 답변 작성 (큰 모델)
    mcp: Any               # MCP 클라이언트 (계산 엔진 Tool, 가이드 Resource)
    session_store: Any     # 대화 이력 (SQLite)
    hitl: bool = True      # 예산 변경 같은 저장 조치를 사람 승인 후에만 실행
    classifier: str = "quality"   # 가맹점 분류 모델: "quality"(기본) | "fast" — 분류는 가맹점당 1번이라 큰 모델도 부담이 작다
    catalog: dict = field(default_factory=dict)   # data_catalog Tool 결과 (months, merchants, categories)
