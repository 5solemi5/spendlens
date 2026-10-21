"""그래프 통합 테스트 — fake LLM + 가짜 MCP로 실제 LangGraph를 끝까지 돌린다(Ollama·서버 불필요)."""
import asyncio

from langgraph.types import Command

from agent import ledger
from tests.conftest import make_deps


def run(graph, query, history=None, config=None):
    return asyncio.run(graph.ainvoke({"query": query, "thread_id": "t", "history": history or [],
                                      "events": [], "cost_usd": 0.0}, config=config))


def tools(result):
    return [e["tool"] for e in result["events"] if e["type"] == "ToolCalled"]


def test_total_classifies_unknown_merchants_first(fake_graph):
    graph, deps = fake_graph
    result = run(graph, "9월 식비 얼마 썼어?")
    assert result["classified"]["하이디라오 강남점"] == "식비"   # 분류가 조회보다 먼저
    expected = ledger.spending_summary("2026-09", "식비")["total"]   # 분류 반영 후 계산
    assert f"{expected:,}원" in result["final"]
    verdicts = [e["verdict"] for e in result["events"] if e["type"] == "Validation"]
    assert verdicts == ["불합격", "합격"]                          # fake 1차 초안의 '직접 더한 합계'를 반려
    assert "하이디라오 강남점→식비" in result["final"]


def test_compare_uses_tool_not_llm_math(fake_graph):
    graph, _ = fake_graph
    result = run(graph, "8월보다 9월에 가장 많이 늘어난 카테고리는?")
    assert tools(result) == ["compare_months"]
    assert "쇼핑 98,000원→" in result["final"]


def test_anomaly_question_gets_guide(fake_graph):
    graph, _ = fake_graph
    result = run(graph, "9월에 이상한 결제 있어?")
    assert "중복 결제 의심" in result["final"] and "389,000원" in result["final"]
    assert result["guides"][0]["topic"] == "이상결제"


def test_subscriptions_total(fake_graph):
    graph, _ = fake_graph
    result = run(graph, "내 구독 서비스 정리해 줘. 매달 얼마 나가?")
    assert "116,680원" in result["final"] and "13,500원→17,000원" in result["final"]


def test_out_of_scope_refused_without_tools(fake_graph):
    graph, deps = fake_graph
    result = run(graph, "비트코인 사도 될까?")
    assert result["route"] == "refuse" and "조언은 드리지 않아요" in result["final"]
    assert deps.mcp.calls == []


def test_chat_remembers_name(fake_graph):
    graph, _ = fake_graph
    history = [{"role": "user", "content": "제 이름은 민수입니다"}, {"role": "assistant", "content": "반가워요"}]
    assert "민수" in run(graph, "제 이름이 뭐였죠?", history)["final"]


def test_month_without_data_is_not_zero(fake_graph):
    graph, deps = fake_graph
    result = run(graph, "10월 지출은?")
    assert "2026-10" in result["final"] and "0원" not in result["final"] and deps.mcp.calls == []


def test_budget_change_without_amount_asks_back(fake_graph):
    graph, _ = fake_graph
    result = run(graph, "식비 예산 바꿔줘")
    assert "얼마로" in result["final"] and ledger.load_budget()["식비"] == 400000


def _hitl_graph():
    from agent.graph import build_graph
    deps = make_deps(hitl=True)
    return build_graph(deps), deps


def test_budget_change_needs_approval_then_applies():
    graph, deps = _hitl_graph()
    cfg = {"configurable": {"thread_id": "b1"}}
    first = run(graph, "식비 예산 50만원으로 바꿔줘", config=cfg)
    assert "__interrupt__" in first and ledger.load_budget()["식비"] == 400000   # 승인 전엔 그대로
    assert first["__interrupt__"][0].value["actions"][0]["sentence"] == "식비 예산 400,000원 → 500,000원"
    done = asyncio.run(graph.ainvoke(Command(resume={"approved": True}), config=cfg))
    assert ledger.load_budget()["식비"] == 500000 and "✅" in done["final"]


def test_budget_change_rejected_keeps_budget():
    graph, deps = _hitl_graph()
    cfg = {"configurable": {"thread_id": "b2"}}
    run(graph, "카페 예산 10만원으로 올려줘", config=cfg)
    done = asyncio.run(graph.ainvoke(Command(resume={"approved": False, "comment": "다음 달에"}), config=cfg))
    assert ledger.load_budget()["카페"] == 80000 and "⛔" in done["final"] and "다음 달에" in done["final"]
    assert not any(name == "set_budget" for name, _ in deps.mcp.calls)
