"""advise — 절약 가이드 RAG. 분석 결과(예산 초과·증가폭 1위·이상 결제)를 검색 힌트로 쓴다."""
import asyncio

from langsmith import traceable

from ..deps import Deps
from ..guide_retriever import GuideRetriever
from .state import AgentState

RETRIEVER = GuideRetriever()   # 가이드 인덱스는 프로세스당 1번


def hints_from_facts(facts: list[dict], category: str | None) -> list[str]:
    """질문에 카테고리가 없어도 '문제가 된 곳'의 가이드를 찾도록 힌트를 만든다."""
    hints = [category] if category else []
    for f in facts:
        r = f["result"]
        if f["tool"] == "budget_status":
            hints += [i["category"] for i in r["over"]]
        elif f["tool"] == "compare_months" and r["diffs"] and r["diffs"][0]["diff"] > 0:
            hints.append(r["diffs"][0]["category"])
        elif f["tool"] == "detect_anomalies" and r["count"]:
            hints += ["이상결제"] + [a["type"] for a in r["anomalies"]]
        elif f["tool"] == "find_subscriptions":
            hints.append("구독")
    return list(dict.fromkeys(hints))


@traceable(name="advise_node")
async def advise_node(state: AgentState, deps: Deps) -> dict:
    """절약 방법을 물었거나, 예산 초과·이상 결제가 있으면 관련 가이드를 붙인다."""
    hints = hints_from_facts(state.get("facts", []), state.get("category"))
    wants = "advice" in state["intents"] or any(i in state["intents"] for i in ("budget", "anomaly", "subscription"))
    if not wants or not (hints or "advice" in state["intents"]):
        return {"guides": [], "events": state["events"] + [{"type": "AdviceSkipped"}]}
    guides = await asyncio.to_thread(RETRIEVER.retrieve, state["query"], hints)
    return {"guides": guides, "events": state["events"] + [
        {"type": "GuidesRetrieved", "topics": [g["topic"] for g in guides], "hints": hints}]}
