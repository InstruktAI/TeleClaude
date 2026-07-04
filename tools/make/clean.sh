#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "Cleaning generated files..."
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
find . -type f -name "*.pyo" -delete
rm -rf .pytest_cache
rm -rf .mypy_cache
rm -rf coverage
rm -f .coverage
rm -rf test_sessions.db
rm -rf ./*.egg-info
echo "✓ Cleaned generated files"
