# guard: no-companion
# pylint: disable=protected-access
"""Test specifications for teleclaude.install.configure_agent_cli.

Covers:
  R1 — Module rename: configure_agent_cli is importable at the new path, and all
       internal references (guardrails.py, init_flow.py) are updated.
  R2 — Shell wrapper inlining: setup_agent_hooks.sh removed; bin/init.sh updated.
  R3 — Repo-owned compaction prompt source file exists with correct content.
  R4 — Compaction prompt deployment: file written, TOML key set, idempotent,
       and delivered via the settings/codex.json override mechanism.
  R6 — Prototype .codex/ files absent from the repository (regression guards).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.install import configure_agent_cli
from teleclaude.install.configure_agent_cli import configure_claude, configure_codex, configure_gemini

pytestmark = pytest.mark.unit

COMPACTION_PROMPT_FILENAME = "CODEX.compaction.md"
COMPACT_PROMPT_TOML_KEY = "experimental_compact_prompt_file"

# Repo root: tests/unit/install/ → tests/unit/ → tests/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# R1 — Module rename
# ---------------------------------------------------------------------------


def test_configure_agent_cli_module_is_importable() -> None:
    assert configure_agent_cli.__file__


def test_configure_codex_callable_from_renamed_module() -> None:
    assert callable(configure_codex)


def test_configure_claude_and_gemini_callable_from_renamed_module() -> None:
    assert callable(configure_claude)
    assert callable(configure_gemini)


# ---------------------------------------------------------------------------
# R4 — Compaction prompt deployment
# ---------------------------------------------------------------------------


def test_configure_codex_writes_compaction_prompt_to_codex_dir(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    prompt_file = codex_dir / COMPACTION_PROMPT_FILENAME
    assert prompt_file.exists(), f"Compaction prompt must be written to {prompt_file}"
    source = (_REPO_ROOT / "teleclaude" / "install" / "settings" / COMPACTION_PROMPT_FILENAME).read_text(
        encoding="utf-8"
    )
    assert prompt_file.read_text(encoding="utf-8") == source, (
        "Deployed compaction prompt content must exactly match the repo-owned source file"
    )


def test_configure_codex_sets_compact_prompt_toml_key(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config_path = codex_dir / "config.toml"
    assert config_path.exists(), "config.toml must be created by configure_codex"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert COMPACT_PROMPT_TOML_KEY in config, f"config.toml must contain '{COMPACT_PROMPT_TOML_KEY}'"
    value = config[COMPACT_PROMPT_TOML_KEY]
    assert isinstance(value, str) and value.strip(), f"'{COMPACT_PROMPT_TOML_KEY}' must be a non-empty file path string"


def test_configure_codex_compaction_prompt_deployment_is_idempotent(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)
        config_after_first = (codex_dir / "config.toml").read_text(encoding="utf-8")

        configure_codex(tmp_path)
        config_after_second = (codex_dir / "config.toml").read_text(encoding="utf-8")

    assert config_after_first == config_after_second, (
        "configure_codex must be idempotent: config.toml must not change on re-run"
    )


def test_compact_prompt_key_sourced_from_settings_override(tmp_path: Path) -> None:
    """The experimental_compact_prompt_file value in config.toml must match settings/codex.json — verifying the
    override mechanism is the actual delivery path, not incidental hardcoding."""
    settings_path = Path(configure_agent_cli.__file__).parent / "settings" / "codex.json"
    assert settings_path.exists(), "teleclaude/install/settings/codex.json must exist"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert COMPACT_PROMPT_TOML_KEY in settings, (
        f"settings/codex.json must contain '{COMPACT_PROMPT_TOML_KEY}' "
        "so the existing override mechanism delivers it to config.toml"
    )

    # End-to-end: verify the deployed config.toml value is sourced from the override, not hardcoded
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert config[COMPACT_PROMPT_TOML_KEY] == settings[COMPACT_PROMPT_TOML_KEY], (
        f"config.toml['{COMPACT_PROMPT_TOML_KEY}'] must equal settings/codex.json['{COMPACT_PROMPT_TOML_KEY}'] — "
        "the settings override mechanism must be the delivery path"
    )


def test_configure_codex_omits_compact_prompt_key_when_prompt_source_missing(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    broken_settings_dir = tmp_path / "broken-settings"
    broken_settings_dir.mkdir()
    (broken_settings_dir / "codex.json").write_text(
        json.dumps({COMPACT_PROMPT_TOML_KEY: COMPACTION_PROMPT_FILENAME}),
        encoding="utf-8",
    )

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(configure_agent_cli, "SETTINGS_DIR", broken_settings_dir),
    ):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert COMPACT_PROMPT_TOML_KEY not in config, (
        "configure_codex must not point config.toml at a compaction prompt file "
        "when the source prompt asset is unavailable"
    )


def test_install_hooks_module_no_longer_exists_on_disk() -> None:
    """The old module path must be absent after the rename — no silent co-existence."""
    assert not (_REPO_ROOT / "teleclaude" / "install" / "install_hooks.py").exists()


def test_bin_init_entry_point_no_longer_exists_at_old_path() -> None:
    """The old CLI entry point stub must be absent after the rename."""
    assert not (_REPO_ROOT / "bin" / "init" / "install_hooks.py").exists()


# ---------------------------------------------------------------------------
# R1 — Internal reference updates
# ---------------------------------------------------------------------------


def test_guardrails_exclusion_list_references_renamed_module() -> None:
    """guardrails.py loose-dict exclusion list must reference configure_agent_cli.py after the rename."""
    content = (_REPO_ROOT / "tools" / "lint" / "guardrails.py").read_text(encoding="utf-8")
    assert "configure_agent_cli.py" in content, (
        "tools/lint/guardrails.py must list configure_agent_cli.py in its exclusion list"
    )


def test_init_flow_imports_renamed_module() -> None:
    """init_flow.py must import the agent CLI configurator under its new module identity."""
    content = (_REPO_ROOT / "teleclaude" / "project_setup" / "init_flow.py").read_text(encoding="utf-8")
    assert "configure_agent_cli" in content, (
        "teleclaude/project_setup/init_flow.py must import from configure_agent_cli, not install_hooks"
    )


# ---------------------------------------------------------------------------
# R2 — Shell wrapper inlining
# ---------------------------------------------------------------------------


def test_setup_agent_hooks_shell_script_removed() -> None:
    """bin/init/setup_agent_hooks.sh must no longer exist after its behavior is inlined into bin/init.sh."""
    assert not (_REPO_ROOT / "bin" / "init" / "setup_agent_hooks.sh").exists(), (
        "bin/init/setup_agent_hooks.sh must be removed — its invocation is inlined into bin/init.sh"
    )


def test_bin_init_does_not_source_removed_script() -> None:
    """bin/init.sh must not source setup_agent_hooks.sh after the standalone script is removed."""
    content = (_REPO_ROOT / "bin" / "init.sh").read_text(encoding="utf-8")
    assert "setup_agent_hooks.sh" not in content, (
        "bin/init.sh must not source setup_agent_hooks.sh — the script no longer exists"
    )


def test_bin_init_invokes_renamed_python_entry_point() -> None:
    """bin/init.sh must invoke the renamed Python entry point for agent CLI configuration."""
    content = (_REPO_ROOT / "bin" / "init.sh").read_text(encoding="utf-8")
    assert "configure_agent_cli.py" in content, (
        "bin/init.sh must invoke bin/init/configure_agent_cli.py using PYTHONPATH + venv python"
    )


# ---------------------------------------------------------------------------
# R3 — Repo-owned compaction prompt source
# ---------------------------------------------------------------------------

_SETTINGS_COMPACTION_PROMPT = _REPO_ROOT / "teleclaude" / "install" / "settings" / COMPACTION_PROMPT_FILENAME


def test_compaction_prompt_source_file_exists_in_settings() -> None:
    """A compaction prompt file must be stored in teleclaude/install/settings/ for version-controlled distribution."""
    assert _SETTINGS_COMPACTION_PROMPT.exists(), (
        f"Compaction prompt must exist at {_SETTINGS_COMPACTION_PROMPT} alongside other install-time settings"
    )


def test_compaction_prompt_instructs_preservation_of_marked_content() -> None:
    """The compaction prompt must instruct Codex to preserve content between the context-preservation markers."""
    content = _SETTINGS_COMPACTION_PROMPT.read_text(encoding="utf-8")
    assert "TELECLAUDE_CONTEXT_PRESERVATION_START" in content, (
        "Compaction prompt must reference TELECLAUDE_CONTEXT_PRESERVATION_START"
    )
    assert "TELECLAUDE_CONTEXT_PRESERVATION_END" in content, (
        "Compaction prompt must reference TELECLAUDE_CONTEXT_PRESERVATION_END"
    )


# ---------------------------------------------------------------------------
# R6 — Prototype files absent (regression guards)
# ---------------------------------------------------------------------------


def test_prototype_codex_config_toml_not_in_repository() -> None:
    """.codex/config.toml must not be committed — superseded by the repo-managed install settings path."""
    assert not (_REPO_ROOT / ".codex" / "config.toml").exists(), (
        ".codex/config.toml must not exist in the repository — "
        "use teleclaude/install/settings/codex.json for Codex settings"
    )


def test_prototype_codex_compaction_md_not_in_repository() -> None:
    """.codex/CODEX.compaction.md must not be committed — superseded by teleclaude/install/settings/."""
    assert not (_REPO_ROOT / ".codex" / COMPACTION_PROMPT_FILENAME).exists(), (
        ".codex/CODEX.compaction.md must not exist in the repository — "
        f"the canonical source is teleclaude/install/settings/{COMPACTION_PROMPT_FILENAME}"
    )


# ---------------------------------------------------------------------------
# Characterization coverage carried forward from test_install_hooks.py
# ---------------------------------------------------------------------------


class TestExtractReceiverScript:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("python /tmp/receiver.py --agent claude", "receiver"),
            ("python /tmp/receiver/__main__.py --agent gemini", "receiver"),
            (["python", "/tmp/custom_receiver.py"], "receiver"),
        ],
    )
    def test_normalizes_receiver_variants(self, command: str | list[object], expected: str) -> None:
        assert configure_agent_cli._extract_receiver_script(command) == expected


class TestMergeHooks:
    def test_replaces_existing_receiver_hook_but_keeps_foreign_hooks(self) -> None:
        existing = {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"command": "/old/receiver.py --agent claude"},
                        {"command": "/usr/bin/custom-hook"},
                    ],
                }
            ]
        }
        new = {"Stop": {"command": "/new/receiver.py --agent claude"}}

        merged = configure_agent_cli.merge_hooks(existing, new)

        hooks = merged["Stop"][0]["hooks"]
        assert hooks == [{"command": "/usr/bin/custom-hook"}, {"command": "/new/receiver.py --agent claude"}]


class TestPruneAgentHooks:
    def test_removes_teleclaude_hooks_from_disallowed_events(self) -> None:
        existing = {
            "Stop": [{"matcher": "*", "hooks": [{"command": "/tmp/receiver.py --agent claude"}]}],
            "SessionStart": [{"matcher": "*", "hooks": [{"command": "/tmp/receiver.py --agent claude"}]}],
            "custom": {"preserve": True},
        }

        pruned = configure_agent_cli._prune_agent_hooks(existing, {"SessionStart"})

        assert "Stop" not in pruned
        assert pruned["SessionStart"][0]["hooks"] == [{"command": "/tmp/receiver.py --agent claude"}]
        assert pruned["custom"] == {"preserve": True}


class TestCodexMcpConfig:
    def test_ensure_codex_mcp_servers_appends_stdio_sections(self) -> None:
        content = ""

        updated = configure_agent_cli._ensure_codex_mcp_servers(
            content, {"teleclaude": {"command": "uvx", "args": ["a"]}}
        )

        assert "[mcp_servers]" in updated
        assert "[mcp_servers.teleclaude]" in updated
        assert 'type="stdio"' in updated
        assert 'command="uvx"' in updated


class TestResolveMainRepoRoot:
    def test_follows_worktree_gitdir_to_main_repository(self, tmp_path: Path) -> None:
        main_repo = tmp_path / "main"
        worktree = tmp_path / "worktree"
        gitdir = main_repo / ".git" / "worktrees" / "demo"
        gitdir.mkdir(parents=True)
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

        resolved = configure_agent_cli.resolve_main_repo_root(worktree)

        assert resolved == main_repo
