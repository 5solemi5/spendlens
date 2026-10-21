"""그래프 상태 정의 + 노드 공통 도우미."""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    query: str
    thread_id: str
    history: list[dict]
    route: str                 # spending / chat / refuse
    parsed: dict               # query.parse_query 결과
    intents: list[str]
    months: list[str]          # 조회할 달 (비교면 2개, 전체 기간이면 빈 목록)
    month: str | None          # 대표 달 (전체 기간이면 None)
    category: str | None
    merchant: str | None
    budget_change: dict | None
    missing_months: list[str]  # 질문에 나왔지만 데이터가 없는 달
    clarify_reason: str
    calls: list[dict]          # 조회 계획: [{"tool", "args"}]
    classified: dict           # 이번 요청에서 LLM이 새로 분류한 가맹점
    facts: list[dict]          # [{"tool", "args", "result"}]
    guides: list[dict]         # 절약 가이드 RAG 결과
    facts_text: str
    draft: str
    validation_attempts: int
    validation_feedback: str | None
    grounding_issues: list[str]
    approval: dict
    final: str
    last_prompt: str
    cost_usd: float
    prompt_tokens: int         # 이번 요청에서 LLM에 넣은 프롬프트 토큰 합 (Before/After 비교용)
    events: list[dict]


def add_usage(state: AgentState, usage: dict) -> dict:
    """이번 LLM 호출의 비용·프롬프트 토큰을 누적한 상태 갱신값. 노드는 return {..., **add_usage(state, usage)}."""
    return {"cost_usd": round(state.get("cost_usd", 0.0) + usage["usd"], 6),
            "prompt_tokens": state.get("prompt_tokens", 0) + usage.get("prompt_tokens", 0)}
