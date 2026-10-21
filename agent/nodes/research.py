"""categorize(미분류 가맹점 LLM 분류) · research(MCP Tool 병렬 호출) 노드."""
import asyncio

from langsmith import traceable

from ..deps import Deps
from ..retry import with_retry
from .state import AgentState, add_usage


@traceable(name="categorize_node")
async def categorize_node(state: AgentState, deps: Deps) -> dict:
    """규칙에 없는 가맹점이 이번 조회 범위에 있으면 LLM으로 분류해 저장한다.
    분류를 먼저 해야 하는 이유: '9월 식비'에 하이디라오(미분류) 69,000원이 빠지면 합계가 틀린다.
    한 번 저장하면 다음 요청부터는 분류된 상태라 LLM을 다시 부르지 않는다.
    분류 모델은 기본으로 quality(8b) — 0.6b는 '하이디라오 강남점'을 쇼핑으로 분류했다(eval/classify_eval.py)."""
    if not state.get("calls"):
        return {}
    pending = (await deps.mcp.call_tool("list_uncategorized",
                                        {"month": state["month"]} if state.get("month") else {}))["merchants"]
    if not pending:
        return {"events": state["events"] + [{"type": "CategorizeSkipped"}]}
    model = deps.quality_llm if deps.classifier == "quality" else deps.fast_llm
    labels, usage = await asyncio.to_thread(model.classify, pending)
    for merchant, category in labels.items():
        await deps.mcp.call_tool("set_merchant_category", {"merchant": merchant, "category": category})
    return {"classified": labels, **add_usage(state, usage),
            "events": state["events"] + [{"type": "MerchantsClassified", "labels": labels}]}


@traceable(name="research_node")
async def research_node(state: AgentState, deps: Deps) -> dict:
    """조회 계획(calls)을 MCP Tool로 병렬 실행. 숫자는 전부 여기서 나온다."""
    async def one(call):
        result, retries = await with_retry(deps.mcp.call_tool, call["tool"], call["args"])
        return {**call, "result": result, "retries": retries}

    results = await asyncio.gather(*(one(c) for c in state["calls"]))
    events = list(state["events"]) + [{"type": "ToolCalled", "tool": r["tool"], "args": r["args"],
                                       "retries": r["retries"]} for r in results]
    return {"facts": [{"tool": r["tool"], "args": r["args"], "result": r["result"]} for r in results],
            "events": events}
