"""Functional coverage for lint delegation path safety."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.cli.telec.handlers import quality
from teleclaude.quality.scope import RustScopeKind, resolve_rust_scope, validate_scoped_paths

_SPEC = "general/spec/tools/telec-cli"
_FILES_FROM_PREFIX = "FILES_FROM="
_PROJECT_ROOT_SENTINEL = "<project-root>"


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "path-safety")
def test_validate_scoped_paths_rejects_paths_outside_the_project_boundary(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    sibling_root = tmp_path / "project-sibling"
    project_root.mkdir(exist_ok=True)
    sibling_root.mkdir()
    (project_root / "safe.py").write_text("x = 1\n", encoding="utf-8")
    (sibling_root / "escape.py").write_text("x = 1\n", encoding="utf-8")
    (project_root / "-raw.py").write_text("x = 1\n", encoding="utf-8")
    (project_root / "-normalized.py").write_text("x = 1\n", encoding="utf-8")

    paths = [
        "safe.py",
        "../project-sibling/escape.py",
        str(sibling_root / "escape.py"),
        "-raw.py",
        "./-normalized.py",
    ]

    assert {"safe_paths": validate_scoped_paths(paths, project_root)} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_lint_passes_adversarial_paths_through_nul_files_from(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_popen(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        files_from = next(part.removeprefix(_FILES_FROM_PREFIX) for part in cmd if part.startswith(_FILES_FROM_PREFIX))
        records.append(
            {
                "cmd": cmd[:2],
                "cwd": _PROJECT_ROOT_SENTINEL,
                "files": Path(files_from).read_bytes().split(b"\0"),
            }
        )
        return SimpleNamespace(pid=999999, wait=lambda: 0)

    class FakeLintRunner:
        def __init__(self, project_root: Path) -> None:
            self.project_root = project_root

        def run(self, *, files: list[str] | None = None, run_all: bool = False) -> None:
            records.append(
                {
                    "guardrails_project_root": _PROJECT_ROOT_SENTINEL,
                    "guardrails_project_matches": self.project_root == tmp_path,
                    "guardrails_files": files,
                    "guardrails_run_all": run_all,
                }
            )

    monkeypatch.setattr(quality.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(quality, "LintRunner", FakeLintRunner)

    quality.handle_lint(["a b.py", "c;d.py"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_lint_propagates_make_failure_after_guardrails_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_popen(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        files_from = next(part.removeprefix(_FILES_FROM_PREFIX) for part in cmd if part.startswith(_FILES_FROM_PREFIX))
        records.append(("make", cmd[:2], _PROJECT_ROOT_SENTINEL, Path(files_from).read_bytes().split(b"\0")))
        return SimpleNamespace(pid=999999, wait=lambda: 7)

    class FakeLintRunner:
        def __init__(self, project_root: Path) -> None:
            self.project_root = project_root

        def run(self, *, files: list[str] | None = None, run_all: bool = False) -> None:
            records.append(("guardrails", _PROJECT_ROOT_SENTINEL, self.project_root == tmp_path, files, run_all))

    monkeypatch.setattr(quality.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(quality, "LintRunner", FakeLintRunner)

    with pytest.raises(SystemExit) as exc:
        quality.handle_lint(["teleclaude/core.py"])

    assert exc.value.code == 7
    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_full_run_skips_format_and_stays_check_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records: list[object] = []

    monkeypatch.setattr(quality, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(quality, "resolve_git_root", lambda _cwd: tmp_path)

    def fake_popen(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        records.append({"cmd": cmd[:2]})
        return SimpleNamespace(pid=999999, wait=lambda: 0)

    class FakeLintRunner:
        def __init__(self, project_root: Path) -> None:
            self.project_root = project_root

        def run(self, *, files: list[str] | None = None, run_all: bool = False) -> None:
            records.append({"guardrails_files": files, "guardrails_run_all": run_all})

    monkeypatch.setattr(quality.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(quality, "LintRunner", FakeLintRunner)

    quality.handle_lint(["--all"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "rust-scope")
def test_rust_scope_uses_package_when_changed_path_belongs_to_one_crate(tmp_path: Path, snapshot: object) -> None:
    package_manifest = tmp_path / "crates" / "telec-core" / "Cargo.toml"
    package_manifest.parent.mkdir(parents=True)
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8")
    package_manifest.write_text('[package]\nname = "telec-core"\nversion = "0.1.0"\n', encoding="utf-8")
    (package_manifest.parent / "src").mkdir()
    (package_manifest.parent / "src" / "lib.rs").write_text("", encoding="utf-8")

    scope = resolve_rust_scope(tmp_path, ["crates/telec-core/src/lib.rs"])

    assert {
        "kind": scope.kind,
        "package": scope.package,
        "rust_owned_paths": scope.rust_owned_paths,
        "workspace_root": scope.workspace_root == tmp_path,
    } == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "rust-scope")
def test_rust_scope_uses_workspace_when_root_cargo_manifest_changes(tmp_path: Path, snapshot: object) -> None:
    (tmp_path / "Cargo.toml").write_text("[workspace]\nmembers = []\n", encoding="utf-8")

    scope = resolve_rust_scope(tmp_path, ["Cargo.toml"])

    assert {
        "kind": scope.kind,
        "is_workspace": scope.kind is RustScopeKind.WORKSPACE,
        "package": scope.package,
        "rust_owned_paths": scope.rust_owned_paths,
        "workspace_root": scope.workspace_root == tmp_path,
    } == snapshot
