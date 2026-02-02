from __future__ import annotations

import shutil

from teleclaude import context_selector, paths
from teleclaude.paths import REPO_ROOT


def test_get_context_e2e(monkeypatch, tmp_path) -> None:
    global_snippets = tmp_path / "global" / "docs"
    shutil.copytree(REPO_ROOT / "docs" / "global", global_snippets)
    monkeypatch.setattr(paths, "GLOBAL_SNIPPETS_DIR", global_snippets)
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets)

    output = context_selector.build_context_output(
        snippet_ids=["software-development/policy/commits"],
        areas=["policy"],
        project_root=REPO_ROOT,
    )

    assert "# PHASE 2: Selected snippet content" in output
    assert "software-development/policy/commits" in output
