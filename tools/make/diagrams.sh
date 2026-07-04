#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "Generating architecture diagrams..."
mkdir -p docs/diagrams
uv run python scripts/diagrams/extract_state_machines.py
uv run python scripts/diagrams/extract_events.py
uv run python scripts/diagrams/extract_data_model.py
uv run python scripts/diagrams/extract_modules.py
uv run python scripts/diagrams/extract_commands.py
uv run python scripts/diagrams/extract_runtime_matrix.py
echo "✓ Architecture diagrams generated in docs/diagrams/"
