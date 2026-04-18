#!/usr/bin/env bash
set -euo pipefail

mkdir -p ~/.hermes/logs
source ~/.local/bin/env >/dev/null 2>&1 || true

if pgrep -af "hermes gateway" >/dev/null 2>&1; then
  echo already-running
  exit 0
fi

nohup hermes gateway > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &
echo started
