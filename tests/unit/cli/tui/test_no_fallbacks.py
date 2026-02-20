"""Guardrail: ban the word 'fallback' from TUI code.

Silent substitution logic (the noun 'fallback') masks contract violations.
The verb phrase 'fall back' (two words) is acceptable English.
"""

from __future__ import annotations

import re
from pathlib import Path

_TUI_ROOT = Path(__file__).resolve().parents[4] / "teleclaude" / "cli" / "tui"
_PATTERN = re.compile(r"\bfallback\b", re.IGNORECASE)
# This test file itself is exempt
_SELF = Path(__file__).resolve()


def test_no_fallback_in_tui_code() -> None:
    """Scan all .py files under teleclaude/cli/tui/ for the word 'fallback'.

    Fails with a clear message per violation.
    """
    violations: list[str] = []
    for py_file in sorted(_TUI_ROOT.rglob("*.py")):
        if py_file == _SELF:
            continue
        for line_no, line in enumerate(py_file.read_text().splitlines(), start=1):
            if _PATTERN.search(line):
                rel = py_file.relative_to(_TUI_ROOT.parents[2])
                violations.append(f"{rel}:{line_no}")

    if violations:
        detail = "\n  ".join(violations)
        raise AssertionError(
            f"'fallback' detected — potential design-by-contract violation. "
            f"If this masks a missing contract, fix the contract. "
            f"If the comment is accurate, reword to describe actual behavior. "
            f"Never bypass this test without fixing the underlying pattern.\n  {detail}"
        )
