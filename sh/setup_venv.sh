#!/usr/bin/env bash
# .venv 만들기 + 패키지 설치 (최초 1회)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python3 -m pip install -q --upgrade pip
.venv/bin/python3 -m pip install -q -r requirements.txt -r requirements-dev.txt
echo "✅ 준비 완료: .venv/bin/python3 -m pytest -q 로 테스트해 보세요"
