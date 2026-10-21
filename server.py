"""SpendLens — FastAPI 백엔드. 과제1(운영 에이전트) 서버와 같은 구조다.

- lifespan에서 MCP 연결·LLM·그래프를 프로세스당 1번만 만들고 모든 요청이 공유한다
- mcp_server.py를 subprocess(stdio)로 띄워 계산 엔진 Tool을 쓴다
- POST /chat, GET /chat/stream(SSE) — 그래프 진행 이벤트와 답변 토큰을 실시간으로
- 대화 이력은 SQLite(session.db), 오래된 턴은 요약 메모리(agent/memory.py)
- Human-in-the-loop: 예산 변경은 그래프가 approval 노드에서 멈추고(interrupt) 승인을 기다린다
    /chat → {"status": "pending_approval"} / /chat/stream → ApprovalRequired 이벤트
    POST /chat/approve, GET /chat/approve/stream 으로 승인·거절하면 멈춘 곳부터 이어서 실행
  요청마다 체크포인트 키(run_key)를 새로 만들고, 끝난 요청의 체크포인트는 지운다.

포트: BACKEND_PORT(기본 8200) — 과제1 서버(8100)와 동시에 띄워도 겹치지 않게.
"""
import json
import os
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_* / OPENAI_API_KEY — import보다 먼저

from fastapi import FastAPI, HTTPException   # noqa: E402
from fastapi.responses import StreamingResponse   # noqa: E402
from langgraph.types import Command   # noqa: E402
from langsmith import traceable   # noqa: E402
from pydantic import BaseModel   # noqa: E402

from agent.deps import Deps   # noqa: E402
from agent.fake_llm import FastLLM, QualityLLM   # noqa: E402
from agent.graph import build_graph   # noqa: E402
from agent.mcp_client import MCPClient   # noqa: E402
from agent.memory import load_history   # noqa: E402
from agent.session_store import SqliteSessionStore   # noqa: E402


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ApproveRequest(BaseModel):
    thread_id: str = "default"
    approved: bool
    comment: str = ""


def _build_llms():
    """LLM_BACKEND=fake(기본, 결정론) | ollama(로컬 실모델) | openai(실제 API, 과금)."""
    backend = os.environ.get("LLM_BACKEND", "fake")
    if backend == "ollama":
        from agent.ollama_llm import OllamaFastLLM, OllamaQualityLLM
        return backend, (OllamaFastLLM(os.environ.get("OLLAMA_FAST_MODEL", "qwen3:0.6b"), 0.00015),
                         OllamaQualityLLM(os.environ.get("OLLAMA_QUALITY_MODEL", "qwen3:8b"), 0.005))
    if backend == "openai":
        from agent.openai_llm import OpenAIFastLLM, OpenAIQualityLLM
        return backend, (OpenAIFastLLM(os.environ.get("OPENAI_FAST_MODEL", "gpt-4o-mini"), 0.00015),
                         OpenAIQualityLLM(os.environ.get("OPENAI_QUALITY_MODEL", "gpt-4o"), 0.005))
    return backend, (FastLLM("fast-model-stub", 0.00015), QualityLLM("quality-model-stub", 0.005))


@asynccontextmanager
async def lifespan(app: FastAPI):
    mcp = MCPClient()
    await mcp.start()
    backend, (fast, quality) = _build_llms()
    deps = Deps(fast_llm=fast, quality_llm=quality, mcp=mcp, session_store=SqliteSessionStore(),
                hitl=os.environ.get("HITL_APPROVAL", "1") == "1",
                catalog=await mcp.call_tool("data_catalog", {}))   # 달·가맹점 목록은 시작할 때 1번
    app.state.backend, app.state.deps = backend, deps
    app.state.graph = build_graph(deps)
    app.state.pending = {}   # thread_id → {"run_key", "message"} : 승인 대기 중인 요청
    yield
    await mcp.stop()
    deps.session_store.close()
    try:   # 종료 전 LangSmith 전송 마무리
        from langchain_core.tracers.langchain import wait_for_all_tracers
        wait_for_all_tracers()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    d = app.state.deps
    return {"status": "ok", "llm_backend": app.state.backend, "fast_llm": d.fast_llm.name,
            "quality_llm": d.quality_llm.name, "hitl": d.hitl, "months": d.catalog.get("months")}


def _metadata(result: dict) -> dict:
    return {"route": result.get("route"), "intents": result.get("intents", []),
            "month": result.get("month"), "category": result.get("category"),
            "merchant": result.get("merchant"),
            "tools": [f["tool"] for f in result.get("facts", [])],
            "classified": result.get("classified", {}),
            "guides": [g["topic"] for g in result.get("guides", [])],
            "validation_attempts": result.get("validation_attempts", 0),
            "grounding_issues": result.get("grounding_issues", []),
            "approval": result.get("approval"), "memory": result.get("memory"),
            "facts": result.get("facts_text", ""),        # 채점·디버깅용 근거 텍스트
            "cost_usd": result.get("cost_usd", 0.0), "llm_backend": app.state.backend}


def _config(run_key: str) -> dict:
    return {"configurable": {"thread_id": run_key}}


def _graph_input(message: str, thread_id: str, history: list[dict]) -> dict:
    return {"query": message, "thread_id": thread_id, "history": history, "events": [], "cost_usd": 0.0}


def _interrupt_payload(result: dict) -> dict | None:
    intr = result.get("__interrupt__")
    return intr[0].value if intr else None


