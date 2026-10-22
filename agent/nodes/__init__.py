"""그래프 노드 모듈 — 역할별로 나눴다(과제1 개선 8과 같은 구조).

    state.py      : 그래프 상태(AgentState)와 공통 도우미
    routing.py    : route(가계부/잡담/범위 밖) · chat_answer · refuse
    planning.py   : plan(기간·의도 → 조회 계획) · no_data · clarify
    research.py   : categorize(미분류 가맹점 LLM 분류) · research(MCP Tool 호출, Lock으로 차례로 처리)
    advising.py   : advise(절약 가이드 RAG)
    writing.py    : write(답변 작성) · validate(금액 근거 검사) · finalize
    budget.py     : propose_change(예산 변경 제안) · approval(사람 승인 후 set_budget 실행)
"""
