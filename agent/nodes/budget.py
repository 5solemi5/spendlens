"""예산 변경 — propose_change(제안 작성) → approval(사람 승인 후에만 set_budget 실행).

과제1의 HITL은 '위험한 문장을 답변에 넣을지'를 물었다. 여기서는 실제로 '저장되는 조치'(예산 값을
바꾸는 MCP Tool 호출)를 사람이 승인해야만 실행한다. 승인 전에는 아무것도 바뀌지 않는다.
"""
from langgraph.types import interrupt
from langsmith import traceable

from ..deps import Deps
from ..facts import won
from .state import AgentState


@traceable(name="propose_change_node")
async def propose_change_node(state: AgentState, deps: Deps) -> dict:
    """제안문은 LLM 없이 코드가 쓴다 — 금액이 틀릴 여지를 없앤다."""
    bc = state["budget_change"]
    status = next(f["result"] for f in state["facts"] if f["tool"] == "budget_status")
    item = next((i for i in status["items"] if i["category"] == bc["category"]), None)
    before = item["budget"] if item else None
    spent = f" {status['month']} {bc['category']} 지출은 {won(item['spent'])}입니다." if item else ""
    draft = (f"{bc['category']} 월 예산을 {won(before) if before is not None else '(설정 없음)'}에서 "
             f"{won(bc['amount'])}으로 바꾸려고 합니다.{spent}")
    return {"draft": draft, "approval": {"category": bc["category"], "before": before, "after": bc["amount"]},
            "events": state["events"] + [{"type": "ChangeProposed", **bc, "before": before}]}


@traceable(name="approval_node")
async def approval_node(state: AgentState, deps: Deps) -> dict:
    change = state["approval"]
    if deps.hitl:
        # ⚠️ interrupt() 앞에는 부작용(저장·외부 호출)을 두지 않는다 — 재개 때 이 노드가 처음부터 다시 실행된다
        decision = interrupt({"type": "ApprovalRequired", "actions": [{
            "action": "예산 변경",
            "sentence": f"{change['category']} 예산 {won(change['before']) if change['before'] is not None else '-'}"
                        f" → {won(change['after'])}"}], "draft": state["draft"]})
        approved, comment = bool(decision.get("approved")), decision.get("comment", "")
    else:
        approved, comment = True, "HITL_APPROVAL=0 — 자동 승인"
    if approved:
        result = await deps.mcp.call_tool("set_budget", {"category": change["category"], "amount": change["after"]})
        draft = state["draft"] + f"\n\n✅ 승인되어 {result['category']} 예산을 {won(result['after'])}으로 바꿨습니다."
    else:
        draft = state["draft"] + "\n\n⛔ 승인되지 않아 예산을 바꾸지 않았습니다."
    if comment:
        draft += f" (메모: {comment})"
    return {"draft": draft, "approval": {**change, "approved": approved},
            "events": state["events"] + [{"type": "ApprovalDecided", "approved": approved,
                                          "actions": ["예산 변경"]}]}
