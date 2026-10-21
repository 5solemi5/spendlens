#!/usr/bin/env bash
# 공통 함수 — 포트가 이미 쓰이고 있으면 아무것도 끄지 않고 멈춘다(과제1에서 다른 프로그램을 kill하던 문제의 교훈).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python3"

require_venv() {
  if [ ! -x "$PY" ]; then
    echo "❌ .venv가 없습니다. 먼저: bash sh/setup_venv.sh"; exit 1
  fi
}

require_free_port() {   # $1=포트 $2=환경변수 이름
  if lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "❌ ${1}번 포트를 이미 다른 프로그램이 쓰고 있습니다:"
    lsof -nP -iTCP:"$1" -sTCP:LISTEN | tail -n +2
    echo "   다른 포트로 띄우세요. 예: ${2}=$(( $1 + 1 )) bash $0"
    exit 1
  fi
}
