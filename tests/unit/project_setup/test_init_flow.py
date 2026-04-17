# pylint: disable=protected-access,consider-using-from-import
"""Characterization tests for teleclaude.project_setup.init_flow."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import teleclaude.project_setup.init_flow as init_flow


def test_is_teleclaude_project_detects_repo_layout(tmp_path: Path) -> None:
    marker = tmp_path / "teleclaude" / "project_setup" / "init_flow.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("# marker\n", encoding="utf-8")

    assert init_flow._is_teleclaude_project(tmp_path) is True
    assert init_flow._is_teleclaude_project(tmp_path / "other") is False


def test_prompt_yes_no_returns_default_when_stdin_is_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert init_flow._prompt_yes_no("Proceed?", default=False) is False


def test_prompt_release_channel_updates_stable_channel_and_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "deployment:\n  channel: alpha\n  pinned_minor: ''\n",
        encoding="utf-8",
    )
    answers = iter(["stable", "1.2"])
    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    init_flow._prompt_release_channel(tmp_path)

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert payload["deployment"] == {"channel": "stable", "pinned_minor": "1.2"}


def test_init_project_writes_project_slug_and_registers_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``telec init`` must ensure ``project_slug`` is set and register the root.

    Registration ownership moved out of ``telec sync`` — ``telec init`` is the
    sole writer of ``~/.teleclaude/projects.yaml``. Identity is carried by the
    slug; when the project config lacks one, init must derive it from the
    existing ``project_name`` (or the directory name) and persist it.
    """
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text("project_name: My Project\n", encoding="utf-8")

    manifest_path = tmp_path / "state" / "projects.yaml"

    # Stub every I/O-heavy init side effect so the test stays unit-scoped and
    # the only remaining behavior we observe is the registration step.
    monkeypatch.setattr(init_flow, "configure_agent_cli", lambda: None)
    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_hooks_path", lambda _p: None)
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _p: None)
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _p: None)
    monkeypatch.setattr(init_flow, "install_precommit_hook", lambda _p: None)
    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _p: None)
    monkeypatch.setattr(init_flow, "install_docs_watch", lambda _p: None)
    monkeypatch.setattr(init_flow, "is_macos", lambda: False)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _p: None)
    monkeypatch.setattr(init_flow, "_offer_enrichment", lambda _p: None)
    # seed_event_domains is imported lazily; patch at source.
    import teleclaude.project_setup.domain_seeds as domain_seeds  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(domain_seeds, "seed_event_domains", lambda _p: None)

    # Redirect the manifest to a test-local path.
    from teleclaude import project_manifest  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

    init_flow.init_project(project_root)

    # Slug must be persisted in teleclaude.yml.
    config_payload = yaml.safe_load((project_root / "teleclaude.yml").read_text(encoding="utf-8"))
    assert config_payload["project_slug"] == "my-project"

    # Registry must contain the project root.
    assert manifest_path.exists()
    registry = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    registered = registry.get("projects", [])
    assert str(project_root.resolve()) in registered


def test_init_project_writes_project_slug_for_fresh_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh projects must get a ``project_slug`` after init, not before.

    Regression guard for F1: ``sync_project_artifacts`` creates a bare
    ``teleclaude.yml`` on first run (via ``ensure_project_config``), so the
    slug-writing step must execute *after* sync, not before. Previously
    ``_ensure_project_slug`` ran first and returned silently when the file
    did not yet exist, leaving fresh projects registered without a slug.
    """
    project_root = tmp_path / "fresh_project"
    project_root.mkdir()
    # Intentionally do NOT pre-create teleclaude.yml.

    manifest_path = tmp_path / "state" / "projects.yaml"

    def fake_sync_project_artifacts(root: Path) -> None:
        """Simulate the real sync which creates a bare teleclaude.yml."""
        config_path = root / "teleclaude.yml"
        if not config_path.exists():
            config_path.write_text(
                "business:\n  domains:\n    software-development: docs\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(init_flow, "configure_agent_cli", lambda: None)
    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_hooks_path", lambda _p: None)
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _p: None)
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _p: None)
    monkeypatch.setattr(init_flow, "install_precommit_hook", lambda _p: None)
    monkeypatch.setattr(init_flow, "sync_project_artifacts", fake_sync_project_artifacts)
    monkeypatch.setattr(init_flow, "install_docs_watch", lambda _p: None)
    monkeypatch.setattr(init_flow, "is_macos", lambda: False)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _p: None)
    monkeypatch.setattr(init_flow, "_offer_enrichment", lambda _p: None)
    import teleclaude.project_setup.domain_seeds as domain_seeds  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(domain_seeds, "seed_event_domains", lambda _p: None)

    from teleclaude import project_manifest  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

    init_flow.init_project(project_root)

    # Slug must be persisted, derived from the directory name.
    config_payload = yaml.safe_load((project_root / "teleclaude.yml").read_text(encoding="utf-8"))
    assert config_payload.get("project_slug") == "fresh-project"

    # Registry must still include the fresh project.
    assert manifest_path.exists()
    registry = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert str(project_root.resolve()) in registry.get("projects", [])


def test_ensure_project_slug_raises_when_slug_cannot_be_derived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_ensure_project_slug`` must fail fast when no slug can be derived.

    Regression guard for F1 Principles finding: the helper previously logged
    a warning and returned, silently leaving ``project_slug`` unset. It must
    now raise so the init pipeline surfaces the contract failure instead of
    degrading.
    """
    project_root = tmp_path / "clean"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text("project_name: ''\n", encoding="utf-8")

    # Force normalize_slug to yield an empty string so the helper has no
    # fallback available for derivation.
    monkeypatch.setattr(init_flow, "normalize_slug", lambda _value: "")

    with pytest.raises(RuntimeError, match="project_slug"):
        init_flow._ensure_project_slug(project_root)


