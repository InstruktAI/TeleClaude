#!/usr/bin/env sh
set -eu

. .venv/bin/activate

# Force tests to use sandboxed config and env files
export TELECLAUDE_CONFIG_PATH="${TELECLAUDE_CONFIG_PATH:-tests/integration/config.yml}"
export TELECLAUDE_ENV_PATH="${TELECLAUDE_ENV_PATH:-tests/integration/.env}"

# Run unit and integration suites separately with strict per-test timeouts
pytest tests/unit -n auto --timeout=5 -q
pytest tests/integration -n auto --timeout=15 -q
