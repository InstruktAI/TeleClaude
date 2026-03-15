"""Characterization tests for teleclaude.project_setup.hooks."""

from __future__ import annotations

from pathlib import Path

import yaml

import teleclaude.project_setup.hooks as hooks


def test_install_precommit_hook_updates_framework_config_and_entrypoint_guard(tmp_path: Path) -> None:
    config_path = tmp_path / ".pre-commit-config.yaml"
    config_path.write_text(yaml.safe_dump({"repos": []}, sort_keys=False), encoding="utf-8")
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_text(
        (
            "#!/bin/sh\n"
            "INSTALL_PYTHON=/tmp/python\n"
            "\n"
            'if [ -x "$INSTALL_PYTHON" ]; then\n'
            '  exec "$INSTALL_PYTHON" -mpre_commit "$@"\n'
            "fi\n"
        ),
        encoding="utf-8",
    )

    hooks.install_precommit_hook(tmp_path)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    local_repo = next(repo for repo in config["repos"] if repo["repo"] == "local")
    assert local_repo["hooks"][0]["id"] == "teleclaude-docs-check"
    assert hooks.STASH_PREVENTION_MARKER in hook_file.read_text(encoding="utf-8")


def test_add_raw_git_hook_is_idempotent_and_makes_file_executable(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    hooks._add_raw_git_hook(hooks_dir)
    hooks._add_raw_git_hook(hooks_dir)

    hook_file = hooks_dir / "pre-commit"
    content = hook_file.read_text(encoding="utf-8")
    assert content.count(hooks.STASH_PREVENTION_MARKER) == 1
    assert content.count(hooks.DOCS_CHECK_MARKER) == 1
    assert hook_file.stat().st_mode & 0o111


def test_ensure_precommit_entrypoint_guard_replaces_old_overlap_guard(tmp_path: Path) -> None:
    hook_file = tmp_path / "pre-commit"
    hook_file.write_text(
        (
            "#!/bin/sh\n"
            f"# {hooks._OLD_OVERLAP_MARKER}\n"
            "echo old guard\n"
            "\n"
            'if [ -x "$INSTALL_PYTHON" ]; then\n'
            "  exit 0\n"
            "fi\n"
        ),
        encoding="utf-8",
    )

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert hooks._OLD_OVERLAP_MARKER not in content
    assert hooks.STASH_PREVENTION_MARKER in content
    assert "echo old guard" not in content
