"""SpendLens LangGraph — 노드 연결(엣지)만 둔다. 노드 구현은 agent/nodes/.

route ─┬─ chat_answer                                   (잡담: 요약 메모리 + 이름 기억)
       ├─ refuse                                        (투자·대출 등 범위 밖 → 정중히 거절, LLM 없음)
       └─ plan ─┬─ no_data                              (데이터 없는 달 → 0원이라 답하지 않고 안내)
                ├─ clarify                              (예산 변경인데 카테고리·금액 없음 → 되묻기)
                └─ categorize → research ─┬─ advise → write ⇄ validate → finalize
                                          └─ propose_change → approval(사람 승인) → finalize
"""
from functools import partial

from langgraph.graph import END, StateGraph

from .deps import Deps
from .nodes.advising import advise_node
from .nodes.budget import approval_node, propose_change_node
from .nodes.planning import clarify_node, no_data_node, plan_node
from .nodes.research import categorize_node, research_node
from .nodes.routing import chat_answer_node, refuse_node, route_node
from .nodes.state import AgentState
from .nodes.writing import finalize_node, validate_node, write_node


def _after_route(state: AgentState) -> str:
    return {"spending": "plan", "chat": "chat_answer", "refuse": "refuse"}[state["route"]]


def _after_plan(state: AgentState) -> str:
    if state.get("missing_months"):
        return "no_data"
    if state.get("clarify_reason"):
        return "clarify"
    return "categorize"


def _after_research(state: AgentState) -> str:
    return "propose_change" if "budget_change" in state["intents"] else "advise"


def _after_validate(state: AgentState) -> str:
    return "finalize" if state.get("validation_feedback") is None else "write"


def build_graph(deps: Deps, checkpointer=None):
    """checkpointer: 승인 대기(interrupt)로 멈춘 상태를 저장할 곳. HITL을 켰는데 안 주면 메모리 저장소."""
    if deps.hitl and checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()
    g = StateGraph(AgentState)
    node = lambda fn: partial(fn, deps=deps)   # 의존성 주입
    for name, fn in [("route", route_node), ("chat_answer", chat_answer_node), ("refuse", refuse_node),
                     ("plan", plan_node), ("no_data", no_data_node), ("clarify", clarify_node),
                     ("categorize", categorize_node), ("research", research_node), ("advise", advise_node),
                     ("write", write_node), ("validate", validate_node), ("finalize", finalize_node),
                     ("propose_change", propose_change_node), ("approval", approval_node)]:
        g.add_node(name, node(fn))
    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route, {"plan": "plan", "chat_answer": "chat_answer", "refuse": "refuse"})
    g.add_conditional_edges("plan", _after_plan, {"no_data": "no_data", "clarify": "clarify", "categorize": "categorize"})
    g.add_edge("categorize", "research")
    g.add_conditional_edges("research", _after_research, {"propose_change": "propose_change", "advise": "advise"})
    g.add_edge("advise", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", _after_validate, {"finalize": "finalize", "write": "write"})
    g.add_edge("propose_change", "approval")
    g.add_edge("approval", "finalize")
    for end in ("chat_answer", "refuse", "no_data", "clarify", "finalize"):
        g.add_edge(end, END)
    return g.compile(checkpointer=checkpointer)
