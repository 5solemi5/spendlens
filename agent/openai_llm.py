"""LLM_BACKEND=openai — 실제 OpenAI API (fast=gpt-4o-mini, quality=gpt-4o). ⚠️ 과금된다.

프롬프트·후처리(라우팅·의도·분류·작성 규칙)는 ollama_llm.py와 완전히 같고, 'HTTP로 모델을 부르는 부분'
(_chat, _chat_stream)만 다르다. 그래서 OllamaFastLLM/OllamaQualityLLM의 메서드를 그대로 물려받고
전송 계층만 이 클래스로 덮어쓴다(다중 상속: OpenAILLM이 앞에 있으므로 _chat은 이쪽 것이 쓰인다).
"""
import asyncio
import json
import os

import httpx

from .ollama_llm import OllamaFastLLM, OllamaQualityLLM

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "120"))


class OpenAILLM:
    def __init__(self, model: str, usd_per_1k_tokens: float):
        self.name = f"openai:{model}"
        self.model = model
        self.usd_per_1k = usd_per_1k_tokens
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def _request(self, messages: list[dict], schema: dict | None = None) -> tuple[str, dict]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다 — .env 또는 환경변수로 지정하세요.")
        payload = {"model": self.model, "messages": messages, "temperature": 0}
        if schema is not None:
            # JSON 모드는 '유효한 JSON'만 보장하므로 스키마를 지시문으로 함께 준다(후처리는 코드가 다시 검사)
            payload["response_format"] = {"type": "json_object"}
            payload["messages"] = messages[:-1] + [{
                "role": "user", "content": messages[-1]["content"]
                + f"\n\nJSON 객체로만 답하라. 스키마: {json.dumps(schema, ensure_ascii=False)}"}]
        resp = httpx.post(OPENAI_URL, json=payload, timeout=OPENAI_TIMEOUT,
                          headers={"Authorization": f"Bearer {self.api_key}"})
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        return data["choices"][0]["message"]["content"], {
            "model": self.name, "tokens": tokens, "prompt_tokens": usage.get("prompt_tokens", 0),
            "usd": round(tokens / 1000 * self.usd_per_1k, 6)}

    def _chat(self, system: str, user: str, schema: dict | None = None) -> tuple[str, dict]:
        return self._request([{"role": "system", "content": system}, {"role": "user", "content": user}], schema)

    async def _chat_stream(self, messages: list[dict], on_token=None) -> tuple[str, dict]:
        """스트리밍 대신 완성된 답을 한 번에 넘긴다(인터페이스만 맞춤)."""
        content, usage = await asyncio.to_thread(self._request, messages)
        if on_token is not None:
            on_token(content)
        usage["prompt"] = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages)
        return content, usage


class OpenAIFastLLM(OpenAILLM, OllamaFastLLM):
    pass


class OpenAIQualityLLM(OpenAILLM, OllamaQualityLLM):
    pass
