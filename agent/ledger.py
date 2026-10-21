"""가계부 계산 엔진 — 모든 '숫자'는 여기서 코드로 계산한다.

LLM은 덧셈을 틀린다. 268건을 프롬프트에 넣고 "9월 식비 합계"를 물으면 그럴듯하지만 틀린
숫자를 낸다(eval/naive_baseline.py로 실측). 그래서 합계·비교·탐지는 전부 이 모듈의 순수
함수가 하고, MCP 서버(mcp_server.py)가 이 함수들을 Tool로 내보내며, LLM은 결과를 '말로
옮기는' 일만 한다.

데이터 파일:
  data/transactions.csv     카드 내역 (scripts/make_data.py가 생성)
  data/merchant_rules.json  가맹점 → 카테고리 규칙
  data/budget.json          카테고리별 월 예산 (원본)
  data/runtime/             실행 중에 바뀌는 값 — LLM이 분류한 가맹점, 승인된 예산 변경 (git 제외)
"""
import csv
import json
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("SPENDLENS_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
RUNTIME_DIR = Path(os.environ.get("SPENDLENS_RUNTIME_DIR", DATA_DIR / "runtime"))

CATEGORIES = ["식비", "카페", "장보기", "교통", "쇼핑", "구독", "통신", "문화", "의료", "기타"]
UNCATEGORIZED = "미분류"
DUPLICATE_WINDOW_S = 300      # 같은 가맹점·같은 금액이 5분 안에 두 번 → 중복 결제 의심
OUTLIER_MULTIPLIER = 3        # 그 카테고리 평소 결제(중앙값)의 3배 이상
OUTLIER_MIN_AMOUNT = 100_000  # …이면서 10만 원 이상일 때만 (커피 1.5천 원의 3배 같은 잡음 제외)
SUBSCRIPTION_MAX_RATIO = 1.5  # 정기 결제로 볼 금액 흔들림 상한 (가격 인상 13,500→17,000은 1.26배라 포함)


# ---------------------------------------------------------------- 파일 읽기·쓰기

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_rules() -> list[tuple[re.Pattern, str]]:
    raw = _read_json(DATA_DIR / "merchant_rules.json", {"rules": []})["rules"]
    return [(re.compile(pattern, re.I), category) for pattern, category in raw]


def load_overrides() -> dict[str, str]:
    """LLM이 분류해 저장한 가맹점 → 카테고리."""
    return _read_json(RUNTIME_DIR / "category_overrides.json", {})


def categorize(merchant: str, rules=None, overrides=None) -> str:
    """규칙 → 저장된 분류 → 미분류 순서. 규칙이 먼저인 이유: 사람이 정한 규칙이 LLM 판단보다 우선."""
    for pattern, category in rules if rules is not None else load_rules():
        if pattern.search(merchant):
            return category
    return (overrides if overrides is not None else load_overrides()).get(merchant, UNCATEGORIZED)


def load_transactions() -> list[dict]:
    """CSV → dict 목록. amount는 int, overseas는 bool, category는 categorize()로 붙인다."""
    rules, overrides = load_rules(), load_overrides()
    with (DATA_DIR / "transactions.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["amount"] = int(r["amount"])
        r["overseas"] = r["overseas"] == "Y"
        r["month"] = r["date"][:7]
        r["category"] = categorize(r["merchant"], rules, overrides)
    return rows


def months() -> list[str]:
    return sorted({r["month"] for r in load_transactions()})


def data_catalog() -> dict:
    """에이전트가 질문을 해석할 때 쓰는 목록: 데이터가 있는 달, 가맹점 이름, 카테고리."""
    rows = load_transactions()
    return {"months": sorted({r["month"] for r in rows}), "merchants": sorted({r["merchant"] for r in rows}),
            "categories": CATEGORIES}


# ---------------------------------------------------------------- 조회·합계

def _filter(rows, month=None, category=None, merchant=None):
    out = rows
    if month:
        out = [r for r in out if r["month"] == month]
    if category:
        out = [r for r in out if r["category"] == category]
    if merchant:
        m = merchant.lower()
        out = [r for r in out if m in r["merchant"].lower()]
    return out


def spending_summary(month: str | None = None, category: str | None = None,
                     merchant: str | None = None) -> dict:
    """조건에 맞는 결제의 합계·건수·평균. month=None이면 전체 기간."""
    rows = _filter(load_transactions(), month, category, merchant)
    total = sum(r["amount"] for r in rows)
    return {"month": month or "전체", "category": category, "merchant": merchant,
            "total": total, "count": len(rows),
            "average": round(total / len(rows)) if rows else 0}


def category_breakdown(month: str) -> dict:
    """그 달의 카테고리별 합계(큰 순서)와 전체 합계."""
    rows = _filter(load_transactions(), month)
    by = defaultdict(lambda: {"total": 0, "count": 0})
    for r in rows:
        by[r["category"]]["total"] += r["amount"]
        by[r["category"]]["count"] += 1
    items = sorted(({"category": c, **v} for c, v in by.items()), key=lambda x: -x["total"])
    return {"month": month, "total": sum(r["amount"] for r in rows), "categories": items}


def compare_months(month_a: str, month_b: str) -> dict:
    """a → b 카테고리별 증감. 증가액이 큰 순서. (a=이전 달, b=비교할 달)"""
    a = {c["category"]: c["total"] for c in category_breakdown(month_a)["categories"]}
    b = {c["category"]: c["total"] for c in category_breakdown(month_b)["categories"]}
    diffs = []
    for cat in sorted(set(a) | set(b)):
        before, after = a.get(cat, 0), b.get(cat, 0)
        diffs.append({"category": cat, "before": before, "after": after, "diff": after - before,
                      "change_pct": round((after - before) / before * 100, 1) if before else None})
    diffs.sort(key=lambda d: -d["diff"])
    return {"from": month_a, "to": month_b, "total_before": sum(a.values()),
            "total_after": sum(b.values()), "diffs": diffs}


def list_transactions(month=None, category=None, merchant=None, limit: int = 20) -> dict:
    rows = _filter(load_transactions(), month, category, merchant)
    top = sorted(rows, key=lambda r: -r["amount"])[:limit]
    keep = ("id", "date", "time", "merchant", "amount", "category", "overseas")
    # count = 조건에 맞는 전체 건수, shown = 실제로 보여 준 건수 (처음엔 limit으로 자른 뒤 세서 "10건"이 됐다)
    return {"count": len(rows), "shown": len(top), "transactions": [{k: r[k] for k in keep} for r in top]}


# ---------------------------------------------------------------- 이상 결제·구독

def _ts(r) -> datetime:
    return datetime.fromisoformat(f"{r['date']}T{r['time']}")


def detect_anomalies(month: str) -> dict:
    """중복 결제 / 평소보다 큰 결제 / 해외 결제. 기준은 모두 위의 상수(코드)로 정한다."""
    all_rows = load_transactions()
    rows = _filter(all_rows, month)
    found = []

    by_key = defaultdict(list)
    for r in rows:
        by_key[(r["merchant"], r["amount"])].append(r)
    for (merchant, amount), group in by_key.items():
        group.sort(key=_ts)
        for prev, cur in zip(group, group[1:]):
            gap = (_ts(cur) - _ts(prev)).total_seconds()
            if gap <= DUPLICATE_WINDOW_S:
                found.append({"type": "중복 결제 의심", "merchant": merchant, "amount": amount,
                              "date": cur["date"], "ids": [prev["id"], cur["id"]],
                              "reason": f"같은 가맹점·같은 금액이 {int(gap // 60)}분 간격으로 2번"})

    medians = {}
    for cat in {r["category"] for r in all_rows}:
        amounts = [r["amount"] for r in all_rows if r["category"] == cat]
        medians[cat] = statistics.median(amounts)
    for r in rows:
        med = medians[r["category"]]
        if r["amount"] >= max(OUTLIER_MULTIPLIER * med, OUTLIER_MIN_AMOUNT):
            found.append({"type": "평소보다 큰 결제", "merchant": r["merchant"], "amount": r["amount"],
                          "date": r["date"], "ids": [r["id"]],
                          "reason": f"{r['category']} 결제 중앙값 {round(med):,}원의 {r['amount'] / med:.1f}배"})
        if r["overseas"]:
            found.append({"type": "해외 결제", "merchant": r["merchant"], "amount": r["amount"],
                          "date": r["date"], "ids": [r["id"]], "reason": "해외 가맹점 결제"})
    # 같은 결제가 여러 기준에 걸리면(예: AMAZON — 큰 결제 + 해외 결제) 한 항목으로 묶는다.
    # 처음엔 기준마다 따로 냈더니 '이상 결제 4건'이 되어, 모델이 맞게 쓴 "3건"이 근거 없는 숫자로 반려됐다.
    merged: dict[str, dict] = {}
    for a in found:
        key = a["ids"][-1]   # '문제가 된 그 결제'(중복이면 두 번째 결제) 기준 — 중복이면서 고액인 결제도 한 항목
        if key in merged:
            merged[key]["type"] += " + " + a["type"]
            merged[key]["reason"] += " / " + a["reason"]
        else:
            merged[key] = dict(a)
    items = sorted(merged.values(), key=lambda a: a["date"])
    return {"month": month, "count": len(items), "anomalies": items}


def find_subscriptions() -> dict:
    """정기 결제 찾기: 2개월 이상, 매달 정확히 1번, 결제일 차이 3일 이내, 금액 차이 1.5배 이내인 가맹점.
    (금액 조건이 없을 때는 우연히 매달 비슷한 날 한 번씩 간 약국이 구독으로 잡혔다)
    카테고리 이름이 아니라 '반복 패턴'으로 찾는다 — 규칙에 없는 새 구독도 잡기 위해."""
    rows = load_transactions()
    all_months = sorted({r["month"] for r in rows})
    latest = all_months[-1]
    by_merchant = defaultdict(list)
    for r in rows:
        by_merchant[r["merchant"]].append(r)
    subs = []
    for merchant, rs in by_merchant.items():
        per_month = defaultdict(list)
        for r in rs:
            per_month[r["month"]].append(r)
        if len(per_month) < 2 or any(len(v) != 1 for v in per_month.values()):
            continue
        days = [int(v[0]["date"][8:]) for v in per_month.values()]
        # 결제일 차이는 '달력을 한 바퀴 도는' 거리로 잰다 — 30일과 1일은 29일이 아니라 2일 차이
        if max(min(abs(a - b), 31 - abs(a - b)) for a in days for b in days) > 3:
            continue
        amounts = [v[0]["amount"] for v in per_month.values()]
        if max(amounts) / min(amounts) > SUBSCRIPTION_MAX_RATIO:   # 금액이 들쭉날쭉하면 정기 결제가 아니다
            continue
        history = [{"month": m, "amount": per_month[m][0]["amount"]} for m in sorted(per_month)]
        sub = {"merchant": merchant, "category": rs[0]["category"],
               "day": int(per_month[max(per_month)][0]["date"][8:]),   # 가장 최근 달의 결제일
               "amount": history[-1]["amount"], "months": [h["month"] for h in history],
               "active": latest in per_month}
        if history[-1]["amount"] != history[-2]["amount"]:
            sub["price_change"] = {"from": history[-2]["amount"], "to": history[-1]["amount"],
                                   "month": history[-1]["month"]}
        if history[0]["month"] != all_months[0]:
            sub["started"] = history[0]["month"]
        subs.append(sub)
    subs.sort(key=lambda s: -s["amount"])
    active = [s for s in subs if s["active"]]
    return {"latest_month": latest, "count": len(active),
            "monthly_total": sum(s["amount"] for s in active), "subscriptions": subs}


# ---------------------------------------------------------------- 예산

def load_budget() -> dict[str, int]:
    base = {k: v for k, v in _read_json(DATA_DIR / "budget.json", {}).items() if not k.startswith("_")}
    return {**base, **_read_json(RUNTIME_DIR / "budget.json", {})}


def budget_status(month: str) -> dict:
    spent = {c["category"]: c["total"] for c in category_breakdown(month)["categories"]}
    budget = load_budget()
    items = []
    for cat, limit in budget.items():
        used = spent.get(cat, 0)
        items.append({"category": cat, "budget": limit, "spent": used, "remaining": limit - used,
                      "used_pct": round(used / limit * 100, 1) if limit else None, "over": used > limit})
    items.sort(key=lambda x: -(x["used_pct"] or 0))
    return {"month": month, "over_count": sum(i["over"] for i in items),
            "over": [i for i in items if i["over"]], "items": items}


def set_budget(category: str, amount: int) -> dict:
    """예산 변경 — 되돌리기 쉬운 값이지만 '저장되는 조치'라 에이전트는 사람 승인 뒤에만 부른다."""
    if category not in CATEGORIES:
        raise ValueError(f"알 수 없는 카테고리: {category}")
    if amount <= 0:
        raise ValueError("예산은 0보다 커야 합니다")
    before = load_budget().get(category)
    saved = _read_json(RUNTIME_DIR / "budget.json", {})
    saved[category] = int(amount)
    _write_json(RUNTIME_DIR / "budget.json", saved)
    return {"category": category, "before": before, "after": int(amount)}


# ---------------------------------------------------------------- 미분류 가맹점

def list_uncategorized(month: str | None = None) -> dict:
    rows = _filter(load_transactions(), month)
    merchants = sorted({r["merchant"] for r in rows if r["category"] == UNCATEGORIZED})
    return {"month": month or "전체", "merchants": merchants}


def set_merchant_category(merchant: str, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"알 수 없는 카테고리: {category}")
    saved = load_overrides()
    saved[merchant] = category
    _write_json(RUNTIME_DIR / "category_overrides.json", saved)
    return {"merchant": merchant, "category": category}
