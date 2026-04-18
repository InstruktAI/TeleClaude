"""Unit tests for teleclaude.project_setup.hooks — hook content generation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import teleclaude.project_setup.hooks as hooks


def _make_precommit_entrypoint(extra: str = "", install_python: str = "/tmp/python") -> str:
    """Build a minimal pre-commit generated hook wrapper for testing."""
    return (
        "#!/usr/bin/env bash\n"
        f"INSTALL_PYTHON={install_python}\n"
        "ARGS=()\n"
        f"{extra}\n"
        'if [ -x "$INSTALL_PYTHON" ]; then\n'
        '  exec "$INSTALL_PYTHON" -mpre_commit "$@"\n'
        "fi\n"
    )


def test_install_precommit_hook_updates_framework_config_and_entrypoint_guard(tmp_path: Path) -> None:
    config_path = tmp_path / ".pre-commit-config.yaml"
    config_path.write_text(yaml.safe_dump({"repos": []}, sort_keys=False), encoding="utf-8")
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks.install_precommit_hook(tmp_path)

    content = hook_file.read_text(encoding="utf-8")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    local_repo = next(repo for repo in config["repos"] if repo["repo"] == "local")
    assert local_repo["hooks"][0]["id"] == hooks.DOCS_CHECK_MARKER
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content


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
    old_guard = f"# {hooks._OLD_OVERLAP_MARKER}\necho old guard\n"
    hook_file.write_text(
        _make_precommit_entrypoint(extra=old_guard),
        encoding="utf-8",
    )

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert hooks._OLD_OVERLAP_MARKER not in content
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content


def test_ensure_precommit_entrypoint_guard_is_idempotent(tmp_path: Path) -> None:
    hook_file = tmp_path / "pre-commit"
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks._ensure_precommit_entrypoint_guard(hook_file)
    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert content.count(hooks.STASH_PREVENTION_MARKER) == 1
    assert content.count(hooks.RESTAGE_MARKER) == 1


def test_ensure_precommit_entrypoint_guard_replaces_existing_restage_block(tmp_path: Path) -> None:
    """When the installed wrapper has an outdated RESTAGE block, re-running must replace it."""
    hook_file = tmp_path / "pre-commit"
    outdated = (
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/tmp/python\n"
        "ARGS=()\n"
        f"# {hooks.STASH_PREVENTION_MARKER}: old stash guard\n"
        f"# {hooks.RESTAGE_MARKER}: outdated block\n"
        "echo outdated-restage-logic\n"
        "exit 1\n"
    )
    hook_file.write_text(outdated, encoding="utf-8")

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert "outdated-restage-logic" not in content
    assert content.count(hooks.RESTAGE_MARKER) == 1


def test_ensure_precommit_entrypoint_guard_restores_restage_retry_logic(tmp_path: Path) -> None:
    hook_file = tmp_path / "pre-commit"
    hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert "_pre_staged" in content
    assert "_teleclaude_run_precommit" in content
    assert "git add -- $_modified" in content
    assert "Restaged formatter-modified files; re-running pre-commit..." in content
    assert 'exec "$INSTALL_PYTHON" -mpre_commit "${ARGS[@]}"' not in content


def test_ensure_precommit_entrypoint_guard_cleans_up_legacy_staging_marker(tmp_path: Path) -> None:
    """Legacy session-scoped-staging marker is removed on re-run."""
    hook_file = tmp_path / "pre-commit"
    legacy = (
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/tmp/python\n"
        "ARGS=()\n"
        "# teleclaude-session-scoped-staging: legacy block\n"
        "echo legacy-staging\n"
    )
    hook_file.write_text(legacy, encoding="utf-8")

    hooks._ensure_precommit_entrypoint_guard(hook_file)

    content = hook_file.read_text(encoding="utf-8")
    assert "legacy-staging" not in content
    assert "teleclaude-session-scoped-staging" not in content
    assert hooks.STASH_PREVENTION_MARKER in content
    assert hooks.RESTAGE_MARKER in content


class TestEntrypointGuardBlockOrdering:
    """Verify the guard produces blocks in the correct sequence."""

    @pytest.mark.unit
    def test_blocks_appear_in_correct_order(self, tmp_path: Path) -> None:
        hook_file = tmp_path / "pre-commit"
        hook_file.write_text(_make_precommit_entrypoint(), encoding="utf-8")

        hooks._ensure_precommit_entrypoint_guard(hook_file)

        content = hook_file.read_text(encoding="utf-8")
        stash_pos = content.index(hooks.STASH_PREVENTION_MARKER)
        restage_pos = content.index(hooks.RESTAGE_MARKER)
        assert stash_pos < restage_pos
