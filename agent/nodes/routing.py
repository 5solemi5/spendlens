"""route(가계부 질문 / 잡담 / 범위 밖) · chat_answer · refuse 노드."""
import asyncio

from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import Deps
from ..query import is_spending_question, parse_query
from .state import AgentState, add_cost

REFUSE_MESSAGE = ("투자·대출·주식·코인 같은 금융 상품에 대한 조언은 드리지 않아요. 저는 카드 지출을 분석하는 "
                  "가계부 비서예요. 대신 이런 걸 도와드릴 수 있어요: 월별·카테고리별 지출, 지난달과 비교, "
                  "이상 결제, 구독 정리, 예산 대비 현황.")


@traceable(name="route_node")
async def route_node(state: AgentState, deps: Deps) -> dict:
    """결정 순서: ① 범위 밖(투자 등) → refuse  ② 코드가 가계부 신호를 찾음 → spending
    ③ 신호가 없을 때만 LLM에게 묻는다("요즘 돈을 너무 많이 쓰는 것 같아"처럼 단어로 안 잡히는 경우)."""
    parsed = parse_query(state["query"], deps.catalog.get("merchants", []))
    events = state.get("events", [])
    if parsed["out_of_scope"]:
        return {"route": "refuse", "parsed": parsed,
                "events": events + [{"type": "RouteDecided", "route": "refuse", "by": "code"}]}
    if is_spending_question(parsed):
        return {"route": "spending", "parsed": parsed,
                "events": events + [{"type": "RouteDecided", "route": "spending", "by": "code"}]}
    result, usage = await asyncio.to_thread(deps.fast_llm.route, state["query"])
    return {"route": result["route"], "parsed": parsed, "cost_usd": add_cost(state, usage),
            "events": events + [{"type": "RouteDecided", "route": result["route"], "by": "llm"}]}


@traceable(name="chat_answer_node")
async def chat_answer_node(state: AgentState, deps: Deps) -> dict:
    writer = get_stream_writer()
    reply, usage = await deps.fast_llm.chat(
        state["query"], state.get("history", []),
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece}))
    return {"final": reply, "last_prompt": usage.get("prompt"), "cost_usd": add_cost(state, usage),
            "events": state["events"] + [{"type": "Finalize", "pipeline": "chat"}]}


@traceable(name="refuse_node")
async def refuse_node(state: AgentState, deps: Deps) -> dict:
    """범위 밖 질문 — LLM을 부르지 않는다(작은 모델은 '사도 됩니다'라고 답할 위험이 있다)."""
    return {"final": REFUSE_MESSAGE,
            "events": state["events"] + [{"type": "Finalize", "pipeline": "refuse"}]}
