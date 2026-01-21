from __future__ import annotations

import shutil
from pathlib import Path

from teleclaude import context_selector, paths
from teleclaude.paths import REPO_ROOT


def test_get_context_e2e(monkeypatch, tmp_path) -> None:
    global_snippets = tmp_path / "global-snippets"
    shutil.copytree(REPO_ROOT / "docs" / "global-snippets", global_snippets)
    monkeypatch.setattr(paths, "GLOBAL_SNIPPETS_DIR", global_snippets)
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets)

    monkeypatch.setattr(
        context_selector,
        "_select_ids",
        lambda _corpus, _metadata: ["software-development/standards/commits"],
    )

    output = context_selector.build_context_output(
        corpus="commit standards commitizen atomic commits",
        areas=["policy", "standard"],
        project_root=REPO_ROOT,
        session_id=None,
    )

    assert "NEW_SNIPPETS:" in output
    assert "(none)" not in output
    assert "software-development/standards/commits" in output
