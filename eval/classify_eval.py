"""가맹점 분류 정확도 — fast(qwen3:0.6b) vs quality(qwen3:8b).

규칙에 없는 가맹점 5곳(실제 데이터) + 헷갈리기 쉬운 가상 가맹점 10곳의 '정답 카테고리'를 사람이 정해 두고,
두 모델이 몇 개를 맞히는지 잰다. 분류 결과는 저장돼 계속 쓰이므로(한 번 틀리면 계속 틀림) 정확도가 중요하다.

사용법: python eval/classify_eval.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import expected   # noqa: E402

from agent.ollama_llm import OllamaFastLLM, OllamaQualityLLM   # noqa: E402

EXTRA = {"을지로 노가리골목 호프": "식비", "빽다방 신촌점": "카페", "홈플러스 익스프레스": "장보기",
         "티맵 대리운전": "교통", "에이블리": "쇼핑", "왓챠": "구독", "알뜰모바일 요금": "통신",
         "롯데시네마 월드타워": "문화", "연세튼튼정형외과": "의료", "마라탕 하오츠": "식비"}


def main():
    truth = {**expected.TRUE_LABELS, **EXTRA}
    merchants = list(truth)
    out = {}
    for name, llm in [("fast qwen3:0.6b", OllamaFastLLM("qwen3:0.6b", 0.00015)),
                      ("quality qwen3:8b", OllamaQualityLLM("qwen3:8b", 0.005))]:
        t0 = time.perf_counter()
        labels, usage = llm.classify(merchants)
        wrong = {m: f"{labels[m]} (정답 {truth[m]})" for m in merchants if labels[m] != truth[m]}
        out[name] = {"accuracy": f"{len(merchants) - len(wrong)}/{len(merchants)}", "wrong": wrong,
                     "seconds": round(time.perf_counter() - t0, 1), "tokens": usage["tokens"]}
        print(name, json.dumps(out[name], ensure_ascii=False))
    (HERE / "results" / "classify_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
