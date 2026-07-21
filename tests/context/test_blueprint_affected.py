"""Functional tests for the codebase Blueprint blast-radius helper and command."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.cli.telec.handlers.context import _FALLBACK_PREFIX, _handle_blueprint_affected, _resolve_main_sha
from teleclaude.core.blueprint import refresh as blueprint_refresh
from teleclaude.core.blueprint._paths import GRAPH_FILENAME, graph_path, manifest_path, refresh_lock_path
from teleclaude.core.blueprint.manifest import read_manifest
from teleclaude.git import Repo

pytestmark = pytest.mark.functional

_BASELINE = "mainbaselinesha0001"

# Leading indent on each dependent output line — used in _dependent_labels_via_command.
_DEPENDENT_LINE_INDENT = "  "

# Prefix of the blast-radius header line emitted by _format_result when dependents are found.
_BLAST_RADIUS_PREFIX = "Blast radius"


# guard: loose-dict-func - fixture mirroring the untrusted graph.json contract under test
def _graph() -> dict[str, object]:
    """A dependency chain app.main -> top.run -> mid.use_base -> core.base, plus noise.

    Edges point dependent -> dependency, so the reverse traversal from a change in
    core.py must reach mid, top and app (a depth-3 hop that proves the traversal is
    unbounded, beyond graphify's default depth-2 cap).
    """
    return {
        "directed": True,
        "nodes": [
            {"id": "core", "source_file": "core.py", "source_location": "L1", "label": "core.py"},
            {"id": "core_base", "source_file": "core.py", "source_location": "L2", "label": "base()"},
            {"id": "mid_use", "source_file": "mid.py", "source_location": "L5", "label": "use_base()"},
            {"id": "top_run", "source_file": "top.py", "source_location": "L9", "label": "run()"},
            {"id": "app_main", "source_file": "app.py", "source_location": "L3", "label": "main()"},
            {"id": "lonely", "source_file": "unrelated.py", "source_location": "L1", "label": "lonely()"},
            {"id": "helper_h", "source_file": "helper.py", "source_location": "L1", "label": "h()"},
            {"id": "consumer_c", "source_file": "consumer.py", "source_location": "L4", "label": "c()"},
            # Full-repo-relative-path node ids (graphify 0.9.0's format), proving
            # compute_affected keys purely on source_file/relation and never on id shape.
            {
                "id": "handlers/dispatch_target.py:on_event",
                "source_file": "handlers/dispatch_target.py",
                "source_location": "L1",
                "label": "on_event()",
            },
            {
                "id": "services/dispatcher.py:route_via_table",
                "source_file": "services/dispatcher.py",
                "source_location": "L1",
                "label": "route_via_table()",
            },
        ],
        "links": [
            {"relation": "contains", "source": "core", "target": "core_base"},
            {"relation": "calls", "source": "mid_use", "target": "core_base"},
            {"relation": "calls", "source": "top_run", "target": "mid_use"},
            {"relation": "calls", "source": "app_main", "target": "top_run"},
            {"relation": "imports", "source": "consumer_c", "target": "helper_h"},
            # graphify 0.9.4's indirect-call relation: a dispatch table entry pointing
            # at its target without a direct static call edge.
            {
                "relation": "indirect_call",
                "source": "services/dispatcher.py:route_via_table",
                "target": "handlers/dispatch_target.py:on_event",
            },
        ],
    }


def _dependent_labels_via_command(tmp_path: Path, changed: list[str], capsys: pytest.CaptureFixture[str]) -> set[str]:
    """Run the blueprint affected command and return the set of dependent labels.

    Uses the CLI handler at the command boundary — not the internal compute_affected
    helper — so the full handler path (freshness check, graph load, format, print) is
    exercised.
    """
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, changed, main_sha=_BASELINE)
    out = capsys.readouterr().out
    labels = set()
    for line in out.splitlines():
        if line.startswith(_DEPENDENT_LINE_INDENT):
            # Each dependent line: "  file:line  label" — split on double-space after strip.
            parts = line.strip().split(_DEPENDENT_LINE_INDENT, 1)
            if len(parts) == 2:
                labels.add(parts[1])
    return labels


def test_affected_returns_unbounded_transitive_dependents(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A change in core.py reaches every transitive dependent, including depth-3 app.main."""
    assert _dependent_labels_via_command(tmp_path, ["core.py"], capsys) == {"use_base()", "run()", "main()"}


def test_affected_traverses_only_downstream_dependents(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A change in mid.py reaches its dependents, never its dependencies (core)."""
    assert _dependent_labels_via_command(tmp_path, ["mid.py"], capsys) == {"run()", "main()"}


def test_affected_unions_dependents_across_changed_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two changed files in independent subgraphs contribute one unioned dependent set."""
    assert _dependent_labels_via_command(tmp_path, ["core.py", "helper.py"], capsys) == {
        "use_base()",
        "run()",
        "main()",
        "c()",
    }


def test_affected_excludes_nodes_inside_the_changed_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dependents that live in another changed file are part of the change, not the radius."""
    assert _dependent_labels_via_command(tmp_path, ["core.py", "mid.py"], capsys) == {"run()", "main()"}


def test_affected_traverses_indirect_call_relation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """graphify 0.9.4's indirect-call relation (dispatch tables, callback refs) reaches its
    dependent — proving the whitelist widening in _DEPENDENCY_RELATIONS. Fails against the
    pre-0.9.4 whitelist, which drops this relation at the reverse_adj filter."""
    assert _dependent_labels_via_command(tmp_path, ["handlers/dispatch_target.py"], capsys) == {"route_via_table()"}


def test_affected_reports_files_absent_from_the_graph(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A changed file with no symbols in the graph is surfaced as unmatched."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, ["ghost.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


def _write_blueprint(root: Path, *, baseline_sha: str, status: str = "ok") -> None:
    manifest_path(root).parent.mkdir(parents=True, exist_ok=True)
    graph_path(root).write_text(json.dumps(_graph()))
    manifest_path(root).write_text(
        json.dumps({"baseline_sha": baseline_sha, "generated_at": "2026-06-11T00:00:00+00:00", "status": status})
    )


def _run_command(tmp_path: Path, changed: list[str], *, main_sha: str | None) -> None:
    with (
        patch("teleclaude.cli.telec.handlers.context.resolve_invocation_project_root", return_value=tmp_path),
        patch("teleclaude.cli.telec.handlers.context._resolve_main_sha", return_value=main_sha),
    ):
        _handle_blueprint_affected(changed)


def test_command_prints_blast_radius_when_fresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A fresh Blueprint prints the dependent set with file:line."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, ["core.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


def test_command_falls_back_when_blueprint_is_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A baseline behind current main yields the explicit manual-exploration fallback."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, ["core.py"], main_sha="differentmainsha9999")
    assert capsys.readouterr().out == snapshot


def test_command_falls_back_when_blueprint_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """No manifest at all yields the fallback, never a silent skip."""
    _run_command(tmp_path, ["core.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


def test_command_falls_back_when_blueprint_graph_is_malformed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A malformed graph yields the fallback, never an empty dependent set."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    graph_path(tmp_path).write_text(json.dumps({"nodes": {}, "links": []}))
    _run_command(tmp_path, ["core.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


# --- Real-resolver freshness regression -------------------------------------
#
# The mocked _run_command above patches _resolve_main_sha away, which is exactly
# why the origin/main-vs-local-main bug was invisible. These tests drive the real
# resolver against a git repo with a remote-tracking origin/main, the only way to
# bind the writer/reader ref-class contract.


def _init_repo_with_origin(root: Path) -> tuple[Repo, str]:
    """Init a repo with an origin remote, publish C0 to origin/main, return (repo, C0 sha)."""
    origin = Repo.init(root / "origin.git", bare=True)
    origin.git.symbolic_ref("HEAD", "refs/heads/main")
    work = root / "work"
    repo = Repo.init(work)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Blueprint Test")
    repo.git.config("user.email", "blueprint-test@example.test")
    # resolve_project_root finds .git at `work` itself (its own repo, nested
    # under the outer tmp_path fixture repo) and requires teleclaude.yml there.
    (work / "teleclaude.yml").write_text("business:\n  domains:\n    software-development: docs\n", encoding="utf-8")
    (work / "seed.txt").write_text("c0\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "C0")
    repo.create_remote("origin", str(root / "origin.git"))
    repo.git.push("origin", "main")
    return repo, repo.head.commit.hexsha


def _commit(repo: Repo, root: Path, name: str, message: str) -> str:
    (root / "work" / name).write_text(f"{message}\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", message)
    return repo.head.commit.hexsha


def _run_command_real_resolver(project_root: Path, changed: list[str]) -> None:
    """Run the command with only the project root patched — _resolve_main_sha runs for real."""
    with patch(
        "teleclaude.cli.telec.handlers.context.resolve_invocation_project_root",
        return_value=project_root,
    ):
        _handle_blueprint_affected(changed)


def test_command_is_fresh_when_local_main_is_ahead_of_origin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Local main ahead of origin/main is fresh: freshness is judged against origin/main, not local main.

    This is the regression. The baseline equals origin/main (C0); a local-only commit
    (C1) advances local main past it — the steady state for unpushed doc commits. The
    command must print the blast radius, proving it compares against origin/main (C0).
    """
    repo, c0 = _init_repo_with_origin(tmp_path)
    work = tmp_path / "work"
    _commit(repo, tmp_path, "local.txt", "C1 local-only")
    assert repo.commit("origin/main").hexsha == c0
    assert repo.commit("main").hexsha != c0  # local main is genuinely ahead
    _write_blueprint(work, baseline_sha=c0)
    _run_command_real_resolver(work, ["core.py"])
    out = capsys.readouterr().out
    assert _BLAST_RADIUS_PREFIX in out
    assert _FALLBACK_PREFIX not in out


def test_command_falls_back_when_origin_main_actually_advances(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Origin/main advancing past the baseline is genuine staleness: the fallback still fires."""
    repo, c0 = _init_repo_with_origin(tmp_path)
    work = tmp_path / "work"
    _commit(repo, tmp_path, "next.txt", "C1 published")
    repo.git.push("origin", "main")
    assert repo.commit("origin/main").hexsha != c0
    _write_blueprint(work, baseline_sha=c0)
    _run_command_real_resolver(work, ["core.py"])
    assert _FALLBACK_PREFIX in capsys.readouterr().out


def test_command_falls_back_when_origin_main_is_absent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A repo with no resolvable origin/main resolves to None and falls back, never crashes."""
    work = tmp_path / "work"
    repo = Repo.init(work)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Blueprint Test")
    repo.git.config("user.email", "blueprint-test@example.test")
    (work / "teleclaude.yml").write_text("business:\n  domains:\n    software-development: docs\n", encoding="utf-8")
    (work / "seed.txt").write_text("c0\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "C0")
    assert _resolve_main_sha(str(work)) is None
    _write_blueprint(work, baseline_sha=_BASELINE)
    _run_command_real_resolver(work, ["core.py"])
    assert _FALLBACK_PREFIX in capsys.readouterr().out


# --- UC-BP1: a stale baseline dispatches its own detached refresh ----------
#
# The three tests below exercise `dispatch_refresh`, called from the handler's
# not-fresh branch. Two process boundaries are faked in all three: the detached
# `subprocess.Popen` (replaced with a fake that runs the child entrypoint
# in-process against a patched os.environ, rather than truly spawning) and the
# Graphify subprocess (patched at `generate.subprocess.run`, the existing pattern
# from tests/context/test_blueprint_generate.py). Real Graphify is never exercised:
# its ~77s runtime and machine-dependent output would violate TQ-09.


def _fake_graphify_update(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    root = Path(args[2])
    source_graph = root / "graphify-out" / GRAPH_FILENAME
    source_graph.parent.mkdir(parents=True, exist_ok=True)
    source_graph.write_text(json.dumps(_graph()), encoding="utf-8")
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def _run_child_inline(args: list[str], *, env: dict[str, str], **_kwargs: object) -> None:
    """Fake for `subprocess.Popen`: run the child entrypoint in-process instead of spawning."""
    with patch.dict(os.environ, env, clear=True):
        blueprint_refresh.main()


def test_stale_baseline_dispatches_refresh_that_converges(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-BP1: a stale baseline dispatches a detached refresh; the next call is fresh."""
    repo, c0 = _init_repo_with_origin(tmp_path)
    work = tmp_path / "work"
    _commit(repo, tmp_path, "next.txt", "C1 published")
    repo.git.push("origin", "main")
    c1 = repo.commit("origin/main").hexsha
    _write_blueprint(work, baseline_sha=c0)

    monkeypatch.setattr(blueprint_refresh, "resolve_invocation_cwd", lambda: work)
    monkeypatch.setattr(blueprint_refresh.subprocess, "Popen", _run_child_inline)

    with (
        patch("teleclaude.core.blueprint.generate.subprocess.run", side_effect=_fake_graphify_update),
        patch("teleclaude.cli.telec.handlers.context.resolve_invocation_project_root", return_value=work),
    ):
        _handle_blueprint_affected(["core.py"])
        first_out = capsys.readouterr().out

        manifest_after = read_manifest(manifest_path(work))
        assert manifest_after is not None
        assert manifest_after.baseline_sha == c1

        _handle_blueprint_affected(["core.py"])
        second_out = capsys.readouterr().out

    assert _FALLBACK_PREFIX in first_out
    assert _BLAST_RADIUS_PREFIX in second_out
    assert _FALLBACK_PREFIX not in second_out


def test_refresh_child_noops_when_lock_already_held(tmp_path: Path) -> None:
    """A second refresh child exits without regenerating when the lock is already held."""
    repo, c0 = _init_repo_with_origin(tmp_path)
    work = tmp_path / "work"
    _commit(repo, tmp_path, "next.txt", "C1 published")
    repo.git.push("origin", "main")
    _write_blueprint(work, baseline_sha=c0)

    lock_path = refresh_lock_path(work)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held_fh = lock_path.open("a+")
    fcntl.flock(held_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with (
            patch.dict(os.environ, {"GRAPHIFY_REPO_ROOT": str(work)}, clear=False),
            patch("teleclaude.core.blueprint.generate.subprocess.run") as fake_run,
        ):
            assert blueprint_refresh.main() == 0
        fake_run.assert_not_called()
    finally:
        fcntl.flock(held_fh.fileno(), fcntl.LOCK_UN)
        held_fh.close()

    manifest = read_manifest(manifest_path(work))
    assert manifest is not None
    assert manifest.baseline_sha == c0


def test_worktree_invocation_dispatches_no_refresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale baseline observed from inside a slug worktree dispatches nothing."""
    repo, c0 = _init_repo_with_origin(tmp_path)
    work = tmp_path / "work"
    _commit(repo, tmp_path, "next.txt", "C1 published")
    repo.git.push("origin", "main")
    _write_blueprint(work, baseline_sha=c0)

    worktree_root = work / "trees" / "some-slug"
    repo.git.worktree("add", "-b", "some-slug", str(worktree_root))

    popen_calls: list[list[str]] = []
    monkeypatch.setattr(blueprint_refresh, "resolve_invocation_cwd", lambda: worktree_root)
    monkeypatch.setattr(
        blueprint_refresh.subprocess,
        "Popen",
        lambda args, **_kwargs: popen_calls.append(args),
    )

    with patch(
        "teleclaude.cli.telec.handlers.context.resolve_invocation_project_root",
        return_value=work,
    ):
        _handle_blueprint_affected(["core.py"])

    assert _FALLBACK_PREFIX in capsys.readouterr().out
    assert popen_calls == []
