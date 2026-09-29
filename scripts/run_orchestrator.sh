#!/usr/bin/env bash
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && source .env; set +a
exec .venv/bin/uvicorn orchestrator.app.main:app \
  --host "${ORCH_HOST:-127.0.0.1}" --port "${ORCH_PORT:-8800}" "$@"
