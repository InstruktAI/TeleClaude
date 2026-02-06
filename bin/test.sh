#!/usr/bin/env sh
set -eu

. .venv/bin/activate

# Force tests to use sandboxed config and env files
export TELECLAUDE_CONFIG_PATH="${TELECLAUDE_CONFIG_PATH:-tests/integration/config.yml}"
export TELECLAUDE_ENV_PATH="${TELECLAUDE_ENV_PATH:-tests/integration/.env}"

# Run unit and integration suites separately with strict per-test timeouts
if [ "${1:-}" = "--cov" ]; then
    echo "Running tests with coverage..."
    pytest tests/unit tests/integration -n auto --timeout=15 --cov=teleclaude --cov-report=html --cov-report=term-missing
    
    # Generate absolute path for clickable link
    REPORT_PATH="$(pwd)/coverage/html/index.html"
    echo ""
    echo "✓ Coverage report generated: file://$REPORT_PATH"
else
    pytest tests/unit -n auto --timeout=5 -q
    pytest tests/integration -n auto --timeout=15 -q
fi
