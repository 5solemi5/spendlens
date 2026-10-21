"""서버 통합 테스트 — 실제 MCP subprocess + fake LLM으로 FastAPI를 프로세스 안에서 띄운다.
(SPENDLENS_RUNTIME_DIR를 임시 폴더로 줘서 MCP 서버 프로세스도 실제 data/runtime을 건드리지 않게 한다)"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SPENDLENS_RUNTIME_DIR", str(tmp_path / "rt"))   # MCP 자식 프로세스에 전달됨
    import server
    monkeypatch.setattr(server, "SqliteSessionStore", lambda: _store(tmp_path))   # session.db도 임시 파일로
    with TestClient(server.app) as c:
        yield c, server


def _store(tmp_path):
    from agent.session_store import SqliteSessionStore
    return SqliteSessionStore(tmp_path / "s.db")


def test_health_and_chat(client):
    c, _ = client
    assert c.get("/health").json()["months"] == ["2026-07", "2026-08", "2026-09"]
    r = c.post("/chat", json={"message": "9월에 이상한 결제 있어?", "thread_id": "t1"}).json()
    assert r["status"] == "done" and "389,000원" in r["reply"] and r["metadata"]["tools"] == ["detect_anomalies"]


def test_budget_change_approve_flow_and_cleanup(client):
    c, server = client
    r = c.post("/chat", json={"message": "카페 예산 10만원으로 바꿔줘", "thread_id": "t2"}).json()
    assert r["status"] == "pending_approval"
    assert c.post("/chat/approve", json={"thread_id": "t2", "approved": True}).json()["reply"].count("✅") == 1
    assert c.post("/chat/approve", json={"thread_id": "t2", "approved": True}).status_code == 404
    assert server.app.state.pending == {} and len(server.app.state.graph.checkpointer.storage) == 0
    r = c.post("/chat", json={"message": "9월 예산 넘은 카테고리 알려줘", "thread_id": "t3"}).json()
    assert "카페 78,400원 / 100,000원" in r["reply"]   # 승인된 예산이 MCP 서버 쪽에 저장돼 반영됨


def test_stream_refuse(client):
    c, _ = client
    body = c.get("/chat/stream", params={"message": "코인 투자 추천해줘", "thread_id": "t4"}).text
    assert '"route": "refuse"' in body and body.rstrip().endswith("data: [DONE]")
