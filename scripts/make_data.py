"""가상 카드 내역 생성기 — data/transactions.csv를 만든다.

실제 카드 내역은 개인정보라 저장소에 올릴 수 없다. 그래서 '그럴듯한' 3개월치(2026-07~09)
내역을 고정 시드로 만든다. 같은 시드면 항상 같은 파일이 나오므로 정답(expected)도 고정된다.

일부러 심어 둔 것 (에이전트가 찾아내야 하는 것):
  - 중복 결제   : 9/14 배달의민족 27,500원이 2분 간격으로 두 번
  - 이상 고액   : 9/22 무신사 389,000원 (평소 쇼핑 결제는 2~6만 원대)
  - 해외 결제   : 9/27 AMAZON.COM 152,300원 (overseas=Y)
  - 구독료 인상 : NETFLIX 7·8월 13,500원 → 9월 17,000원
  - 새 구독     : 밀리의서재 8월부터 9,900원
  - 규칙에 없는 가맹점: 하이디라오·블루보틀·다이소·쏘카·클라이밍파크 → LLM이 분류해야 함

사용법: python scripts/make_data.py   (data/transactions.csv 덮어씀)
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "transactions.csv"
SEED = 1020

# (가맹점, 최소, 최대, 한 달 평균 횟수) — 금액은 100원 단위로 반올림
DAILY = {
    "식비": [("김밥천국", 5000, 9000, 4), ("배달의민족", 15000, 35000, 5), ("맘스터치", 7000, 12000, 3),
             ("한솥도시락", 5000, 8000, 3), ("버거킹", 8000, 13000, 2), ("하이디라오 강남점", 45000, 70000, 1)],
    "카페": [("스타벅스", 4500, 7000, 6), ("메가커피", 1500, 4000, 6), ("투썸플레이스", 5000, 8000, 2),
             ("블루보틀 성수", 6000, 9000, 1)],
    "장보기": [("이마트", 30000, 90000, 2), ("GS25", 2000, 9000, 6), ("CU", 2000, 9000, 4)],
    "교통": [("카카오T 택시", 8000, 25000, 3), ("티머니 지하철", 1450, 1450, 20), ("쏘카", 20000, 45000, 1)],
    "쇼핑": [("쿠팡", 12000, 45000, 2), ("올리브영", 15000, 40000, 1), ("무신사", 30000, 60000, 1),
             ("다이소 신촌점", 3000, 12000, 1)],
    "문화": [("CGV", 14000, 28000, 1), ("교보문고", 12000, 30000, 1), ("클라이밍파크 신림", 22000, 22000, 2)],
    "의료": [("온누리약국", 3000, 15000, 1)],
}

# (가맹점, 결제일, 월별 금액 {월: 금액}) — 매달 같은 날 나가는 정기 결제
RECURRING = [
    ("쿠팡와우 멤버십", 1, {7: 7890, 8: 7890, 9: 7890}),
    ("NETFLIX", 5, {7: 13500, 8: 13500, 9: 17000}),          # 9월 가격 인상
    ("YOUTUBE PREMIUM", 12, {7: 14900, 8: 14900, 9: 14900}),
    ("밀리의서재", 15, {8: 9900, 9: 9900}),                    # 8월부터 새로 시작
    ("SPOTIFY", 20, {7: 11990, 8: 11990, 9: 11990}),
    ("SKT 통신요금", 25, {7: 55000, 8: 55000, 9: 55000}),
]

# 9월 지출을 늘려 예산 초과·전월 대비 증가를 만들기 위한 배율
MONTH_SCALE = {7: 1.0, 8: 0.9, 9: 1.2}


def rand_time(rng: random.Random) -> str:
    return f"{rng.randint(8, 23):02d}:{rng.randint(0, 59):02d}"


def build_rows() -> list[dict]:
    rng = random.Random(SEED)
    rows = []
    for month in (7, 8, 9):
        days = (date(2026, month + 1, 1) - timedelta(days=1)).day
        for category, merchants in DAILY.items():
            for merchant, lo, hi, per_month in merchants:
                count = max(0, round(per_month * MONTH_SCALE[month] + rng.uniform(-0.6, 0.6)))
                for _ in range(count):
                    amount = round(rng.randint(lo, hi), -2) if lo != hi else lo
                    rows.append({"date": date(2026, month, rng.randint(1, days)).isoformat(),
                                 "time": rand_time(rng), "merchant": merchant, "amount": amount,
                                 "card": rng.choice(["신한카드", "현대카드"]), "overseas": "N"})
        for merchant, day, by_month in RECURRING:
            if month in by_month:
                rows.append({"date": date(2026, month, day).isoformat(), "time": "09:00",
                             "merchant": merchant, "amount": by_month[month],
                             "card": "현대카드", "overseas": "N"})
    # 일부러 심는 이상 거래
    rows += [
        {"date": "2026-09-14", "time": "19:31", "merchant": "배달의민족", "amount": 27500, "card": "신한카드", "overseas": "N"},
        {"date": "2026-09-14", "time": "19:33", "merchant": "배달의민족", "amount": 27500, "card": "신한카드", "overseas": "N"},
        {"date": "2026-09-22", "time": "22:47", "merchant": "무신사", "amount": 389000, "card": "현대카드", "overseas": "N"},
        {"date": "2026-09-27", "time": "03:12", "merchant": "AMAZON.COM", "amount": 152300, "card": "현대카드", "overseas": "Y"},
    ]
    rows.sort(key=lambda r: (r["date"], r["time"], r["merchant"]))
    for i, r in enumerate(rows, 1):
        r["id"] = f"T{i:04d}"
    return rows


def main():
    rows = build_rows()
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "date", "time", "merchant", "amount", "card", "overseas"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows → {OUT}")


if __name__ == "__main__":
    main()
