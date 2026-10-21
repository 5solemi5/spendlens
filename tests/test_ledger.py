"""계산 엔진 — 데이터 생성기가 '일부러 심은 것'을 코드가 정확히 찾는지 확인한다."""
import csv

import pytest

from agent import ledger as L
from tests.conftest import ROOT


def test_months_and_grand_total_match_csv():
    with (ROOT / "data" / "transactions.csv").open(encoding="utf-8") as f:
        raw_total = sum(int(r["amount"]) for r in csv.DictReader(f))
    assert L.months() == ["2026-07", "2026-08", "2026-09"]
    assert sum(L.category_breakdown(m)["total"] for m in L.months()) == raw_total


def test_planted_anomalies_found_only_in_september():
    found = {(a["type"], a["merchant"], a["amount"]) for a in L.detect_anomalies("2026-09")["anomalies"]}
    assert found == {("중복 결제 의심", "배달의민족", 27500), ("평소보다 큰 결제", "무신사", 389000),
                     ("평소보다 큰 결제 + 해외 결제", "AMAZON.COM", 152300)}   # 같은 결제는 한 항목
    assert L.detect_anomalies("2026-09")["count"] == 3
    assert L.detect_anomalies("2026-07")["count"] == 0 and L.detect_anomalies("2026-08")["count"] == 0


def test_subscriptions_by_pattern_not_by_name():
    subs = L.find_subscriptions()
    names = {s["merchant"] for s in subs["subscriptions"]}
    assert names == {"SKT 통신요금", "NETFLIX", "YOUTUBE PREMIUM", "SPOTIFY", "밀리의서재", "쿠팡와우 멤버십"}
    assert subs["monthly_total"] == 116680
    netflix = next(s for s in subs["subscriptions"] if s["merchant"] == "NETFLIX")
    assert netflix["price_change"] == {"from": 13500, "to": 17000, "month": "2026-09"}
    assert next(s for s in subs["subscriptions"] if s["merchant"] == "밀리의서재")["started"] == "2026-08"
    assert "온누리약국" not in names   # 매달 한 번 갔지만 금액이 1.75배 차이 → 구독 아님


def test_budget_over_in_september():
    over = {i["category"] for i in L.budget_status("2026-09")["over"]}
    assert over == {"쇼핑", "장보기", "구독"}   # 구독은 넷플릭스 인상 때문에 60,000원을 넘음


def test_compare_months_biggest_increase():
    diffs = L.compare_months("2026-08", "2026-09")["diffs"]
    assert diffs[0]["category"] == "쇼핑" and diffs[0]["diff"] == 650200


def test_set_budget_writes_runtime_only(isolated_runtime):
    out = L.set_budget("식비", 500000)
    assert out == {"category": "식비", "before": 400000, "after": 500000}
    assert L.load_budget()["식비"] == 500000
    assert (isolated_runtime / "budget.json").exists()
    assert '"식비": 400000' in (ROOT / "data" / "budget.json").read_text(encoding="utf-8")   # 원본은 그대로
    with pytest.raises(ValueError):
        L.set_budget("술값", 1000)


def test_merchant_category_override_and_rule_priority():
    assert L.categorize("하이디라오 강남점") == L.UNCATEGORIZED
    L.set_merchant_category("하이디라오 강남점", "식비")
    assert L.categorize("하이디라오 강남점") == "식비"
    L.set_merchant_category("스타벅스", "쇼핑")          # 규칙이 있는 가맹점은 규칙이 이긴다
    assert L.categorize("스타벅스") == "카페"


def test_merchant_filter_is_case_insensitive_substring():
    assert L.spending_summary(merchant="netflix")["count"] == 3
    assert L.spending_summary(merchant="스타벅스") == {"month": "전체", "category": None, "merchant": "스타벅스",
                                                      "total": 108500, "count": 19, "average": 5711}


def test_review_fixes(tmp_path):
    assert L.categorize("CU 신촌점") == "장보기" and L.categorize("CUCKOO MALL") == L.UNCATEGORIZED
    listed = L.list_transactions("2026-09", limit=3)
    assert listed["shown"] == 3 and listed["count"] == L.spending_summary("2026-09")["count"]


def test_guide_resource_rejects_paths_outside_folder():
    import mcp_server
    assert "Not Found" in mcp_server.saving_guide("../../README")
    assert mcp_server.saving_guide("구독").startswith("# 절약 가이드: 구독")
