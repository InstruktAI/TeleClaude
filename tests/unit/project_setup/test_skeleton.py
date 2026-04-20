# guard: no-companion
"""Tests for R4: telec init skeleton deployment.

Behavioral contracts for skeleton file deployment during telec init:
language-aware deployment, no-overwrite, project name substitution.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.project_setup.skeleton import deploy_skeleton

# ---------------------------------------------------------------------------
# R4.1 — Python skeleton deployed to empty project
# ---------------------------------------------------------------------------


class TestSkeletonDeployment:
    """When language is declared in teleclaude.yml, init deploys skeleton files."""

    def test_deploy_creates_pyproject_toml(self, tmp_path: Path) -> None:
        """Deploying Python skeleton creates pyproject.toml in an empty project."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "pyproject.toml").exists(), "pyproject.toml was not deployed"

    def test_deploy_creates_precommit_config(self, tmp_path: Path) -> None:
        """Deploying Python skeleton creates .pre-commit-config.yaml with real content."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        precommit = tmp_path / ".pre-commit-config.yaml"
        assert precommit.exists(), ".pre-commit-config.yaml was not deployed"
        content = precommit.read_text(encoding="utf-8")
        assert "repos:" in content or "repo:" in content, (
            "Deployed .pre-commit-config.yaml lacks repo entries — not production-grade"
        )

    def test_deploy_creates_makefile(self, tmp_path: Path) -> None:
        """Deploying Python skeleton creates a Makefile with real targets."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        makefile = tmp_path / "Makefile"
        assert makefile.exists(), "Makefile was not deployed"
        content = makefile.read_text(encoding="utf-8")
        assert "lint:" in content or "lint :" in content, (
            "Deployed Makefile lacks 'lint:' target — not production-grade"
        )

    def test_deployed_pyproject_is_non_trivial(self, tmp_path: Path) -> None:
        """Deployed pyproject.toml contains actual tool configuration (not a stub)."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        # Must contain tool configuration, not just the project header
        assert "[tool.ruff]" in content, "Deployed pyproject.toml lacks [tool.ruff] section"
        assert "[tool.pyright]" in content or "pyrightconfig" in content or "typeCheckingMode" in content, (
            "Deployed pyproject.toml lacks pyright configuration"
        )


# ---------------------------------------------------------------------------
# R4.1b — Skeleton deployment reads languages list
# ---------------------------------------------------------------------------


class TestSkeletonMultiLanguage:
    """Skeleton deployment reads the languages list field."""

    def test_deploy_reads_languages_list(self, tmp_path: Path) -> None:
        """teleclaude.yml with languages: [python] triggers Python skeleton deployment."""
        (tmp_path / "teleclaude.yml").write_text("languages:\n  - python\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "pyproject.toml").exists(), "Python skeleton not deployed from languages list"

    def test_deploy_skips_unrecognized_language(self, tmp_path: Path) -> None:
        """Unrecognized languages in the list are skipped, not errored."""
        (tmp_path / "teleclaude.yml").write_text("languages:\n  - cobol\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert not (tmp_path / "pyproject.toml").exists(), "No skeleton expected for unrecognized language"


# ---------------------------------------------------------------------------
# R4.2 — Existing files are never overwritten
# ---------------------------------------------------------------------------


class TestNoOverwrite:
    """Skeleton deployment must never overwrite files that already exist."""

    def test_existing_pyproject_not_overwritten(self, tmp_path: Path) -> None:
        """An existing pyproject.toml is not modified by skeleton deployment."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        original = "[project]\nname = 'custom'\n"
        (tmp_path / "pyproject.toml").write_text(original, encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == original

    def test_existing_precommit_not_overwritten(self, tmp_path: Path) -> None:
        """An existing .pre-commit-config.yaml is not modified by skeleton deployment."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        original = "repos: []\n"
        (tmp_path / ".pre-commit-config.yaml").write_text(original, encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8") == original

    def test_existing_makefile_not_overwritten(self, tmp_path: Path) -> None:
        """An existing Makefile is not modified by skeleton deployment."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        original = "custom: echo hello\n"
        (tmp_path / "Makefile").write_text(original, encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "Makefile").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# R4.3 — No deployment when no language declared
# ---------------------------------------------------------------------------


class TestNoDeploymentWithoutLanguage:
    """When teleclaude.yml declares no language, no skeleton files are deployed."""

    def test_no_language_means_no_pyproject(self, tmp_path: Path) -> None:
        """No pyproject.toml deployed when teleclaude.yml has no language field."""
        (tmp_path / "teleclaude.yml").write_text("business:\n  domains: {}\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert not (tmp_path / "pyproject.toml").exists(), (
            "pyproject.toml was deployed despite no language being declared"
        )

    def test_no_language_means_no_makefile(self, tmp_path: Path) -> None:
        """No Makefile deployed when teleclaude.yml has no language field."""
        (tmp_path / "teleclaude.yml").write_text("{}\n", encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert not (tmp_path / "Makefile").exists(), "Makefile was deployed despite no language being declared"

    def test_missing_teleclaude_yml_deploys_nothing(self, tmp_path: Path) -> None:
        """When teleclaude.yml is absent, deployment is silently skipped."""
        deploy_skeleton(project_root=tmp_path)
        # None of the skeleton files should appear
        assert not (tmp_path / "pyproject.toml").exists()
        assert not (tmp_path / ".pre-commit-config.yaml").exists()
        assert not (tmp_path / "Makefile").exists()


# ---------------------------------------------------------------------------
# R4.4 — Project name substitution
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3A — Diff-and-prompt for existing files
# ---------------------------------------------------------------------------


class TestDiffAndPrompt:
    """When a file exists and differs from template, skeleton shows diff and prompts."""

    def test_identical_file_is_skipped_silently(self, tmp_path: Path) -> None:
        """Existing file identical to template content is skipped without output."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        # Deploy once to get the template content
        deploy_skeleton(project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

        # Deploy again — should skip silently (no exception, no change)
        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == content

    def test_different_file_not_overwritten_non_interactive(self, tmp_path: Path) -> None:
        """In non-interactive mode, differing files are skipped (not overwritten)."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        original = "[project]\nname = 'custom'\n"
        (tmp_path / "pyproject.toml").write_text(original, encoding="utf-8")

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 3B — TypeScript skeleton templates
# ---------------------------------------------------------------------------


class TestTypeScriptSkeleton:
    """TypeScript skeleton templates deploy to frontend_root."""

    def test_typescript_skeleton_deployed_to_frontend_root(self, tmp_path: Path) -> None:
        """TypeScript skeleton files deploy under the frontend_root directory."""
        (tmp_path / "teleclaude.yml").write_text(
            "languages:\n  - typescript\nfrontend_root: frontend\n",
            encoding="utf-8",
        )
        (tmp_path / "frontend").mkdir()

        deploy_skeleton(project_root=tmp_path)
        # At minimum, tsconfig.json should be deployed
        assert (tmp_path / "frontend" / "tsconfig.json").exists(), "tsconfig.json not deployed to frontend/"

    def test_typescript_skeleton_default_frontend_dir(self, tmp_path: Path) -> None:
        """When frontend_root is not set, defaults to frontend/."""
        (tmp_path / "teleclaude.yml").write_text(
            "languages:\n  - typescript\n",
            encoding="utf-8",
        )
        (tmp_path / "frontend").mkdir()

        deploy_skeleton(project_root=tmp_path)
        assert (tmp_path / "frontend" / "tsconfig.json").exists()


# ---------------------------------------------------------------------------
# R4.4 — Project name substitution
# ---------------------------------------------------------------------------


class TestProjectNameSubstitution:
    """Project name in deployed configuration defaults to the directory name."""

    def test_pyproject_contains_directory_name_as_project_name(self, tmp_path: Path) -> None:
        """Deployed pyproject.toml has the directory name as the project name."""
        project_dir = tmp_path / "my-new-project"
        project_dir.mkdir()
        (project_dir / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        deploy_skeleton(project_root=project_dir)
        content = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
        assert "my-new-project" in content, (
            f"Project name 'my-new-project' not found in deployed pyproject.toml:\n{content[:500]}"
        )
