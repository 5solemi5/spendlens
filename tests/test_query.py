"""질문 해석 — 기간·카테고리·가맹점·의도를 코드로 정확히 뽑는가."""
import pytest

from agent import ledger
from agent.query import is_spending_question, month_shift, parse_amount, parse_months, parse_query

MERCHANTS = sorted({r["merchant"] for r in ledger.load_transactions()})


def q(text):
    return parse_query(text, MERCHANTS)


@pytest.mark.parametrize("text, months", [
    ("9월 식비", ["2026-09"]),
    ("8월보다 9월에 늘어난 것", ["2026-08", "2026-09"]),   # 회귀: 처음엔 9월이 사라졌다
    ("2026년 9월 쇼핑", ["2026-09"]),                     # 연도+월을 두 번 세지 않음
    ("지난달보다 이번 달", ["2026-08", "2026-09"]),
    ("요즘 지출", []),
])
def test_parse_months(text, months):
    assert parse_months(text) == months


def test_month_shift_wraps_year():
    assert month_shift("2026-01", -1) == "2025-12" and month_shift("2026-12", 1) == "2027-01"


@pytest.mark.parametrize("text, amount", [("50만원으로", 500000), ("45만 원", 450000), ("450,000원", 450000),
                                          ("12.5만원", 125000), ("예산 바꿔줘", None)])
def test_parse_amount(text, amount):
    assert parse_amount(text) == amount


def test_compare_with_single_month_uses_previous_month():
    assert q("9월이 전달보다 늘었어?")["months"] == ["2026-08", "2026-09"]


def test_budget_change_intent_is_exclusive():
    p = q("식비 예산 50만원으로 바꿔줘")
    assert p["intents"] == ["budget_change"] and p["budget_change"] == {"category": "식비", "amount": 500000}


def test_subscription_question_is_not_category_total():
    p = q("내 구독 서비스 정리해 줘")
    assert "subscription" in p["intents"] and p["category"] is None


def test_merchant_and_all_period():
    p = q("스타벅스에 3달 동안 얼마 썼어?")
    assert p["merchant"] == "스타벅스" and p["all_period"] and "total" in p["intents"]
    assert q("하이디라오에서 얼마 썼지")["merchant"] == "하이디라오"   # 가맹점 이름의 첫 단어로도 찾음


def test_out_of_scope_and_chat():
    assert q("비트코인 사도 될까?")["out_of_scope"]
    assert not is_spending_question(q("안녕, 너는 누구야?"))
    assert is_spending_question(q("9월 카페 몇 번 갔어?"))


def test_review_fixes():
    from agent.query import find_category
    assert find_category("스마트폰 요금 얼마야") == "통신"          # '스마트폰'의 '마트'를 장보기로 읽지 않음
    assert find_category("책임감 있게 쓰자") is None and find_category("책 값") == "문화"
    assert parse_months("9월 카드 내역 전달해줘") == ["2026-09"]      # 동사 '전달하다'는 지난달이 아님
    assert parse_amount("3만 5천원") == 35000 and parse_amount("5천원") == 5000
    assert q("7월 8월 9월 비교해줘")["months"] == ["2026-07", "2026-09"]
    assert q("9월이 지난달보다 늘었어?")["months"] == ["2026-08", "2026-09"]


def test_compare_single_month_branch():
    # 달이 하나만 나오는 비교 → 직전 달과 비교 (리뷰: 기존 테스트는 '전달'을 두 번째 달로 읽어 이 분기를 안 탔다)
    assert q("9월에 많이 늘었어?")["months"] == ["2026-08", "2026-09"]
