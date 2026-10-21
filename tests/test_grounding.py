"""금액 근거 검사 — 사실에 없는 금액·비율·건수를 잡고, 정상적인 줄임 표현은 통과시키는가."""
import pytest

from agent.grounding import check_amounts

FACTS = ("- 2026-09 식비 지출: 합계 333,700원, 22건, 평균 15,168원\n"
         "- 2026-09 예산 초과: 쇼핑 748,200원 / 예산 150,000원 (498.8%, 598,200원 초과)")


@pytest.mark.parametrize("draft", ["9월 식비는 333,700원(22건)입니다.", "약 33만 원 썼어요", "33.4만 원", "33만 3,700원",
                                   "약 334,000원", "예산의 498.8%", "1번 확인하세요", "9월 14일에"])
def test_grounded(draft):
    assert check_amounts(draft, FACTS) == []


@pytest.mark.parametrize("draft, bad", [("식비와 쇼핑을 합치면 1,081,900원", "1,081,900원"), ("35만 원", "35만 원"),
                                        ("약 340,000원", "약 340,000원"), ("500%", "500%"), ("23건", "23건")])
def test_ungrounded(draft, bad):
    assert check_amounts(draft, FACTS) == [bad]


def test_review_fixes():
    # 날짜 속 숫자(2026, 09)는 사실 수치가 아니다
    assert check_amounts("9건 있어요", "- 2026-09 식비 지출: 합계 333,700원, 22건") == ["9건"]
    # 반올림이 맞으면 통과, 틀린 반올림은 반려
    facts = "- 합계 333,700원"
    assert check_amounts("약 330,000원", facts) == [] and check_amounts("33만 원", facts) == []
    assert check_amounts("34만 원", facts) == ["34만 원"]