class TestDetectAndSetLanguages:
    """_detect_and_set_languages scans project root for language indicators."""

    def test_detects_python_from_pyproject_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pyproject.toml presence triggers Python detection."""
        (tmp_path / "teleclaude.yml").write_text("project_name: test\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
        monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

        init_flow._detect_and_set_languages(tmp_path)

        config = yaml.safe_load((tmp_path / "teleclaude.yml").read_text(encoding="utf-8"))
        assert "python" in config.get("languages", [])

    def test_detects_typescript_from_package_json_with_dep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """package.json with typescript in devDeps triggers TypeScript detection."""
        (tmp_path / "teleclaude.yml").write_text("project_name: test\n", encoding="utf-8")
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"devDependencies": {"typescript": "^5.0"}}', encoding="utf-8")
        (frontend / "tsconfig.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

        init_flow._detect_and_set_languages(tmp_path)

        config = yaml.safe_load((tmp_path / "teleclaude.yml").read_text(encoding="utf-8"))
        assert "typescript" in config.get("languages", [])
        assert config.get("frontend_root") == "frontend"

    def test_no_indicators_leaves_config_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No language indicators leaves languages unset."""
        (tmp_path / "teleclaude.yml").write_text("project_name: test\n", encoding="utf-8")
        monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

        init_flow._detect_and_set_languages(tmp_path)

        config = yaml.safe_load((tmp_path / "teleclaude.yml").read_text(encoding="utf-8"))
        assert config.get("languages") is None or config.get("languages") == []

    def test_skips_when_config_already_matches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No config write when detected matches existing."""
        (tmp_path / "teleclaude.yml").write_text("project_name: test\nlanguages:\n  - python\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

        original_mtime = (tmp_path / "teleclaude.yml").stat().st_mtime
        init_flow._detect_and_set_languages(tmp_path)
        # File should not have been rewritten
        new_mtime = (tmp_path / "teleclaude.yml").stat().st_mtime
        assert original_mtime == new_mtime

    def test_detects_python_from_setup_py(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """setup.py presence triggers Python detection."""
        (tmp_path / "teleclaude.yml").write_text("project_name: test\n", encoding="utf-8")
        (tmp_path / "setup.py").write_text("from setuptools import setup\n", encoding="utf-8")
        monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

        init_flow._detect_and_set_languages(tmp_path)

        config = yaml.safe_load((tmp_path / "teleclaude.yml").read_text(encoding="utf-8"))
        assert "python" in config.get("languages", [])

    def test_detects_typescript_from_tsconfig_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """tsconfig.json in project root triggers TypeScript detection."""
        (tmp_path / "teleclaude.yml").write_text("project_name: test\n", encoding="utf-8")
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

        init_flow._detect_and_set_languages(tmp_path)

        config = yaml.safe_load((tmp_path / "teleclaude.yml").read_text(encoding="utf-8"))
        assert "typescript" in config.get("languages", [])


def test_offer_enrichment_launches_refresh_for_reinitialized_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches: list[object] = []

    def has_generated_snippets(project_root: Path) -> bool:
        _ = project_root
        return True

    def prompt_yes_no(prompt: str) -> bool:
        _ = prompt
        return True

    def launch_enrichment(project_root: Path) -> None:
        launches.append(project_root)

    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(init_flow, "_has_generated_snippets", has_generated_snippets)
    monkeypatch.setattr(init_flow, "_prompt_yes_no", prompt_yes_no)
    monkeypatch.setattr(init_flow, "_launch_enrichment", launch_enrichment)
    monkeypatch.setattr(init_flow, "_launch_config_assessment", lambda _p: None)

    init_flow._offer_enrichment(tmp_path)

    assert launches == [tmp_path]


def test_offer_enrichment_launches_both_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When user approves enrichment, both doc snippets and config assessment sessions launch."""
    enrichment_launches: list[Path] = []
    assessment_launches: list[Path] = []

    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(init_flow, "_has_generated_snippets", lambda _p: False)
    monkeypatch.setattr(init_flow, "_prompt_yes_no", lambda _prompt: True)
    monkeypatch.setattr(init_flow, "_launch_enrichment", enrichment_launches.append)
    monkeypatch.setattr(init_flow, "_launch_config_assessment", assessment_launches.append)

    init_flow._offer_enrichment(tmp_path)

    assert enrichment_launches == [tmp_path], "Enrichment session not launched"
    assert assessment_launches == [tmp_path], "Config assessment session not launched"
