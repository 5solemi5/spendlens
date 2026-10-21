"""Before — '나이브 방식': 카드 내역 CSV 전체를 LLM 프롬프트에 넣고 바로 답하게 한다.

에이전트 없이 LLM만 쓰는 가장 흔한 방식(ChatGPT에 명세서 붙여 넣기)이다. 도구·검증·분류 없이
모델이 직접 세고 더한다. 같은 질문 12개, 같은 채점(eval/score.py)으로 에이전트(After)와 비교한다.

사용법: python eval/naive_baseline.py [--model qwen3:8b] [--think] [--label before_naive]
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import expected   # noqa: E402
from score import score, summarize   # noqa: E402

import httpx   # noqa: E402

from agent.ollama_llm import OllamaLLM   # noqa: E402

SYSTEM = ("당신은 개인 가계부 비서다. 아래 카드 내역(CSV)과 카테고리별 월 예산을 보고 사용자의 질문에 "
          "한국어로 정확하게 답하라. 금액은 원 단위로 쓴다. 날짜 형식은 YYYY-MM-DD.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="ollama", choices=["ollama", "openai"])
    ap.add_argument("--model", default=None, help="기본: ollama=qwen3:8b, openai=gpt-4o-mini")
    ap.add_argument("--think", action="store_true", help="qwen3 thinking 켜기(느리지만 계산이 나아지는지 확인용)")
    ap.add_argument("--label", default="before_naive")
    ap.add_argument("--ids", help="일부 질문만 (예: 1,2,5,6) — thinking 모드처럼 느릴 때")
    args = ap.parse_args()

    csv_text = (HERE.parent / "data" / "transactions.csv").read_text(encoding="utf-8")
    budget = json.dumps(expected.budget(), ensure_ascii=False)
    if args.backend == "openai":   # 같은 방식(CSV 통째로)을 OpenAI 모델로 — 키는 .env의 OPENAI_API_KEY
        from dotenv import load_dotenv
        load_dotenv(HERE.parent / ".env")
        from agent.openai_llm import OpenAILLM
        args.model = args.model or "gpt-4o-mini"
        llm = OpenAILLM(args.model, usd_per_1k_tokens=0.005)
    else:
        args.model = args.model or "qwen3:8b"
        llm = OllamaLLM(args.model, usd_per_1k_tokens=0.005, think=args.think, num_ctx=16384)
    exps, truth = expected.expectations(), expected.all_true_numbers()
    rows = []
    ids = {int(i) for i in args.ids.split(",")} if args.ids else None
    for case in json.loads((HERE / "queries.json").read_text(encoding="utf-8")):
        if ids and case["id"] not in ids:
            continue
        user = f"## 카드 내역\n{csv_text}\n## 카테고리별 월 예산(원)\n{budget}\n\n## 질문\n{case['query']}"
        t0 = time.perf_counter()
        try:
            reply, usage = llm._chat(SYSTEM, user)
        except httpx.TimeoutException:   # 시간 초과도 결과로 남긴다(답을 못 한 것 = 오답)
            reply, usage = "[시간 초과]", {"prompt_tokens": 0, "usd": 0.0}
        elapsed = round(time.perf_counter() - t0, 1)
        s = score(case, exps[case["id"]], reply, expected.budget(), truth)   # 나이브는 예산을 바꿀 수단이 없다
        rows.append({"id": case["id"], "query": case["query"], "kind": case["kind"], "elapsed_s": elapsed,
                     "prompt_tokens": usage["prompt_tokens"], "cost_usd": usage["usd"], "reply": reply, **s})
        print(f"[{elapsed:>6}s] #{case['id']} {'O' if s['ok'] else 'X'} invented={s['invented'][:3]} "
              f"{reply.strip()[:60]!r}", flush=True)
    out = {"label": args.label, "model": args.model, "think": args.think, "summary": summarize(rows), "rows": rows}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{args.label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
