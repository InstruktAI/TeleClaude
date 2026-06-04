"""Characterization tests for teleclaude.project_setup.init_flow."""

from __future__ import annotations

import builtins
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import teleclaude.project_setup.domain_seeds as domain_seeds
import teleclaude.project_setup.init_flow as init_flow
from teleclaude import project_manifest

_SLUG_MY_PROJECT = "my-project"
_SLUG_FRESH_PROJECT = "fresh-project"


def test_is_teleclaude_project_detects_repo_layout(tmp_path: Path) -> None:
    marker = tmp_path / "teleclaude" / "project_setup" / "init_flow.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("# marker\n", encoding="utf-8")

    assert init_flow._is_teleclaude_project(tmp_path) is True
    assert init_flow._is_teleclaude_project(tmp_path / "other") is False


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
    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_hooks_path", lambda _p: None)
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _p: None)
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_precommit_safety_guards", lambda _p: None)
    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _p: None)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _p: None)
    # seed_event_domains is imported lazily; patch at source.
    monkeypatch.setattr(domain_seeds, "seed_event_domains", lambda _p: None)

    # Redirect the manifest to a test-local path.
    monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

    init_flow.init_project(project_root)

    # Slug must be persisted in teleclaude.yml.
    config_payload = yaml.safe_load((project_root / "teleclaude.yml").read_text(encoding="utf-8"))
    assert config_payload["project_slug"] == _SLUG_MY_PROJECT

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

    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_hooks_path", lambda _p: None)
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _p: None)
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_precommit_safety_guards", lambda _p: None)
    monkeypatch.setattr(init_flow, "sync_project_artifacts", fake_sync_project_artifacts)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _p: None)
    monkeypatch.setattr(domain_seeds, "seed_event_domains", lambda _p: None)

    monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

    init_flow.init_project(project_root)

    # Slug must be persisted, derived from the directory name.
    config_payload = yaml.safe_load((project_root / "teleclaude.yml").read_text(encoding="utf-8"))
    assert config_payload.get("project_slug") == _SLUG_FRESH_PROJECT

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


def test_init_project_does_not_spawn_subprocesses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavioral guard: a complete ``init_project`` run must not shell out.

    With every plumbing helper stubbed, the only way a ``subprocess.run`` call
    would reach this spy is if init_project itself dispatched an agent session
    (the regression this refactor prevents). The AI-enrichment dispatchers
    live in ``onboard_flow`` and are not entered through ``init_project``.
    """
    spy_calls: list[list[str]] = []

    def spying_run(cmd: list[str], *_args: object, **_kwargs: object) -> SimpleNamespace:
        spy_calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    project_root = tmp_path / "spied"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text("project_name: Spied\n", encoding="utf-8")

    manifest_path = tmp_path / "state" / "projects.yaml"

    # Stub every plumbing helper so we observe init_project's own behavior in isolation.
    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_hooks_path", lambda _p: None)
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _p: None)
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_precommit_safety_guards", lambda _p: None)
    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _p: None)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _p: None)
    monkeypatch.setattr(domain_seeds, "seed_event_domains", lambda _p: None)
    monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)
    # Spy on the subprocess module itself — any leaked shell-out will be captured.
    monkeypatch.setattr(subprocess, "run", spying_run)

    init_flow.init_project(project_root)

    assert spy_calls == [], f"init_project leaked subprocess calls: {spy_calls}"


def test_init_project_writes_no_global_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Project init must not write machine-global agent or launcher state.

    Behavioral assertion: each global root contains zero files after init_project
    returns. Per ``software-development/policy/test-structure`` rule 6, the
    earlier inventory-snapshot form is replaced with a direct emptiness check.
    """
    fake_home = tmp_path / "fakehome"
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text("project_name: Project\n", encoding="utf-8")

    global_roots = (
        fake_home / ".claude",
        fake_home / ".codex",
        fake_home / ".gemini",
        fake_home / "Applications",
    )
    for root in global_roots:
        root.mkdir(parents=True)

    manifest_path = tmp_path / "state" / "projects.yaml"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(init_flow, "ensure_git_repo", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_hooks_path", lambda _p: None)
    monkeypatch.setattr(init_flow, "setup_git_filters", lambda _p: None)
    monkeypatch.setattr(init_flow, "update_gitattributes", lambda _p: None)
    monkeypatch.setattr(init_flow, "ensure_precommit_safety_guards", lambda _p: None)
    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _p: None)
    monkeypatch.setattr(init_flow, "_prompt_release_channel", lambda _p: None)
    monkeypatch.setattr(init_flow, "seed_event_domains", lambda _p: None)
    monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

    init_flow.init_project(project_root)

    leaked_files = {
        root.relative_to(fake_home).as_posix(): [
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        ]
        for root in global_roots
    }
    assert all(not files for files in leaked_files.values()), (
        f"init_project wrote files into machine-global roots: {leaked_files}"
    )
