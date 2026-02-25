"""Tests for teleclaude.sync — the sync orchestrator."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from teleclaude.sync import sync


def _write_snippet(path: Path, *, id: str, type: str = "spec", scope: str = "project", desc: str = "Test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {id}\ntype: {type}\nscope: {scope}\ndescription: {desc}\n---\n\n# Title\n\n## Body\n\nContent.\n",
        encoding="utf-8",
    )


@pytest.mark.unit
class TestSync:
    def test_validate_only_does_not_build(self, tmp_path: Path) -> None:
        _write_snippet(tmp_path / "docs" / "project" / "test.md", id="test/x")
        with patch("teleclaude.sync._run_distribute") as mock:
            ok = sync(tmp_path, validate_only=True)
        assert ok is True
        mock.assert_not_called()

    def test_empty_project_succeeds(self, tmp_path: Path) -> None:
        with patch("teleclaude.sync._run_distribute"):
            ok = sync(tmp_path)
        assert ok is True

    def test_warn_only_returns_true_on_errors(self, tmp_path: Path) -> None:
        # Create an artifact with a validation error
        agents_dir = tmp_path / ".agents" / "commands"
        agents_dir.mkdir(parents=True)
        cmd = agents_dir / "bad.md"
        cmd.write_text("---\n---\n\n# No description\n\nBody only.\n")
        with patch("teleclaude.sync._run_distribute"):
            ok = sync(tmp_path, warn_only=True)
        assert ok is True  # warn_only means no failure

    def test_full_sync_calls_distribute(self, tmp_path: Path) -> None:
        _write_snippet(tmp_path / "docs" / "project" / "test.md", id="test/x")
        calls = []

        def record_distribute(*args, **kwargs):
            calls.append((args, kwargs))

        with patch("teleclaude.sync._run_distribute", new=record_distribute):
            sync(tmp_path)
        assert len(calls) == 1

    def test_sync_registers_project_manifest_when_config_exists(self, tmp_path: Path) -> None:
        config = {
            "project_name": "teleclaude",
            "description": "Project docs",
            "business": {"domains": {"software-development": "docs"}},
        }
        (tmp_path / "teleclaude.yml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        _write_snippet(tmp_path / "docs" / "project" / "test.md", id="project/spec/x")
        with (
            patch("teleclaude.sync._run_distribute"),
            patch("teleclaude.sync.register_project") as mock_register,
        ):
            ok = sync(tmp_path)
        assert ok is True
        mock_register.assert_called_once()

    def test_sync_skips_manifest_registration_for_bare_repo(self, tmp_path: Path) -> None:
        _write_snippet(tmp_path / "docs" / "project" / "test.md", id="project/spec/x")
        with (
            patch("teleclaude.sync._run_distribute"),
            patch("teleclaude.sync.register_project") as mock_register,
        ):
            ok = sync(tmp_path)
        assert ok is True
        mock_register.assert_not_called()
