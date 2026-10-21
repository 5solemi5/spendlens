"""pytest 공통 설정 — 프로젝트 루트를 import 경로에 넣고, 실행 중 바뀌는 파일(data/runtime)을
테스트마다 임시 폴더로 돌린다. 테스트가 실제 예산·분류 저장 파일을 건드리지 않게."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ.setdefault("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    from agent import ledger
    monkeypatch.setattr(ledger, "RUNTIME_DIR", tmp_path / "runtime")
    return tmp_path / "runtime"
