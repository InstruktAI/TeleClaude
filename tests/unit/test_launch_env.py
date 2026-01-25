"""Tests for daemon launch environment defaults."""

from pathlib import Path


def test_wrapper_prefixes_venv_path() -> None:
    """Test that the wrapper script prepends the venv bin directory."""
    repo_root = Path(__file__).resolve().parents[2]
    wrapper = (repo_root / "bin" / "teleclaude-wrapper.sh").read_text(encoding="utf-8")
    assert 'PATH=".venv/bin:$PATH"' in wrapper


def test_launchd_template_prefixes_venv_path() -> None:
    """Test that the launchd template prepends the venv bin directory."""
    repo_root = Path(__file__).resolve().parents[2]
    template = (repo_root / "config" / "ai.instrukt.teleclaude.daemon.plist.template").read_text(encoding="utf-8")
    assert "<string>.venv/bin:{{PATH}}</string>" in template
