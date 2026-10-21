#!/usr/bin/env bash
# 백엔드 실행. LLM_BACKEND=fake(기본)|ollama|openai, BACKEND_PORT(기본 8200), HITL_APPROVAL=1(기본)|0
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_venv
BACKEND_PORT="${BACKEND_PORT:-8200}"; export BACKEND_PORT
export LLM_BACKEND="${LLM_BACKEND:-fake}"
require_free_port "$BACKEND_PORT" BACKEND_PORT
if [ "$LLM_BACKEND" = "ollama" ] && ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  echo "❌ Ollama가 꺼져 있습니다. 다른 터미널에서: ollama serve"; exit 1
fi
if [ "$LLM_BACKEND" = "openai" ]; then
  read -r -p "⚠️ OpenAI API는 과금됩니다. 계속할까요? (y/N) " yn; [ "$yn" = "y" ] || exit 0
fi
echo "🚀 SpendLens 백엔드: http://127.0.0.1:${BACKEND_PORT} (LLM_BACKEND=${LLM_BACKEND})"
echo "   예) curl -s -X POST localhost:${BACKEND_PORT}/chat -H 'Content-Type: application/json' -d '{\"message\":\"9월 식비 얼마 썼어?\",\"thread_id\":\"t1\"}'"
echo "   화면: 다른 터미널에서 BACKEND_PORT=${BACKEND_PORT} bash sh/run_frontend.sh"
cd "$ROOT" && exec "$PY" server.py
