"""plan(기간·의도 → 조회 계획) · no_data(데이터 없는 기간 안내) · clarify(되묻기) 노드."""
import asyncio

from langsmith import traceable

from ..deps import Deps
from ..query import REF_MONTH
from .state import AgentState, add_cost

# 의도 → 필요한 MCP Tool. args의 "{month}" 등은 plan_node가 실제 값으로 채운다.
NEEDS_MONTH = {"total", "count", "anomaly", "budget", "advice", "transactions", "overview"}


def build_calls(intents: list[str], months: list[str], month: str | None,
                category: str | None, merchant: str | None) -> list[dict]:
    """의도별 조회 계획. 같은 호출은 한 번만(중복 제거)."""
    calls: list[dict] = []

    def add(tool: str, **args):
        call = {"tool": tool, "args": {k: v for k, v in args.items() if v is not None}}
        if call not in calls:
            calls.append(call)

    for intent in intents:
        if intent in ("total", "count"):
            add("spending_summary", month=month, category=category, merchant=merchant)
            if month and not category and not merchant:
                add("category_breakdown", month=month)
        elif intent == "compare":
            add("compare_months", month_a=months[0], month_b=months[1])
        elif intent == "anomaly":
            add("detect_anomalies", month=month)
        elif intent == "subscription":
            add("find_subscriptions")
        elif intent in ("budget", "advice"):
            add("budget_status", month=month)
            if intent == "advice" and month:
                add("category_breakdown", month=month)
        elif intent == "transactions":
            add("list_transactions", month=month, category=category, merchant=merchant, limit=10)
        elif intent == "overview":
            add("category_breakdown", month=month)
            add("budget_status", month=month)
        elif intent == "budget_change":
            add("budget_status", month=REF_MONTH)
    return calls


@traceable(name="plan_node")
async def plan_node(state: AgentState, deps: Deps) -> dict:
    parsed = state["parsed"]
    available = deps.catalog.get("months", [])
    cost = state.get("cost_usd", 0.0)
    events = list(state["events"])

    intents = list(parsed["intents"])
    if not intents:
        # 코드가 의도를 못 찾았을 때만 LLM에게 보충을 맡긴다. 그래도 없으면 '이번 달 개요'
        procedure = await deps.mcp.get_prompt("spending_analysis_prompt",
                                              {"question": state["query"], "month": REF_MONTH})
        result, usage = await asyncio.to_thread(deps.fast_llm.plan, state["query"], procedure)
        intents = result["intents"] or ["overview"]
        cost = add_cost(state, usage)
        events.append({"type": "IntentsFilled", "by": "llm", "intents": intents})

    months = list(parsed["months"])
    if "compare" in intents and len(months) < 2:
        months = available[-2:]   # "지출이 늘었어?"처럼 달이 없으면 데이터의 최근 두 달
    month = months[-1] if months else None
    if month is None and not parsed["all_period"] and any(i in NEEDS_MONTH for i in intents) \
            and not parsed["merchant"]:
        month = REF_MONTH   # "이상한 결제 있어?"처럼 달이 없으면 기준 달(이번 달)
    missing = [m for m in months + ([month] if month else []) if m not in available]

    base = {"intents": intents, "months": months, "month": month, "category": parsed["category"],
            "merchant": parsed["merchant"], "budget_change": parsed["budget_change"], "cost_usd": cost}
    if missing:
        events.append({"type": "PlanCreated", "intents": intents, "missing_months": missing})
        return {**base, "missing_months": list(dict.fromkeys(missing)), "calls": [], "events": events}
    bc = parsed["budget_change"]
    if bc and (not bc["category"] or not bc["amount"]):
        what = "어느 카테고리" if not bc["category"] else "얼마로"
        events.append({"type": "PlanCreated", "intents": intents, "clarify": what})
        return {**base, "clarify_reason": what, "calls": [], "events": events}

    calls = build_calls(intents, months, month, parsed["category"], parsed["merchant"])
    events.append({"type": "PlanCreated", "intents": intents, "month": month,
                   "calls": [c["tool"] for c in calls]})
    return {**base, "calls": calls, "events": events}


@traceable(name="no_data_node")
async def no_data_node(state: AgentState, deps: Deps) -> dict:
    """데이터에 없는 달을 물으면 0원이라고 답하지 않고 정직하게 안내(LLM 호출 없음)."""
    available = deps.catalog.get("months", [])
    final = (f"{', '.join(state['missing_months'])} 카드 내역은 데이터에 없어서 답할 수 없어요. "
             f"조회할 수 있는 기간: {available[0]} ~ {available[-1]}.")
    return {"final": final, "events": state["events"] + [{"type": "Finalize", "pipeline": "no-data"}]}


@traceable(name="clarify_node")
async def clarify_node(state: AgentState, deps: Deps) -> dict:
    """예산을 바꾸라는데 카테고리나 금액이 없으면 되묻는다(엉뚱한 예산을 바꾸지 않게)."""
    final = (f"예산을 {state['clarify_reason']} 바꿀지 알려 주세요. 예: \"식비 예산 50만원으로 바꿔줘\" "
             f"(카테고리: {', '.join(deps.catalog.get('categories', []))})")
    return {"final": final, "events": state["events"] + [{"type": "Finalize", "pipeline": "clarify"}]}
