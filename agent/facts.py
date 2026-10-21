"""Tool 결과 → 답변 작성 모델에게 줄 '수집된 사실' 텍스트.

금액은 "123,400원"처럼 쉼표 형식으로 미리 적어 준다. 모델이 숫자를 다시 쓰거나 더할 필요가
없게 — 합계·차이·비율은 이미 계산된 값만 넘긴다(계산은 ledger가 했다).
"""


def won(n: int) -> str:
    return f"{n:,}원"


def _summary(args: dict, r: dict) -> str:
    target = " ".join(x for x in (r.get("category"), r.get("merchant")) if x) or "전체"
    return (f"- {r['month']} {target} 지출: 합계 {won(r['total'])}, {r['count']}건, "
            f"평균 {won(r['average'])}")


def _breakdown(args: dict, r: dict) -> str:
    cats = ", ".join(f"{c['category']} {won(c['total'])}({c['count']}건)" for c in r["categories"])
    return f"- {r['month']} 카테고리별 지출(큰 순): {cats} / 전체 합계 {won(r['total'])}"


def _compare(args: dict, r: dict) -> str:
    def one(d):
        pct = f", {d['change_pct']:+}%" if d["change_pct"] is not None else ""
        return f"{d['category']} {won(d['before'])}→{won(d['after'])} ({d['diff']:+,}원{pct})"
    rows = [d for d in r["diffs"] if not args.get("category") or d["category"] == args["category"]]
    return (f"- {r['from']}→{r['to']} 카테고리별 증감(증가액 큰 순): {'; '.join(one(d) for d in rows)} / "
            f"전체 {won(r['total_before'])}→{won(r['total_after'])} ({r['total_after'] - r['total_before']:+,}원)")


def _transactions(args: dict, r: dict) -> str:
    items = ", ".join(f"{t['date'][5:].replace('-', '/')} {t['merchant']} {won(t['amount'])}"
                      for t in r["transactions"])
    return f"- 결제 목록(금액 큰 순, {r['count']}건): {items or '없음'}"


def _anomalies(args: dict, r: dict) -> str:
    if not r["anomalies"]:
        return f"- {r['month']} 이상 결제: 없음"
    return "\n".join(f"- {r['month']} 이상 결제[{a['type']}]: {a['date']} {a['merchant']} {won(a['amount'])} — {a['reason']}"
                     for a in r["anomalies"])


def _subscriptions(args: dict, r: dict) -> str:
    def one(s):
        note = []
        if "price_change" in s:
            pc = s["price_change"]
            note.append(f"{pc['month']}에 {won(pc['from'])}→{won(pc['to'])} 인상")
        if "started" in s:
            note.append(f"{s['started']}부터 시작")
        if not s["active"]:
            note.append(f"{r['latest_month']}에는 결제 없음")
        extra = f", {', '.join(note)}" if note else ""
        return f"{s['merchant']}({s['category']}) {won(s['amount'])} 매달 {s['day']}일{extra}"
    return (f"- 정기 결제 {r['count']}개, 월 합계 {won(r['monthly_total'])}: "
            + "; ".join(one(s) for s in r["subscriptions"]))


def _budget(args: dict, r: dict) -> str:
    over = ", ".join(f"{i['category']} {won(i['spent'])} / 예산 {won(i['budget'])} ({i['used_pct']}%, "
                     f"{won(-i['remaining'])} 초과)" for i in r["over"]) or "없음"
    ok = ", ".join(f"{i['category']} {won(i['spent'])} / {won(i['budget'])} ({i['used_pct']}%)"
                   for i in r["items"] if not i["over"])
    return f"- {r['month']} 예산 초과: {over}\n- {r['month']} 예산 이내: {ok}"


def _uncategorized(args: dict, r: dict) -> str:
    return f"- 미분류 가맹점: {', '.join(r['merchants']) or '없음'}"


FORMATTERS = {"spending_summary": _summary, "category_breakdown": _breakdown, "compare_months": _compare,
              "list_transactions": _transactions, "detect_anomalies": _anomalies,
              "find_subscriptions": _subscriptions, "budget_status": _budget,
              "list_uncategorized": _uncategorized}


def format_facts(facts: list[dict], guides: list[dict] | None = None, classified: dict | None = None) -> str:
    lines = [FORMATTERS[f["tool"]](f["args"], f["result"]) for f in facts if f["tool"] in FORMATTERS]
    if classified:
        lines.append("- 이번에 새로 분류한 가맹점: " + ", ".join(f"{m}→{c}" for m, c in classified.items()))
    for g in guides or []:
        lines.append(f"- 절약 가이드[{g['topic']}]: " + " / ".join(g["lines"]))
    return "\n".join(lines)
