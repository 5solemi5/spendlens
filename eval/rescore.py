"""저장된 결과를 현재 채점 규칙(score.py, expected.py)으로 다시 채점한다 — 모델을 다시 부르지 않는다.
채점 규칙을 고친 뒤 Before/After를 같은 기준으로 맞출 때 쓴다.

사용법: python eval/rescore.py before_naive after_agent
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import expected   # noqa: E402
from score import score, summarize   # noqa: E402


def main():
    exps, truth = expected.expectations(), expected.all_true_numbers()
    cases = {c["id"]: c for c in json.loads((HERE / "queries.json").read_text(encoding="utf-8"))}
    for label in sys.argv[1:]:
        path = HERE / "results" / f"{label}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data["rows"]:
            # 예산 변경 결과: 에이전트는 실행 당시 기록(budget_after), 나이브는 바꿀 수단이 없어 원래 예산
            r.update(score(cases[r["id"]], exps[r["id"]], r["reply"], r.get("budget_after", expected.budget()), truth))
        data["summary"] = summarize(data["rows"])
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(label, json.dumps(data["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
