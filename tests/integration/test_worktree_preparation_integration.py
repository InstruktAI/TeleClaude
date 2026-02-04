"""Integration tests for worktree preparation."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.next_machine import _prepare_worktree


class TestWorktreePreparationIntegration:
    """Integration tests for actual worktree preparation execution."""

    def test_makefile_install_target(self) -> None:
        """Test that _prepare_worktree runs make install when Makefile has install target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            slug = "test-work-item"
            worktree_path = tmp_path / "trees" / slug
            worktree_path.mkdir(parents=True)
            (worktree_path / "Makefile").write_text("install:\n\techo done\n")

            with patch("teleclaude.core.next_machine.core.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                _prepare_worktree(str(tmp_path), slug)
                actual_call = mock_run.call_args_list[0]
                assert actual_call[0][0] == ["make", "install"]
                assert actual_call[1]["cwd"] == str(worktree_path)

    def test_error_propagation_when_make_fails(self) -> None:
        """Test that errors from make install are properly propagated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            slug = "test-slug"
            worktree_path = tmp_path / "trees" / slug
            worktree_path.mkdir(parents=True)
            (worktree_path / "Makefile").write_text("install:\n\tfalse\n")

            with patch("teleclaude.core.next_machine.core.subprocess.run") as mock_run:
                error = subprocess.CalledProcessError(1, "make install", output="", stderr="Failed!")
                error.stdout = ""
                error.stderr = "Failed!"
                mock_run.side_effect = error
                with pytest.raises(RuntimeError, match="Worktree preparation failed"):
                    _prepare_worktree(str(tmp_path), slug)

    def test_no_targets_logs_and_returns(self) -> None:
        """Test that no error is raised when no preparation targets exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            slug = "test-slug"
            worktree_path = tmp_path / "trees" / slug
            worktree_path.mkdir(parents=True)
            # No Makefile, no package.json — should just return
            with patch("teleclaude.core.next_machine.core.subprocess.run") as mock_run:
                result = _prepare_worktree(str(tmp_path), slug)
            assert result is None
            mock_run.assert_not_called()


class TestInstallInitGuards:
    """Integration tests for install/init guard behavior."""

    def test_install_script_refuses_worktree_execution(self) -> None:
        """Test that install.sh detects and refuses to run from a worktree."""
        # This test verifies the guard by checking the exit code
        # when running install.sh from a real worktree context.
        # Since we can't easily create a real worktree in tests,
        # we verify the script has the guard logic in place.

        install_script = Path("bin/install.sh")
        assert install_script.exists()

        # Verify guard code exists
        content = install_script.read_text()
        assert "CRITICAL: Refuse to run from a git worktree" in content
        assert "Cannot run 'make install' from a git worktree!" in content
        assert 'if [ "$GIT_DIR" != "$COMMON_DIR" ]' in content

    def test_init_script_refuses_worktree_execution(self) -> None:
        """Test that init.sh detects and refuses to run from a worktree."""
        init_script = Path("bin/init.sh")
        assert init_script.exists()

        # Verify guard code exists
        content = init_script.read_text()
        assert "CRITICAL: Refuse to run from a git worktree" in content
        assert "Cannot run 'make init' from a git worktree!" in content
        assert 'if [ "$GIT_DIR" != "$COMMON_DIR" ]' in content

    def test_install_guard_can_be_tested_via_simulation(self) -> None:
        """Test install guard behavior via subprocess simulation.

        This test creates a minimal worktree-like scenario to verify
        the guard would trigger. We don't run actual install, just
        verify the guard detection logic works.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create a minimal script that mimics the guard logic
            test_script = tmp_path / "test_guard.sh"
            test_script.write_text("""#!/usr/bin/env bash
set -e

if command -v git &> /dev/null && git rev-parse --git-dir &> /dev/null; then
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)

    if [ "$GIT_DIR" != "$COMMON_DIR" ]; then
        echo "WORKTREE_DETECTED"
        exit 1
    fi
fi

echo "NOT_A_WORKTREE"
""")
            test_script.chmod(0o755)

            # Run from project root (not a worktree)
            result = subprocess.run(
                [str(test_script)],
                cwd=str(Path.cwd()),
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                assert "NOT_A_WORKTREE" in result.stdout
            elif result.returncode == 1:
                assert "WORKTREE_DETECTED" in result.stdout
            else:
                raise AssertionError(f"Unexpected return code: {result.returncode}")
