"""질문 해석 — 기간·카테고리·가맹점·의도를 '코드로' 뽑는다.

과제1에서 배운 원칙(권위 게이트): 틀리면 숫자가 통째로 틀어지는 값(어느 달? 어느 카테고리?)은
정규식·사전으로 결정하고, LLM은 코드가 못 정한 '의도'만 보충한다. 0.6b에게 "9월"을 맡기면
가끔 "2025-09"를 내고, 그러면 합계가 0원이 된다.

기준 날짜: 데이터는 2026-07~09뿐이라 '이번 달'은 데이터의 마지막 달(9월)로 본다.
           SPENDLENS_REF_MONTH 환경변수로 바꿀 수 있다.
"""
import os
import re

REF_MONTH = os.environ.get("SPENDLENS_REF_MONTH", "2026-09")
YEAR = REF_MONTH[:4]

# 카테고리 별칭 — 위에서부터 검사해 처음 맞는 것을 쓴다(구독이 쇼핑의 '쿠팡'보다 먼저: "쿠팡와우 구독")
CATEGORY_ALIASES: list[tuple[str, str]] = [
    (r"구독|넷플릭스|netflix|유튜브 ?프리미엄|스포티파이|멤버십|정기 ?결제", "구독"),
    (r"식비|밥값|식사|외식|배달|점심|저녁|야식|먹는 데", "식비"),
    (r"카페|커피|스타벅스|음료", "카페"),
    (r"통신|휴대폰|핸드폰|스마트폰|폰 ?요금", "통신"),   # 장보기보다 먼저: "스마트폰"의 '마트'
    (r"장보기|마트|편의점|생활비", "장보기"),
    (r"교통|택시|지하철|버스|대중교통|쏘카", "교통"),
    (r"쇼핑|옷|쿠팡|무신사|올리브영|직구", "쇼핑"),
    (r"문화|여가|영화|도서|서점|책(?![임상])|운동|클라이밍", "문화"),   # "책임·책상"은 책이 아니다
    (r"의료|병원|약국", "의료"),
]

INTENT_PATTERNS: dict[str, str] = {
    "count": r"몇 ?번|몇 ?건|몇 ?회|횟수|자주",
    "compare": r"보다|대비|비교|늘었|줄었|증가|감소|변화|차이",
    "anomaly": r"이상한|이상 ?결제|수상|중복|해외 ?결제|모르는 결제|부정|도용|잘못 ?결제",
    "subscription": r"구독|정기 ?결제|매달 나가|자동 ?결제|고정 ?지출",
    "budget": r"예산|한도|초과|넘었|넘은",
    "advice": r"줄이|절약|아끼|방법|어떻게 하면|팁|조언|추천해",
    "transactions": r"내역|목록|리스트|가장 큰|제일 큰|큰 결제|top|TOP",
    "total": r"얼마|합계|총|썼|쓴|지출|금액",
}
BUDGET_CHANGE = re.compile(r"예산[^.?!]{0,20}?(바꿔|변경|올려|내려|설정|수정|으로 해|로 해|로 잡아|조정)")
OUT_OF_SCOPE = re.compile(r"주식|코인|비트코인|이더리움|투자|대출|펀드|ETF|재테크|부동산")
AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*만\s*(?:(\d+)\s*천)?\s*원?|(\d+)\s*천\s*원|(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def month_shift(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:]) + delta
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def parse_months(text: str) -> list[str]:
    """질문에 나온 달을 등장 순서대로. '이번 달'=REF, '지난달/저번 달'=REF-1."""
    found: list[tuple[int, str]] = []
    for m in re.finditer(r"(20\d\d)[-./년 ]\s*(\d{1,2})\s*월?", text):
        found.append((m.start(), f"{m.group(1)}-{int(m.group(2)):02d}"))
    with_year = [p for p, _ in found]   # "2026년 9월"의 '9월'을 아래에서 한 번 더 세지 않기 위한 위치
    for m in re.finditer(r"(?<![\d-])(\d{1,2})\s*월", text):
        # 연도 표기 바로 뒤의 '월'만 건너뛴다. (처음엔 모든 앞선 달과 비교해서 "8월보다 9월"의 9월이 사라졌다)
        if not any(0 < m.start() - p < 8 for p in with_year):
            found.append((m.start(), f"{YEAR}-{int(m.group(1)):02d}"))
    for m in re.finditer(r"이번 ?달|이달", text):
        found.append((m.start(), REF_MONTH))
    for m in re.finditer(r"지난 ?달|저번 ?달|전 ?달(?![하해했되받])", text):   # "전달해줘"(동사)는 제외
        found.append((m.start(), month_shift(REF_MONTH, -1)))
    return list(dict.fromkeys(mo for _, mo in sorted(found)))


def parse_amount(text: str) -> int | None:
    """'50만원' → 500000, '3만 5천원' → 35000, '5천원' → 5000, '450,000원' → 450000. 없으면 None."""
    m = AMOUNT.search(text)
    if not m:
        return None
    if m.group(1):
        return int(round(float(m.group(1)) * 10_000)) + int(m.group(2) or 0) * 1_000
    if m.group(3):
        return int(m.group(3)) * 1_000
    return int(m.group(4).replace(",", ""))


def find_category(text: str) -> str | None:
    lowered = text.lower()
    for pattern, category in CATEGORY_ALIASES:
        if re.search(pattern, lowered):
            return category
    return None


def find_merchant(text: str, merchants: list[str]) -> str | None:
    """데이터에 있는 가맹점 이름(또는 그 첫 단어)이 질문에 그대로 나오면 그 가맹점."""
    lowered = text.lower()
    for name in sorted(merchants, key=len, reverse=True):
        head = name.split()[0].lower()
        if name.lower() in lowered or (len(head) >= 3 and head in lowered):
            return head if head != name.lower() else name
    return None


def parse_query(text: str, merchants: list[str]) -> dict:
    """질문 → {months, category, merchant, intents, budget_change, out_of_scope, all_period}."""
    intents = [name for name, pattern in INTENT_PATTERNS.items() if re.search(pattern, text, re.I)]
    months = parse_months(text)
    all_period = bool(re.search(r"전체|지금까지|\d\s*달 ?동안|석 ?달|세 ?달|3개월|그동안", text))
    budget_change = None
    if BUDGET_CHANGE.search(text):
        budget_change = {"category": find_category(re.sub(r"예산", "", text)), "amount": parse_amount(text)}
        intents = ["budget_change"]
    category = find_category(text)
    if "subscription" in intents and category == "구독":
        category = None   # "구독 정리해줘"는 구독 '카테고리 합계'가 아니라 정기 결제 탐지 질문
    if "compare" in intents and len(months) == 1:
        months = [month_shift(months[0], -1), months[0]]   # "9월 늘었어?" → [8월, 9월]
    elif "compare" in intents and len(months) >= 2:
        months = sorted(months)
        months = [months[0], months[-1]]   # 순서와 상관없이 [가장 이른 달, 가장 늦은 달] ("7월 8월 9월 비교" → 7·9월)
    return {"months": months, "category": category, "merchant": find_merchant(text, merchants),
            "intents": intents, "budget_change": budget_change, "all_period": all_period,
            "out_of_scope": bool(OUT_OF_SCOPE.search(text))}


def is_spending_question(parsed: dict) -> bool:
    """가계부 질문의 신호(의도·기간·카테고리·가맹점)가 하나라도 있으면 True."""
    return bool(parsed["intents"] or parsed["months"] or parsed["category"] or parsed["merchant"])
