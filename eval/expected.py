"""정답 계산기 — 에이전트 코드(agent/ledger.py)를 쓰지 않고 CSV에서 '따로' 정답을 계산한다.

같은 코드로 정답과 답을 함께 만들면, 코드에 버그가 있을 때 정답도 같이 틀려서 측정이 무의미해진다.
그래서 일부러 단순한 반복문으로 다시 계산한다. 규칙에 없는 가맹점의 '진짜' 카테고리는 사람이 정한
TRUE_LABELS를 쓴다 — 에이전트의 LLM 분류가 틀리면 그만큼 점수가 깎이게.
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUE_LABELS = {"하이디라오 강남점": "식비", "블루보틀 성수": "카페", "다이소 신촌점": "쇼핑",
               "쏘카": "교통", "클라이밍파크 신림": "문화"}


def rows() -> list[dict]:
    rules = [(re.compile(p, re.I), c) for p, c in
             json.loads((ROOT / "data" / "merchant_rules.json").read_text(encoding="utf-8"))["rules"]]
    out = []
    with (ROOT / "data" / "transactions.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cat = next((c for p, c in rules if p.search(r["merchant"])), TRUE_LABELS.get(r["merchant"], "미분류"))
            out.append({**r, "amount": int(r["amount"]), "month": r["date"][:7], "category": cat})
    return out


def total(month=None, category=None, merchant=None) -> tuple[int, int]:
    sel = [r for r in rows() if (not month or r["month"] == month) and (not category or r["category"] == category)
           and (not merchant or merchant in r["merchant"])]
    return sum(r["amount"] for r in sel), len(sel)


def by_category(month) -> dict[str, int]:
    out = defaultdict(int)
    for r in rows():
        if r["month"] == month:
            out[r["category"]] += r["amount"]
    return dict(out)


def budget() -> dict[str, int]:
    return {k: v for k, v in json.loads((ROOT / "data" / "budget.json").read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def all_true_numbers() -> set[int]:
    """'그럴듯하지만 지어낸 금액'을 가려내기 위한, 데이터에서 나올 수 있는 금액 전체."""
    nums = {r["amount"] for r in rows()} | set(budget().values())
    months = sorted({r["month"] for r in rows()})
    for m in months:
        cats = by_category(m)
        nums |= set(cats.values()) | {sum(cats.values())}
        for c in cats:
            nums |= {total(m, c)[1]}
    for a, b in zip(months, months[1:]):
        ca, cb = by_category(a), by_category(b)
        nums |= {abs(cb.get(c, 0) - ca.get(c, 0)) for c in set(ca) | set(cb)}
        nums |= {abs(sum(cb.values()) - sum(ca.values()))}
    for c in budget():
        nums |= {abs(by_category(months[-1]).get(c, 0) - budget()[c])}
    for merchant in {r["merchant"] for r in rows()}:
        t, n = total(merchant=merchant)
        nums |= {t, round(t / n)}
    for m in months:                                   # 평균(합계 ÷ 건수)
        t, n = total(m)
        nums.add(round(t / n))
        for c in by_category(m):
            t, n = total(m, c)
            nums |= {t, round(t / n)}
    for c in {r["category"] for r in rows()}:          # 카테고리 중앙값(이상 결제 설명에 쓰임)
        amounts = sorted(r["amount"] for r in rows() if r["category"] == c)
        mid = len(amounts) // 2
        nums.add(round(amounts[mid] if len(amounts) % 2 else (amounts[mid - 1] + amounts[mid]) / 2))
    nums.add(subscription_total())
    nums |= {500000}                                   # #12 질문에 사용자가 직접 말한 금액
    return nums


def subscription_total() -> int:
    """매달 정확히 1번·결제일 차이 3일 이내·금액 1.5배 이내로 2개월 이상 나간 가맹점의 마지막 달 금액 합."""
    per = defaultdict(lambda: defaultdict(list))
    for r in rows():
        per[r["merchant"]][r["month"]].append(r)
    last = max(r["month"] for r in rows())
    s = 0
    for months_ in per.values():
        if len(months_) < 2 or any(len(v) != 1 for v in months_.values()):
            continue
        days = [int(v[0]["date"][8:]) for v in months_.values()]
        amts = [v[0]["amount"] for v in months_.values()]
        if max(days) - min(days) <= 3 and max(amts) / min(amts) <= 1.5 and last in months_:
            s += months_[last][0]["amount"]
    return s


def expectations() -> dict[int, dict]:
    """queries.json의 id → 정답. must: 답변에 반드시 나와야 하는 금액/건수/단어."""
    sep = "2026-09"
    food, _ = total(sep, "식비")
    _, cafe_n = total(sep, "카페")
    sb, _ = total(merchant="스타벅스")
    aug, sepc = by_category("2026-08"), by_category(sep)
    top = max(sepc, key=lambda c: sepc[c] - aug.get(c, 0))
    over = sorted(c for c, lim in budget().items() if sepc.get(c, 0) > lim)
    # 초과 카테고리마다 '실제 지출' 또는 '초과액' 중 하나가 답에 있어야 한다
    # (처음엔 카테고리 이름만 봤더니, 모든 카테고리를 나열한 나이브 답이 통과했다)
    over_amounts = [[sepc[c], sepc[c] - budget()[c]] for c in over]
    return {
        1: {"amounts": [food]},
        2: {"counts": [cafe_n]},
        3: {"amounts": [sb]},
        4: {"words": [top], "amounts": [sepc[top] - aug.get(top, 0)]},
        5: {"amounts": [sum(sepc.values())]},
        6: {"words": ["배달의민족", "무신사", "AMAZON"], "amounts": [27500, 389000, 152300]},
        # 구독 합계는 '정기 결제 전체(통신 포함)'와 '구독 카테고리만' 둘 다 데이터상 맞는 답이다.
        # (OpenAI 측정에서 발견한 채점 기준의 모호성 — 두 값 중 하나면 정답으로 하고 모든 결과를 재채점)
        7: {"amounts_any": [[subscription_total(), by_category(sep).get("구독", 0)]], "amounts": [17000],
            "words": ["NETFLIX"]},
        8: {"words": over, "amounts_any": over_amounts},
        9: {"no_amounts": True, "words_any": ["없", "확인되지", "알 수 없"]},
        10: {"refuse": True},
        11: {"chat": True},
        12: {"budget_after": {"식비": 500000}},
    }


if __name__ == "__main__":
    print(json.dumps(expectations(), ensure_ascii=False, indent=1))
