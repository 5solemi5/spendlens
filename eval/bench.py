"""After — 에이전트 서버(/chat)에 같은 질문 12개를 보내고 같은 규칙으로 채점한다.

예산 변경(#12)은 승인 대기가 오면 자동 승인한다(사람 대신). 실행 전 data/runtime을 비워
가맹점 분류·예산 변경을 '처음 상태'에서 시작한다(--keep-runtime으로 끌 수 있음).

사용법: python eval/bench.py --url http://127.0.0.1:8200 --label after_agent
"""
import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import expected   # noqa: E402
from score import score, summarize   # noqa: E402

from agent import ledger   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8200")
    ap.add_argument("--label", default="after_agent")
    ap.add_argument("--keep-runtime", action="store_true")
    args = ap.parse_args()
    if not args.keep_runtime:
        shutil.rmtree(ledger.RUNTIME_DIR, ignore_errors=True)

    exps, truth = expected.expectations(), expected.all_true_numbers()
    run = uuid.uuid4().hex[:6]
    rows = []
    for case in json.loads((HERE / "queries.json").read_text(encoding="utf-8")):
        thread = f"bench-{run}-{case['id']}"
        t0 = time.perf_counter()
        res = httpx.post(f"{args.url}/chat", json={"message": case["query"], "thread_id": thread}, timeout=600).json()
        approval = res.get("status") == "pending_approval"
        if approval:
            res = httpx.post(f"{args.url}/chat/approve", json={"thread_id": thread, "approved": True,
                                                                "comment": "bench 자동 승인"}, timeout=600).json()
        elapsed = round(time.perf_counter() - t0, 1)
        meta = res.get("metadata", {})
        s = score(case, exps[case["id"]], res["reply"], ledger.load_budget(), truth)
        rows.append({"id": case["id"], "query": case["query"], "kind": case["kind"], "elapsed_s": elapsed,
                     "cost_usd": meta.get("cost_usd", 0.0), "prompt_tokens": meta.get("prompt_tokens", 0),
                     "approval": approval, "reply": res["reply"],
                     "metadata": meta, "events": res.get("events", []), **s})
        print(f"[{elapsed:>6}s] #{case['id']} {'O' if s['ok'] else 'X'} invented={s['invented'][:3]} "
              f"route={meta.get('route')} tools={meta.get('tools')} {res['reply'].strip()[:50]!r}", flush=True)
    out = {"label": args.label, "url": args.url, "summary": summarize(rows), "rows": rows}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{args.label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
