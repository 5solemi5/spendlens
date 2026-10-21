"""write(답변 작성) · validate(금액 근거 검사) · finalize(마무리) 노드."""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import Deps
from ..facts import format_facts
from ..grounding import check_grounding
from .state import AgentState, add_usage

MAX_VALIDATION_ATTEMPTS = 3


@traceable(name="write_node")
async def write_node(state: AgentState, deps: Deps) -> dict:
    attempt = state.get("validation_attempts", 0) + 1
    facts_text = format_facts(state.get("facts", []), state.get("guides"), state.get("classified"))
    writer = get_stream_writer()
    draft, usage = await deps.quality_llm.write(
        state["query"], facts_text, attempt, state.get("validation_feedback"),
        on_token=lambda piece: writer({"type": "AnswerToken", "attempt": attempt, "delta": piece}))
    return {"draft": draft, "facts_text": facts_text, "last_prompt": usage.get("prompt"),
            **add_usage(state, usage),
            "events": state["events"] + [{"type": "DraftWritten", "attempt": attempt, "length": len(draft)}]}


@traceable(name="validate_node")
async def validate_node(state: AgentState, deps: Deps) -> dict:
    """답변의 금액·비율·건수가 수집된 사실에 있는지 코드로 검사. 틀리면 이유를 붙여 다시 쓰게 한다."""
    draft = state["draft"]
    attempts = state.get("validation_attempts", 0) + 1
    problems = []
    if len(draft.strip()) < 15:
        problems.append("답변이 너무 짧습니다. 질문에 대한 핵심 숫자를 포함해 답하세요.")
    issues = check_grounding(draft, state.get("facts_text", ""))
    problems += issues
    ok = not problems
    verdict = "합격" if ok else "불합격"
    if not ok and attempts >= MAX_VALIDATION_ATTEMPTS:   # 무한 재작성 방지 — 통과시키되 경고를 남긴다
        ok, verdict = True, "합격(최대 시도 도달 — 경고와 함께 통과)"
    event = {"type": "Validation", "attempt": attempts, "verdict": verdict}
    if issues:
        event["grounding_issues"] = issues
    return {"validation_attempts": attempts, "validation_feedback": None if ok else " ".join(problems),
            "grounding_issues": issues, "events": state["events"] + [event]}


@traceable(name="finalize_node")
async def finalize_node(state: AgentState, deps: Deps) -> dict:
    final = state["draft"].rstrip()
    notes = []
    if state.get("classified"):
        notes.append("※ 규칙에 없던 가맹점을 자동 분류했어요: "
                     + ", ".join(f"{m}→{c}" for m, c in state["classified"].items()))
    if state.get("grounding_issues"):
        notes.append("※ 자동 검증에서 근거를 확인하지 못한 숫자가 있어요: " + " / ".join(state["grounding_issues"]))
    if notes:
        final += "\n\n" + "\n".join(notes)
    return {"final": final, "events": state["events"] + [{"type": "Finalize", "pipeline": "spending"}]}
