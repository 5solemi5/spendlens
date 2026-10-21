"""절약 가이드 RAG — 질문에 카테고리 이름이 없어도 관련 가이드를 찾는가."""
import pytest

from agent.guide_retriever import GuideRetriever

R = GuideRetriever()


@pytest.mark.parametrize("query, hints, topic", [
    ("커피값 줄이는 법", [], "카페"),
    ("넷플릭스 해지할까", [], "구독"),
    ("배달 너무 많이 시켜", [], "식비"),
    ("모르는 해외 결제가 있어", [], "이상결제"),
    ("9월 지출 줄이는 방법 알려줘", ["쇼핑", "구독"], "쇼핑"),   # 질문엔 카테고리가 없고 분석 결과(hints)가 결정
])
def test_top_topic(query, hints, topic):
    assert R.retrieve(query, hints)[0]["topic"] == topic


def test_lines_are_guide_body_not_metadata():
    top = R.retrieve("구독료가 올랐어", [])[0]
    assert top["topic"] == "구독" and all(len(l) > 15 for l in top["lines"])   # 메타 문구("구독 정리")가 아닌 본문
