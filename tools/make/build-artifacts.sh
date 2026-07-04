#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

uv run -m teleclaude.codegen.pydantic_to_typescript
uv run -m teleclaude.cli.telec sync
