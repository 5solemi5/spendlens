"""SpendLens MCP 서버 — 가계부 계산 엔진(agent/ledger.py)을 MCP Tool로, 절약 가이드를 Resource로 내보낸다.

FastAPI 백엔드(server.py)가 lifespan에서 이 파일을 subprocess(stdio)로 1회 띄워 재사용한다.
에이전트는 숫자를 직접 계산하지 않고 반드시 이 Tool들을 거친다 → 같은 질문이면 항상 같은 숫자.

- Tool     : 조회(data_catalog, spending_summary, category_breakdown, compare_months, list_transactions,
             detect_anomalies, find_subscriptions, budget_status, list_uncategorized)
             쓰기(set_merchant_category — 분류 저장, set_budget — 예산 변경: 에이전트는 사람 승인 후에만 호출)
- Resource : guide://saving/{topic}  절약·대응 가이드 문서
- Prompt   : spending_analysis_prompt  분석 절차
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP   # noqa: E402

from agent import ledger   # noqa: E402

mcp = FastMCP(name="spendlens-ledger")
GUIDE_DIR = ledger.DATA_DIR / "guides"


@mcp.tool()
def data_catalog() -> dict:
    """데이터가 있는 달, 가맹점 이름, 카테고리 목록 — 에이전트가 시작할 때 1번 읽는다."""
    return ledger.data_catalog()


@mcp.tool()
def spending_summary(month: str | None = None, category: str | None = None,
                     merchant: str | None = None) -> dict:
    """조건(월 'YYYY-MM', 카테고리, 가맹점 이름 일부)에 맞는 결제의 합계·건수·평균. 조건이 없으면 전체 기간."""
    return ledger.spending_summary(month, category, merchant)


@mcp.tool()
def category_breakdown(month: str) -> dict:
    """그 달의 카테고리별 지출 합계(큰 순서)."""
    return ledger.category_breakdown(month)


@mcp.tool()
def compare_months(month_a: str, month_b: str) -> dict:
    """두 달의 카테고리별 지출 증감(a=이전 달, b=비교할 달). 증가액이 큰 순서."""
    return ledger.compare_months(month_a, month_b)


@mcp.tool()
def list_transactions(month: str | None = None, category: str | None = None,
                      merchant: str | None = None, limit: int = 20) -> dict:
    """조건에 맞는 결제 목록(금액이 큰 순서, 최대 limit건)."""
    return ledger.list_transactions(month, category, merchant, limit)


@mcp.tool()
def detect_anomalies(month: str) -> dict:
    """그 달의 이상 결제: 중복 결제 의심, 평소보다 큰 결제, 해외 결제."""
    return ledger.detect_anomalies(month)


@mcp.tool()
def find_subscriptions() -> dict:
    """반복 패턴으로 찾은 정기 결제(구독)와 월 합계, 가격 변동."""
    return ledger.find_subscriptions()


@mcp.tool()
def budget_status(month: str) -> dict:
    """그 달의 카테고리별 예산 대비 지출과 초과 항목."""
    return ledger.budget_status(month)


@mcp.tool()
def list_uncategorized(month: str | None = None) -> dict:
    """규칙으로 분류되지 않은 가맹점 목록."""
    return ledger.list_uncategorized(month)


@mcp.tool()
def set_merchant_category(merchant: str, category: str) -> dict:
    """가맹점의 카테고리를 저장한다(규칙이 있는 가맹점은 규칙이 우선)."""
    return ledger.set_merchant_category(merchant, category)


@mcp.tool()
def set_budget(category: str, amount: int) -> dict:
    """카테고리 월 예산을 바꾼다. ⚠️ 저장되는 조치 — 에이전트는 사람 승인 후에만 호출한다."""
    return ledger.set_budget(category, amount)


@mcp.resource("guide://saving/{topic}")
def saving_guide(topic: str) -> str:
    """주제(카테고리 또는 '이상결제')별 절약·대응 가이드."""
    path = GUIDE_DIR / f"{topic}.md"
    if not path.exists():
        return f"# Guide Not Found\n\n{topic}에 대한 가이드가 없습니다."
    return path.read_text(encoding="utf-8")


@mcp.prompt()
def spending_analysis_prompt(question: str, month: str) -> str:
    """지출 분석 표준 절차 — planning 노드가 이 절차를 따른다."""
    return f"""다음 지출 질문을 표준 절차로 분석하세요.

## 질문
{question}

## 기준 월
{month}

## 절차 (순서대로)
1. 규칙으로 분류되지 않은 가맹점이 있으면 먼저 분류한다(list_uncategorized → set_merchant_category).
2. 질문에 필요한 숫자는 Tool로만 구한다(spending_summary, category_breakdown, compare_months, …). 직접 계산하지 않는다.
3. 절약 방법을 답할 때는 guide://saving/{{topic}} 가이드를 근거로 쓴다.
4. 예산 변경처럼 저장되는 조치는 사용자 승인 후에만 set_budget을 호출한다.
"""


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:   # 구버전 fastmcp 호환
        mcp.run()
