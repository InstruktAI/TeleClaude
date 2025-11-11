#!/usr/bin/env sh
. .venv/bin/activate

# Run ALL tests in parallel with isolated databases per test
# Function-scoped fixtures ensure no database conflicts
pytest tests/ -n auto --timeout=5 -q
