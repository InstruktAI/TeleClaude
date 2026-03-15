"""Characterization tests for teleclaude.install.install_hooks."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.install import install_hooks

pytestmark = pytest.mark.unit


class TestExtractReceiverScript:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("python /tmp/receiver.py --agent claude", install_hooks.RECEIVER_TOKEN),
            ("python /tmp/receiver/__main__.py --agent gemini", install_hooks.RECEIVER_TOKEN),
            (["python", "/tmp/custom_receiver.py"], install_hooks.RECEIVER_TOKEN),
        ],
    )
    def test_normalizes_receiver_variants(self, command: str | list[object], expected: str) -> None:
        assert install_hooks._extract_receiver_script(command) == expected


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

        merged = install_hooks.merge_hooks(existing, new)

        hooks = merged["Stop"][0]["hooks"]
        assert hooks == [{"command": "/usr/bin/custom-hook"}, {"command": "/new/receiver.py --agent claude"}]


class TestPruneAgentHooks:
    def test_removes_teleclaude_hooks_from_disallowed_events(self) -> None:
        existing = {
            "Stop": [{"matcher": "*", "hooks": [{"command": "/tmp/receiver.py --agent claude"}]}],
            "SessionStart": [{"matcher": "*", "hooks": [{"command": "/tmp/receiver.py --agent claude"}]}],
            "custom": {"preserve": True},
        }

        pruned = install_hooks._prune_agent_hooks(existing, {"SessionStart"})

        assert "Stop" not in pruned
        assert pruned["SessionStart"][0]["hooks"] == [{"command": "/tmp/receiver.py --agent claude"}]
        assert pruned["custom"] == {"preserve": True}


class TestCodexMcpConfig:
    def test_ensure_codex_mcp_servers_appends_stdio_sections(self) -> None:
        content = ""

        updated = install_hooks._ensure_codex_mcp_servers(content, {"teleclaude": {"command": "uvx", "args": ["a"]}})

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

        resolved = install_hooks.resolve_main_repo_root(worktree)

        assert resolved == main_repo
