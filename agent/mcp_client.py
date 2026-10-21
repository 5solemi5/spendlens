"""MCP 클라이언트 — mcp_server.py를 subprocess(stdio)로 1번 띄워 서버 수명 동안 재사용한다.

과제1(운영 에이전트)의 클라이언트와 같은 구조다. 서버가 하나라 '어느 서버가 resource를 갖고
있나'를 찾는 단계는 빼고, Tool 호출 결과(JSON 텍스트)를 dict로 바꿔 돌려주는 일만 한다.
"""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from langsmith import traceable
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "mcp_server.py"
CALL_TIMEOUT = float(os.environ.get("MCP_CALL_TIMEOUT", "30"))   # 넘으면 asyncio.TimeoutError → with_retry가 재시도


class MCPClient:
    def __init__(self, server_script: Path = SERVER_SCRIPT):
        self._script = server_script
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None
        # stdio 하나를 여러 요청이 동시에 쓰지 않게. 그래서 research의 '병렬' 호출도 MCP 앞에서는 차례로 처리된다
        # (계산이 밀리초 단위라 체감 차이는 없다 — 원격 MCP 서버라면 세션을 여러 개 두는 편이 낫다)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=sys.executable, args=[str(self._script)],
                                       env={**os.environ, "FASTMCP_LOG_LEVEL": "ERROR"})
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack, self.session = None, None

    @traceable(run_type="tool", name="mcp.call_tool")
    async def call_tool(self, name: str, arguments: dict) -> dict:
        # 시간 제한이 없으면 서버가 멈췄을 때 영원히 기다리고, with_retry(TimeoutError만 재시도)도 동작할 기회가 없다
        async with self._lock:
            result = await asyncio.wait_for(self.session.call_tool(name, arguments), CALL_TIMEOUT)
        # SDK 버전에 따라 필드 이름이 다르다(2.x: is_error, 1.x: isError). 새 이름을 먼저 본다
        is_error = getattr(result, "is_error", None)
        if is_error is None:
            is_error = getattr(result, "isError", False)
        if is_error:
            raise ValueError(result.content[0].text)
        return json.loads(result.content[0].text)

    @traceable(run_type="tool", name="mcp.read_resource")
    async def read_resource(self, uri: str) -> str:
        async with self._lock:
            result = await self.session.read_resource(uri)
        return result.contents[0].text

    @traceable(run_type="tool", name="mcp.get_prompt")
    async def get_prompt(self, name: str, arguments: dict) -> str:
        async with self._lock:
            result = await self.session.get_prompt(name, arguments)
        return result.messages[0].content.text
