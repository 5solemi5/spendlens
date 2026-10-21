"""pytest 공통 설정 — 프로젝트 루트를 import 경로에 넣고, 실행 중 바뀌는 파일(data/runtime)을
테스트마다 임시 폴더로 돌린다. 테스트가 실제 예산·분류 저장 파일을 건드리지 않게."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ.setdefault("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    from agent import ledger
    monkeypatch.setattr(ledger, "RUNTIME_DIR", tmp_path / "runtime")
    return tmp_path / "runtime"


class StubMCP:
    """mcp_client.MCPClient와 같은 메서드를 가진 가짜 — subprocess 없이 ledger 함수를 바로 부른다."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        from agent import ledger
        self.calls.append((name, dict(arguments)))
        return getattr(ledger, name)(**arguments)

    async def read_resource(self, uri):
        topic = uri.rsplit("/", 1)[-1]
        return (ROOT / "data" / "guides" / f"{topic}.md").read_text(encoding="utf-8")

    async def get_prompt(self, name, arguments):
        return f"질문: {arguments['question']}\n기준 월: {arguments['month']}"


class MemorySession:
    def __init__(self):
        self.rows, self.summaries = {}, {}

    def load(self, thread_id):
        return list(self.rows.get(thread_id, []))

    def append(self, thread_id, role, content):
        self.rows.setdefault(thread_id, []).append({"role": role, "content": content})

    def load_summary(self, thread_id):
        return self.summaries.get(thread_id, ("", 0))

    def save_summary(self, thread_id, summary, covered):
        self.summaries[thread_id] = (summary, covered)


def make_deps(hitl=False):
    from agent import ledger
    from agent.deps import Deps
    from agent.fake_llm import FastLLM, QualityLLM
    return Deps(fast_llm=FastLLM("fast-stub", 0.00015), quality_llm=QualityLLM("quality-stub", 0.005),
                mcp=StubMCP(), session_store=MemorySession(), hitl=hitl, catalog=ledger.data_catalog())


@pytest.fixture
def fake_graph():
    """fake LLM + 가짜 MCP로 만든 실제 LangGraph (HITL 끔). 반환: (graph, deps)"""
    from agent.graph import build_graph
    deps = make_deps(hitl=False)
    return build_graph(deps), deps
