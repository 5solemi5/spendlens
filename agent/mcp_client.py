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


class MCPClient:
    def __init__(self, server_script: Path = SERVER_SCRIPT):
        self._script = server_script
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None
        self._lock = asyncio.Lock()   # stdio 하나를 여러 요청이 동시에 쓰지 않게

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
        async with self._lock:
            result = await self.session.call_tool(name, arguments)
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
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
