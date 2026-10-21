"""LLM_BACKEND=ollama — 로컬 Ollama 실모델 (fast=qwen3:0.6b, quality=qwen3:8b).

fast는 짧고 정형적인 일(라우팅, 의도 보충, 가맹점 분류, 잡담, 대화 요약), quality는 최종 답변 작성.
과제1에서 실측한 대로 qwen3는 thinking이 기본으로 켜져 느리므로 요청마다 "think"를 명시한다.
비용(cost_usd)은 '가상 단가 × 실측 토큰 수' — 로컬이라 실제 과금은 0이지만 같은 잣대로 비교하기 위함.
"""
import json
import os

import httpx
from langsmith import traceable

from .ledger import CATEGORIES
from .memory import SUMMARIZE_SYSTEM, chat_messages, summarize_prompt
from .query import INTENT_PATTERNS

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "0") == "1"
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "180"))

INTENTS = list(INTENT_PATTERNS)
ROUTE_SCHEMA = {"type": "object", "properties": {"route": {"type": "string", "enum": ["spending", "chat"]}},
                "required": ["route"]}
PLAN_SCHEMA = {"type": "object", "properties": {"intents": {"type": "array", "items": {"type": "string", "enum": INTENTS}}},
               "required": ["intents"]}
CLASSIFY_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"merchant": {"type": "string"},
                                     "category": {"type": "string", "enum": CATEGORIES}},
    "required": ["merchant", "category"]}}}, "required": ["items"]}

WRITE_SYSTEM = ("당신은 개인 가계부 비서다. '수집된 사실'만 근거로 사용자 질문에 한국어로 답하라.\n"
                "- 금액·건수·비율은 수집된 사실에 적힌 값을 그대로 인용하라. 직접 더하거나 빼거나 반올림하지 마라.\n"
                "- 사실에 없는 기간·카테고리·가맹점은 언급하지 마라. 모르면 '데이터에서 확인되지 않습니다'라고 써라.\n"
                "- 절약 방법은 '절약 가이드' 사실에 있는 내용만 근거로 1~3개 제안하라.\n"
                "- 투자·대출 같은 금융 상품 조언은 하지 마라.\n"
                "- 3~8줄로 간결하게. 핵심 숫자를 먼저 말하라.")


class OllamaLLM:
    def __init__(self, model: str, usd_per_1k_tokens: float, think: bool = OLLAMA_THINK, num_ctx: int | None = None):
        self.name = f"ollama:{model}"
        self.model = model
        self.usd_per_1k = usd_per_1k_tokens
        self.think = think
        self.num_ctx = num_ctx   # 긴 프롬프트(나이브 기준선: CSV 통째로)를 넣을 때만 늘린다

    def _payload(self, messages: list[dict], stream: bool) -> dict:
        options = {"temperature": 0.0}
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        return {"model": self.model, "messages": messages, "stream": stream,
                "think": self.think, "options": options}

    def _usage(self, data: dict) -> dict:
        prompt_tokens = data.get("prompt_eval_count") or 0
        tokens = prompt_tokens + (data.get("eval_count") or 0)
        return {"model": self.name, "tokens": tokens, "prompt_tokens": prompt_tokens,
                "usd": round(tokens / 1000 * self.usd_per_1k, 6)}

    def _chat(self, system: str, user: str, schema: dict | None = None) -> tuple[str, dict]:
        """동기 호출 — 그래프 노드가 asyncio.to_thread로 감싸 부른다(이벤트 루프를 막지 않게)."""
        payload = self._payload([{"role": "system", "content": system},
                                 {"role": "user", "content": user}], stream=False)
        if schema is not None:
            payload["format"] = schema
        resp = httpx.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"], self._usage(data)

    async def _chat_stream(self, messages: list[dict], on_token=None) -> tuple[str, dict]:
        """사용자에게 보이는 답변 전용 — 토큰을 받는 즉시 on_token으로 넘겨 SSE로 흘려보낸다."""
        chunks, usage = [], {"model": self.name, "tokens": 0, "prompt_tokens": 0, "usd": 0.0}
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            async with client.stream("POST", OLLAMA_URL, json=self._payload(messages, stream=True)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        chunks.append(piece)
                        if on_token is not None:
                            on_token(piece)
                    if data.get("done"):
                        usage = self._usage(data)
        usage["prompt"] = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages)
        return "".join(chunks), usage


