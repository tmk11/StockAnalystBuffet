#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${PORT:=8866}"
: "${HOST:=127.0.0.1}"
if [[ -x .venv/bin/gunicorn ]]; then
  exec .venv/bin/gunicorn -w 2 -b "$HOST:$PORT" app:app
fi
exec gunicorn -w 2 -b "$HOST:$PORT" app:app
