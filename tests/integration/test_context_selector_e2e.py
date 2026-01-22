from __future__ import annotations

import shutil
from pathlib import Path

from teleclaude import context_selector, paths
from teleclaude.paths import REPO_ROOT


def test_get_context_e2e(monkeypatch, tmp_path) -> None:
    global_snippets = tmp_path / "agents" / "docs"
    shutil.copytree(REPO_ROOT / "agents" / "docs", global_snippets)
    monkeypatch.setattr(paths, "GLOBAL_SNIPPETS_DIR", global_snippets)
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets)

    output = context_selector.build_context_output(
        corpus='["software-development/standards/commits"]',
        areas=["policy", "standard"],
        project_root=REPO_ROOT,
        session_id=None,
    )

    assert "NEW_SNIPPETS:" in output
    assert "(none)" not in output
    assert "software-development/standards/commits" in output