def _get_pending(thread_id: str) -> dict:
    """꺼내지 않고 보기만 — 재개가 실패해도 승인 대기가 남아 다시 시도할 수 있다."""
    pending = app.state.pending.get(thread_id)
    if pending is None:
        raise HTTPException(404, f"승인 대기 중인 요청이 없습니다: thread_id={thread_id}")
    return pending


def _finish_run(thread_id: str, run_key: str) -> None:
    """끝난 요청의 승인 대기·체크포인트 정리 (지우지 않으면 요청 수만큼 메모리가 늘어난다)."""
    if app.state.pending.get(thread_id, {}).get("run_key") == run_key:
        app.state.pending.pop(thread_id, None)
    if app.state.graph.checkpointer is not None:
        app.state.graph.checkpointer.delete_thread(run_key)


def _save_turn(thread_id: str, message: str, final: str) -> None:
    store = app.state.deps.session_store
    store.append(thread_id, "user", message)
    store.append(thread_id, "assistant", final)


def _response(result: dict) -> dict:
    payload = _interrupt_payload(result)
    if payload:
        return {"status": "pending_approval", "approval": payload,
                "reply": "⏸ 예산 변경은 승인이 필요합니다. 승인 또는 거절해 주세요.",
                "events": result.get("events", []), "metadata": _metadata(result)}
    return {"status": "done", "reply": result["final"], "events": result.get("events", []),
            "metadata": _metadata(result)}


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str) -> dict:
    deps = app.state.deps
    history, memory = await load_history(deps.session_store, deps.fast_llm, thread_id)
    app.state.pending.pop(thread_id, None)   # 승인 대기 중에 새 질문이 오면 이전 대기는 버린다
    run_key = f"{thread_id}:{uuid.uuid4().hex[:8]}"
    result = await app.state.graph.ainvoke(_graph_input(message, thread_id, history), config=_config(run_key))
    result = {**result, "memory": memory}
    if _interrupt_payload(result):
        app.state.pending[thread_id] = {"run_key": run_key, "message": message}
        return result
    _finish_run(thread_id, run_key)
    _save_turn(thread_id, message, result["final"])
    return result


@app.post("/chat")
async def chat(req: ChatRequest):
    return _response(await _handle_chat(req.message, req.thread_id))


@app.post("/chat/approve")
async def approve(req: ApproveRequest):
    pending = _get_pending(req.thread_id)
    result = await app.state.graph.ainvoke(Command(resume={"approved": req.approved, "comment": req.comment}),
                                           config=_config(pending["run_key"]))
    _finish_run(req.thread_id, pending["run_key"])
    _save_turn(req.thread_id, pending["message"], result["final"])
    return _response(result)


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _guarded(body):
    """예외가 나도 연결을 그냥 끊지 않고 Error 이벤트 + [DONE]으로 끝낸다(화면이 ⏳에 멈추지 않게)."""
    async def gen():
        try:
            async for chunk in body:
                yield chunk
        except Exception as e:
            yield _sse({"type": "Error", "message": f"{type(e).__name__}: {e}"})
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


async def _stream_graph(graph_input, run_key: str, thread_id: str, message: str, seen: int = 0):
    """그래프 실행을 SSE로 중계. 새 질문과 승인 후 재개가 같은 코드를 쓴다.
    seen: 이미 보낸 이벤트 수(재개 때 앞부분을 다시 보내지 않으려고)."""
    final, last_prompt = "", None
    async for mode, payload in app.state.graph.astream(graph_input, config=_config(run_key),
                                                       stream_mode=["updates", "custom"]):
        if mode == "custom":            # 노드 안에서 흘려보낸 답변 토큰
            yield _sse(payload)
            continue
        if "__interrupt__" in payload:  # approval 노드에서 멈춤 → 결정을 기다린다
            app.state.pending[thread_id] = {"run_key": run_key, "message": message}
            yield _sse({**payload["__interrupt__"][0].value, "thread_id": thread_id})
            return
        for node_name, delta in payload.items():
            for ev in (delta.get("events") or [])[seen:]:
                yield _sse({**ev, "node": node_name})
            if delta.get("events"):
                seen = len(delta["events"])
            final = delta.get("final") or final
            last_prompt = delta.get("last_prompt") or last_prompt
    yield _sse({"type": "FinalAnswer", "reply": final, "prompt": last_prompt})
    _finish_run(thread_id, run_key)
    _save_turn(thread_id, message, final)


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default"):
    deps = app.state.deps

    async def body():
        history, memory = await load_history(deps.session_store, deps.fast_llm, thread_id)
        if memory["updated"]:
            yield _sse({"type": "MemorySummarized", **memory})
        app.state.pending.pop(thread_id, None)
        async for chunk in _stream_graph(_graph_input(message, thread_id, history),
                                         f"{thread_id}:{uuid.uuid4().hex[:8]}", thread_id, message):
            yield chunk

    return _guarded(body())


@app.get("/chat/approve/stream")
async def approve_stream(thread_id: str, approved: bool, comment: str = ""):
    pending = _get_pending(thread_id)

    async def body():
        snapshot = await app.state.graph.aget_state(_config(pending["run_key"]))
        async for chunk in _stream_graph(Command(resume={"approved": approved, "comment": comment}),
                                         pending["run_key"], thread_id, pending["message"],
                                         len(snapshot.values.get("events", []))):
            yield chunk

    return _guarded(body())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("BACKEND_PORT", "8200")), log_level="warning")
