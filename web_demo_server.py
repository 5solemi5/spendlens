"""web_demo_server.py — SpendLens와 브라우저 채팅창으로 대화하는 데모 (과제1 코드 재사용).

web_chat.html 한 장을 같은 출처(origin)로 띄우고, /chat·/chat/stream·/chat/approve 요청을 백엔드
(server.py, 기본 8200)로 그대로 중계(프록시)한다 — 브라우저의 CORS 제약 없이 대화하기 위한 얇은 층.

실행:
    python3 web_demo_server.py        # http://localhost:8700 에서 채팅 화면
"""
import json
import os
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# 백엔드 주소·프론트 포트는 환경변수로 바꿀 수 있다
BACKEND = os.environ.get("BACKEND_URL", f"http://127.0.0.1:{os.environ.get('BACKEND_PORT', '8200')}")
FRONT_PORT = int(os.environ.get("FRONT_PORT", "8700"))
HERE = Path(__file__).parent

app = FastAPI()


@app.get("/")
async def index():
    # 수정한 HTML이 브라우저 캐시 때문에 반영 안 되던 문제 방지
    return FileResponse(HERE / "web_chat.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
async def proxy_health():
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BACKEND}/health")
    return JSONResponse(r.json(), status_code=r.status_code)


@app.post("/chat")
async def proxy_chat(req: Request):
    body = await req.body()
    async with httpx.AsyncClient(timeout=600.0) as client:   # 실모델 답변은 수십 초 걸릴 수 있다
        r = await client.post(f"{BACKEND}/chat", content=body,
                              headers={"content-type": "application/json"})
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get("/chat/stream")
async def proxy_stream(message: str, thread_id: str = "web-demo"):
    async def relay():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET", f"{BACKEND}/chat/stream",
                params={"message": message, "thread_id": thread_id},
            ) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream")


@app.post("/chat/approve")
async def proxy_approve(req: Request):   # 승인/거절 (JSON)
    body = await req.body()
    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.post(f"{BACKEND}/chat/approve", content=body,
                              headers={"content-type": "application/json"})
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get("/chat/approve/stream")
async def proxy_approve_stream(thread_id: str, approved: bool, comment: str = ""):
    """백엔드의 상태 코드를 그대로 전달한다 — 승인 대기가 없으면(404) 화면이 '연결 끊김'이 아니라
    실제 이유를 보여 줄 수 있게. (처음엔 무조건 200 스트림으로 감싸서 404가 빈 스트림이 됐다)"""
    client = httpx.AsyncClient(timeout=None)
    upstream = await client.send(client.build_request(
        "GET", f"{BACKEND}/chat/approve/stream",
        params={"thread_id": thread_id, "approved": str(approved).lower(), "comment": comment}), stream=True)
    if upstream.status_code != 200:
        body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        return JSONResponse(json.loads(body or b"{}"), status_code=upstream.status_code)

    async def relay():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(relay(), media_type="text/event-stream")


if __name__ == "__main__":
    print(f"브라우저에서 http://localhost:{FRONT_PORT} 을 열어보세요 (백엔드: {BACKEND})")
    # 0.0.0.0이면 같은 네트워크의 다른 기기에서도 접속된다 — 데모 PC 밖으로 열 이유가 없어 127.0.0.1로
    uvicorn.run(app, host="127.0.0.1", port=FRONT_PORT)
