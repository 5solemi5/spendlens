"""답변 근거 검사 — 답변에 나온 금액·비율·건수가 Tool 결과에 실제로 있는가.

과제1의 grounding을 가계부에 맞게 바꿨다. 가계부에서 가장 위험한 실수는 '그럴듯한 틀린 금액'이다.
모델이 두 카테고리를 직접 더하거나, 반올림을 틀리거나, 다른 달 금액을 섞으면 여기서 걸린다.

허용 규칙:
  - 금액: 사실에 있는 금액과 정확히 같아야 한다. 줄여 쓴 표현만 그 표현의 정밀도만큼 허용한다.
          "33만 원" → ±10,000원, "33.4만 원" → ±1,000원, "약 333,000원" → ±1%.
          (처음엔 모두 ±1%로 했더니 333,700원을 "약 33만 원"이라고 쓴 정상 답이 걸렸다)
  - 비율(%): 사실의 비율과 0.1 이내.
  - 건수(번·건·회·개): 사실에 있는 정수.
날짜("14일", "9/14")와 달("9월")은 검사하지 않는다.
"""
import re

WON = re.compile(r"(?P<approx>약|대략|거의)?\s*(?:(?P<man>\d+(?:\.\d+)?)\s*만\s*(?P<rest>\d{1,3}(?:,\d{3})*|\d+)?|"
                 r"(?P<full>\d{1,3}(?:,\d{3})+|\d+))\s*원(?P<suffix>\s*(?:정도|쯤|가량))?")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
COUNT = re.compile(r"(\d+)\s*(?:번|건|회|개)(?![월일])")
NUM = re.compile(r"\d+(?:\.\d+)?")


def parse_won(m: re.Match) -> tuple[int, float]:
    """매치 → (금액, 허용 오차). 정확한 금액이면 오차 0."""
    approx = bool(m.group("approx") or m.group("suffix"))
    if m.group("man") is not None:
        man = m.group("man")
        value = int(round(float(man) * 10_000 + int((m.group("rest") or "0").replace(",", ""))))
        if m.group("rest") is not None:              # "33만 3,700원" → 정확한 금액
            return value, value * 0.01 if approx else 0
        decimals = len(man.split(".")[1]) if "." in man else 0
        return value, 10_000 / 10 ** decimals      # "33만" ±10,000 / "33.4만" ±1,000
    value = int(m.group("full").replace(",", ""))
    return value, value * 0.01 if approx else 0


def fact_numbers(facts_text: str) -> tuple[set[int], set[float]]:
    """사실 텍스트의 모든 숫자 → (정수 집합, 실수 집합)."""
    ints, floats = set(), set()
    for raw in re.findall(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?", facts_text):
        v = float(raw.replace(",", ""))
        floats.add(v)
        if v.is_integer():
            ints.add(int(v))
    return ints, floats


def check_amounts(draft: str, facts_text: str) -> list[str]:
    ints, floats = fact_numbers(facts_text)
    bad = []
    for m in WON.finditer(draft):
        value, tolerance = parse_won(m)
        if value in ints:
            continue
        if tolerance and any(abs(value - f) <= tolerance for f in ints if f >= 1000):
            continue
        bad.append(m.group(0).strip())
    for m in PERCENT.finditer(draft):
        if not any(abs(float(m.group(1)) - f) <= 0.1 for f in floats):
            bad.append(m.group(0))
    for m in COUNT.finditer(draft):
        if int(m.group(1)) > 1 and int(m.group(1)) not in ints:   # "1번", "1개"는 너무 흔해서 검사하지 않음
            bad.append(m.group(0))
    return list(dict.fromkeys(bad))


def check_grounding(draft: str, facts_text: str) -> list[str]:
    """문제 목록(빈 목록 = 통과)."""
    issues = []
    bad = check_amounts(draft, facts_text)
    if bad:
        issues.append(f"수집된 사실에 없는 숫자가 있습니다({', '.join(bad)}). 금액·비율·건수는 수집된 값을 "
                      f"그대로 인용하고, 직접 더하거나 계산하지 마세요.")
    return issues
