"""LLM_BACKEND=fake — 결정론적 가짜 LLM. 네트워크 없이 그래프 전체를 테스트하기 위한 것.

실제 모델과 같은 인터페이스를 갖고, 일부러 '흔한 실수'를 재현한다:
  - write 1차 초안은 금액을 직접 더한 '틀린 합계'를 넣는다 → validate가 반려하는지 확인
"""
import re

from langsmith import traceable

from .query import INTENT_PATTERNS

FAKE_CATEGORIES = {"하이디라오": "식비", "블루보틀": "카페", "다이소": "쇼핑", "쏘카": "교통", "클라이밍": "문화"}


class FakeLLM:
    def __init__(self, name: str, usd_per_1k_tokens: float):
        self.name = name
        self.usd_per_1k = usd_per_1k_tokens

    def _usage(self, prompt: str, completion: str) -> dict:
        tokens = (len(prompt) + len(completion)) // 4 + 1
        return {"model": self.name, "tokens": tokens, "prompt_tokens": len(prompt) // 4,
                "usd": round(tokens / 1000 * self.usd_per_1k, 6)}


class FastLLM(FakeLLM):
    @traceable(run_type="llm", name="fake_fast.route")
    def route(self, query: str) -> tuple[dict, dict]:
        spending = any(re.search(p, query) for p in INTENT_PATTERNS.values())
        result = {"route": "spending" if spending else "chat"}
        return result, self._usage(query, str(result))

    @traceable(run_type="llm", name="fake_fast.plan")
    def plan(self, query: str, procedure: str) -> tuple[dict, dict]:
        return {"intents": ["total"]}, self._usage(query + procedure, "total")

    @traceable(run_type="llm", name="fake_fast.classify")
    def classify(self, merchants: list[str]) -> tuple[dict, dict]:
        out = {m: next((c for key, c in FAKE_CATEGORIES.items() if key in m), "기타") for m in merchants}
        return out, self._usage(str(merchants), str(out))

    @traceable(run_type="llm", name="fake_fast.chat")
    async def chat(self, query: str, history: list[dict], on_token=None) -> tuple[str, dict]:
        reply = "안녕하세요! SpendLens예요. 월별 지출, 구독, 이상 결제, 예산을 물어보세요."
        for msg in reversed(history):
            m = (re.search(r"제 이름은 (\S+?)입니다", msg.get("content", ""))
                 or re.search(r"^- 이름: (\S+)", msg.get("content", ""), re.M))
            if m and "이름" in query:
                reply = f"{m.group(1)}님이라고 말씀하셨어요."
                break
        else:
            if (m := re.search(r"제 이름은 (\S+?)입니다", query)):
                reply = f"반가워요, {m.group(1)}님!"
        if on_token is not None:
            on_token(reply)
        return reply, self._usage(query, reply)

    @traceable(run_type="llm", name="fake_fast.summarize")
    def summarize(self, prev_summary: str, messages: list[dict]) -> tuple[str, dict]:
        lines = [l for l in prev_summary.splitlines() if l.strip()]
        lines += [f"- 문의: {m['content'][:40]}" for m in messages if m["role"] == "user"]
        summary = "\n".join(lines[-5:])
        return summary, self._usage(str(messages), summary)


class QualityLLM(FakeLLM):
    @traceable(run_type="llm", name="fake_quality.write")
    async def write(self, query: str, facts_text: str, attempt: int, feedback: str | None,
                    on_token=None) -> tuple[str, dict]:
        lines = [l[2:] for l in facts_text.splitlines() if l.startswith("- ")]
        draft = "\n".join(f"{i}) {l}" for i, l in enumerate(lines, 1)) or "데이터에서 확인되지 않습니다."
        if attempt == 1 and lines:
            # 흔한 실수 재현: 사실에 있는 금액 두 개를 '직접 더한' 합계를 덧붙인다
            amounts = [int(a.replace(",", "")) for a in re.findall(r"(\d{1,3}(?:,\d{3})+)원", facts_text)]
            if len(amounts) >= 2:
                draft += f"\n두 금액을 합치면 {amounts[0] + amounts[1]:,}원입니다."
        if on_token is not None:
            on_token(draft)
        return draft, self._usage(query + facts_text + str(feedback), draft)
