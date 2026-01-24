from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GLOBAL_SNIPPETS_DIR = (Path("~/.teleclaude") / "docs").expanduser()
CONTEXT_STATE_PATH = REPO_ROOT / "logs" / "context_selector_state.json"
TUI_STATE_PATH = (Path("~/.teleclaude") / "tui_state.json").expanduser()
