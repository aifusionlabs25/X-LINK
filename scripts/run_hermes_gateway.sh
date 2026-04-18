#!/usr/bin/env bash
set -euo pipefail

source ~/.local/bin/env >/dev/null 2>&1 || true
exec hermes gateway