def _json(content: str) -> dict:
    try:
        out = json.loads(content)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


class OllamaFastLLM(OllamaLLM):
    @traceable(run_type="llm", name="ollama_fast.route")
    def route(self, query: str) -> tuple[dict, dict]:
        system = ("당신은 가계부 비서의 라우터다. 사용자의 지출·카드 내역·예산·구독·절약에 관한 질문이면 "
                  "route=spending, 인사·자기소개·잡담이면 route=chat.")
        content, usage = self._chat(system, query, schema=ROUTE_SCHEMA)
        route = _json(content).get("route")
        return {"route": route if route in ("spending", "chat") else "chat"}, usage

    @traceable(run_type="llm", name="ollama_fast.plan")
    def plan(self, query: str, procedure: str) -> tuple[dict, dict]:
        """코드가 의도를 하나도 못 찾았을 때만 불린다 — 의도 목록만 보충한다."""
        system = ("당신은 가계부 분석 계획 노드다. 질문에 답하려면 어떤 분석이 필요한지 intents로 골라라. "
                  "total=합계, count=횟수, compare=월 비교, anomaly=이상 결제, subscription=정기 결제, "
                  "budget=예산 대비, advice=절약 방법, transactions=결제 목록.")
        content, usage = self._chat(system, f"{procedure}\n\n질문: {query}", schema=PLAN_SCHEMA)
        intents = [i for i in _json(content).get("intents", []) if i in INTENTS]
        return {"intents": list(dict.fromkeys(intents))}, usage

    @traceable(run_type="llm", name="ollama_fast.classify")
    def classify(self, merchants: list[str]) -> tuple[dict, dict]:
        system = ("당신은 카드 가맹점 분류기다. 각 가맹점 이름을 보고 카테고리 하나를 골라라: "
                  f"{', '.join(CATEGORIES)}. 음식점=식비, 커피전문점=카페, 생활용품점=쇼핑, "
                  "차량 공유=교통, 운동·공연·서점=문화. 확실하지 않으면 기타.")
        content, usage = self._chat(system, "\n".join(merchants), schema=CLASSIFY_SCHEMA)
        found = {i.get("merchant"): i.get("category") for i in _json(content).get("items", [])
                 if isinstance(i, dict)}
        # 모델이 빠뜨리거나 이름을 바꿔 적은 가맹점은 '기타' — 분류 대상은 코드가 정한 목록 그대로
        return {m: found.get(m) if found.get(m) in CATEGORIES else "기타" for m in merchants}, usage

    @traceable(run_type="llm", name="ollama_fast.chat")
    async def chat(self, query: str, history: list[dict], on_token=None) -> tuple[str, dict]:
        system = ("당신은 개인 가계부 비서 SpendLens다. 한두 문장의 한국어로 친절하게 답하라. "
                  "지출 질문이 아니면 가볍게 답하고, 무엇을 물어볼 수 있는지(월별 지출, 구독, 이상 결제, 예산) 안내하라. "
                  "'[사용자 정보]'에 적힌 이름·소속은 사용자가 직접 밝힌 확정 사실이다. 사용자와 당신을 혼동하지 마라.")
        return await self._chat_stream(chat_messages(system, history, query), on_token=on_token)

    @traceable(run_type="llm", name="ollama_fast.summarize")
    def summarize(self, prev_summary: str, messages: list[dict]) -> tuple[str, dict]:
        content, usage = self._chat(SUMMARIZE_SYSTEM, summarize_prompt(prev_summary, messages))
        return content.strip(), usage


class OllamaQualityLLM(OllamaLLM):
    @traceable(run_type="llm", name="ollama_quality.write")
    async def write(self, query: str, facts_text: str, attempt: int, feedback: str | None,
                    on_token=None) -> tuple[str, dict]:
        return await self._chat_stream(
            [{"role": "system", "content": WRITE_SYSTEM},
             {"role": "user", "content": build_write_prompt(query, facts_text, feedback)}],
            on_token=on_token)


def build_write_prompt(query: str, facts_text: str, feedback: str | None) -> str:
    """write 프롬프트 — openai_llm.py도 같이 쓴다."""
    user = f"## 사용자 질문\n{query}\n\n## 수집된 사실\n{facts_text or '(없음)'}"
    if feedback:
        user += f"\n\n## 이전 답변이 검증에서 반려된 이유 (반드시 고쳐서 다시 쓰기)\n{feedback}"
    return user
