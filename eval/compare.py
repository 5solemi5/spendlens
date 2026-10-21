"""두 결과 파일(eval/results/<label>.json)을 Markdown 표로 비교한다.

사용법: python eval/compare.py before_naive after_agent
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
LABELS = [("accuracy", "정답률(12문항)"), ("answers_with_invented_amounts", "지어낸 금액이 섞인 답변 수"),
          ("false_action_claims", "하지 않은 조치를 했다고 답한 수"), ("total_s", "총 소요(초)"),
          ("avg_s", "질문당 평균(초)"), ("prompt_tokens", "프롬프트 토큰 합계"), ("cost_usd", "가상 비용(USD)")]


def main():
    a, b = (json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8")) for name in sys.argv[1:3])
    print(f"| 지표 | {a['label']} | {b['label']} |\n|---|---|---|")
    for key, name in LABELS:
        print(f"| {name} | {a['summary'].get(key, '-')} | {b['summary'].get(key, '-')} |")
    print(f"\n| # | 유형 | 질문 | {a['label']} | {b['label']} |\n|---|---|---|---|---|")
    for ra, rb in zip(a["rows"], b["rows"]):
        cell = lambda r: ("O" if r["ok"] else "X") + (f" (지어낸 금액 {', '.join(f'{v:,}' for v in r['invented'][:2])})"
                                                      if r["invented"] else "") + (" (거짓 실행)" if r["false_action"] else "")
        print(f"| {ra['id']} | {ra['kind']} | {ra['query'][:24]} | {cell(ra)} | {cell(rb)} |")


if __name__ == "__main__":
    main()
