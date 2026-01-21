from __future__ import annotations

from teleclaude import context_selector
from teleclaude.paths import REPO_ROOT


def test_get_context_e2e() -> None:
    output = context_selector.build_context_output(
        corpus="commit standards commitizen atomic commits",
        areas=["policy", "standard"],
        project_root=REPO_ROOT,
        session_id=None,
    )

    assert "NEW_SNIPPETS:" in output
    assert "(none)" not in output
    assert "software-development/standards/commits" in output
