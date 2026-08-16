"""Handler for the ``telec code blueprint`` command."""

from __future__ import annotations

from teleclaude.core.blueprint import (
    compute_affected,
    dispatch_refresh,
    evaluate_freshness,
    graph_path,
    load_graph,
    manifest_path,
    read_manifest,
)
from teleclaude.core.blueprint.affected import AffectedResult
from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.project_root import resolve_invocation_project_root

__all__ = ["handle_code_blueprint"]

_BLUEPRINT_USAGE = "Usage: telec code blueprint affected <changed-files>"
_AFFECTED_USAGE = "Usage: telec code blueprint affected <changed-files>"
_FALLBACK_PREFIX = "blueprint stale/missing — fall back to manual exploration"


def handle_code_blueprint(args: list[str]) -> None:
    """Handle ``telec code blueprint`` commands."""
    if not args or args[0] in ("-h", "--help"):
        print(_BLUEPRINT_USAGE)
        return
    if args[0] != "affected":
        print(f"Unknown blueprint subcommand: {args[0]}")
        print(_BLUEPRINT_USAGE)
        raise SystemExit(1)
    _handle_blueprint_affected(args[1:])


def _resolve_main_sha(state_root: str) -> str | None:
    # Resolve origin/main, the ref class the integrator stamps the Blueprint
    # baseline_sha from (see project/spec/codebase-blueprint). Comparing against
    # local main instead would report a current Blueprint as stale whenever local
    # main is ahead — the steady state, since doc-only commits land on local main
    # but are not pushed synchronously. When origin/main cannot be resolved (fresh
    # clone before fetch, or no remote), return None so the caller surfaces the
    # manual-exploration fallback and preserves the agent workflow rather than
    # crashing.
    try:
        return Repo(state_root).commit("origin/main").hexsha
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, BadName, ValueError):
        return None


def _format_result(result: AffectedResult, *, changed_count: int) -> str:
    lines: list[str] = []
    if result.dependents:
        lines.append(f"Blast radius — {len(result.dependents)} dependent(s) of {changed_count} changed file(s):")
        for dep in result.dependents:
            location = f"{dep.source_file}:{dep.line}" if dep.line is not None else dep.source_file
            lines.append(f"  {location}  {dep.label}")
    else:
        lines.append(f"Blast radius — no dependents found in the blueprint for {changed_count} changed file(s).")
    if result.unmatched_files:
        lines.append("")
        lines.append("Files with no symbols in the blueprint (read these manually):")
        for unmatched in result.unmatched_files:
            lines.append(f"  {unmatched}")
    return "\n".join(lines)


def _handle_blueprint_affected(args: list[str]) -> None:
    if "-h" in args or "--help" in args:
        print(_AFFECTED_USAGE)
        return
    unknown = [a for a in args if a.startswith("-")]
    if unknown:
        print(f"Unknown option: {unknown[0]}")
        print(_AFFECTED_USAGE)
        raise SystemExit(1)
    changed_files = [a for a in args if a]
    if not changed_files:
        print("At least one changed file is required.")
        print(_AFFECTED_USAGE)
        raise SystemExit(1)

    state_root = resolve_invocation_project_root()
    manifest = read_manifest(manifest_path(state_root))
    main_sha = _resolve_main_sha(str(state_root))
    freshness = evaluate_freshness(manifest, current_main_sha=main_sha)
    if not freshness.is_fresh:
        # An unresolved origin/main (None) flows through evaluate_freshness as
        # not-fresh: surface the manual-exploration fallback so the agent
        # workflow continues rather than crashing on a missing remote-tracking ref.
        # A resolvable-but-stale baseline dispatches its own detached refresh so
        # the next invocation converges — see project/spec/codebase-blueprint#UC-BP1.
        dispatch_refresh(state_root, main_sha=main_sha)
        print(f"{_FALLBACK_PREFIX}: {freshness.reason}")
        return

    graph = load_graph(graph_path(state_root))
    if graph is None:
        print(f"{_FALLBACK_PREFIX}: blueprint graph could not be read")
        return

    result = compute_affected(graph, changed_files, repo_root=state_root)
    print(_format_result(result, changed_count=len(changed_files)))
