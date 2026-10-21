#!/usr/bin/env bash
# 채팅 화면 실행 (백엔드를 먼저 띄울 것). FRONT_PORT(기본 8700), BACKEND_PORT(기본 8200)
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_venv
export FRONT_PORT="${FRONT_PORT:-8700}" BACKEND_PORT="${BACKEND_PORT:-8200}"
require_free_port "$FRONT_PORT" FRONT_PORT
curl -s "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null || { echo "❌ 백엔드(${BACKEND_PORT})가 꺼져 있습니다. 먼저: bash sh/run_agent.sh"; exit 1; }
echo "🖥  http://localhost:${FRONT_PORT} 접속 (백엔드 ${BACKEND_PORT})"
cd "$ROOT" && exec "$PY" web_demo_server.py
