"""Handler for the ``telec repo blueprint`` command."""

from __future__ import annotations

from pathlib import Path

from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import REPO_BLUEPRINT_AFFECTED
from teleclaude.core.blueprint.affected import AffectedResult, compute_affected, load_graph, normalize_changed
from teleclaude.core.blueprint.query import BlueprintQueryResult, BlueprintQueryState, query_current_blueprint
from teleclaude.core.integration.post_commit_maintenance import ON_DEMAND_MAINTENANCE_COMMAND
from teleclaude.project_root import resolve_invocation_roots

__all__ = ["handle_code_blueprint"]

_BLUEPRINT_USAGE = "Usage: telec repo blueprint affected <changed-files>"
_AFFECTED_USAGE = "Usage: telec repo blueprint affected <changed-files>"
_FALLBACK_PREFIX = "blueprint unavailable — fall back to manual exploration"
_RECOVERY_LINE = "Recover with: {reference}"
_UNAVAILABLE_RESULT_TEMPLATE = "{prefix}: {reason}"
_SHORT_REVISION_LENGTH = 12
_MAINTENANCE_UNOBSERVED = "not observed"


def handle_code_blueprint(args: list[str]) -> None:
    """Handle ``telec repo blueprint`` commands."""
    if not args or args[0] in ("-h", "--help"):
        print(_BLUEPRINT_USAGE)
        return
    if args[0] != "affected":
        print(f"Unknown blueprint subcommand: {args[0]}")
        print(_BLUEPRINT_USAGE)
        raise SystemExit(1)
    _handle_blueprint_affected(args[1:])


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


def _format_header(query: BlueprintQueryResult, *, asking: Path, asked: set[str]) -> str:
    """The facts that locate the answer: the generation, the baseline, maintenance, and the asking checkout's difference."""
    manifest = query.manifest
    if manifest is None:
        return ""
    revision = manifest.baseline_sha
    lines = [f"Blueprint generation: revision {revision[:_SHORT_REVISION_LENGTH]}, generated {manifest.generated_at}"]
    if query.baseline is not None:
        lines.append(
            f"Maintenance baseline: {query.baseline.reference} at {query.baseline.revision[:_SHORT_REVISION_LENGTH]}"
        )
    else:
        lines.append(f"Maintenance baseline: could not be resolved ({query.baseline_error})")
    state = query.maintenance_state.value if query.maintenance_state is not None else _MAINTENANCE_UNOBSERVED
    lines.append(f"Blueprint maintenance: {state}")
    if query.recovery_reference and query.maintenance_state is not None:
        lines.append(_RECOVERY_LINE.format(reference=query.recovery_reference))
    head = query.asking_head[:_SHORT_REVISION_LENGTH] if query.asking_head else _MAINTENANCE_UNOBSERVED
    lines.append(f"Asking checkout: {asking} at HEAD {head}")
    if query.difference_error is not None:
        lines.append(
            f"The difference between the asking checkout and the generation could not be computed: {query.difference_error}"
        )
    elif not query.differing_files:
        lines.append("The asking checkout matches the generation revision in every file.")
    else:
        lines.append(
            f"The asking checkout differs from the generation revision in {len(query.differing_files)} file(s) "
            "(* = asked about):"
        )
        lines.extend(f"  {'*' if path in asked else ' '} {path}" for path in query.differing_files)
        lines.append(f"Inspect it with: git -C {asking} diff {revision}  (untracked files are listed above only)")
    return "\n".join(lines)


def _handle_blueprint_affected(args: list[str]) -> None:
    parsed = parse_command_args(REPO_BLUEPRINT_AFFECTED, args)
    changed_files = [a for a in parsed.positionals if a]
    if not changed_files:
        print("At least one changed file is required.")
        print(_AFFECTED_USAGE)
        raise SystemExit(1)

    roots = resolve_invocation_roots()
    state_root = roots.require_project_root()
    asking = roots.repository_root
    query = query_current_blueprint(state_root, asking)
    if query.state is not BlueprintQueryState.ANSWERED or query.generation is None:
        print(_UNAVAILABLE_RESULT_TEMPLATE.format(prefix=_FALLBACK_PREFIX, reason=query.reason))
        if query.recovery_reference:
            print(_RECOVERY_LINE.format(reference=query.recovery_reference))
        return

    graph = load_graph(query.generation.graph)
    if graph is None:
        print(f"{_FALLBACK_PREFIX}: blueprint graph could not be read")
        print(_RECOVERY_LINE.format(reference=ON_DEMAND_MAINTENANCE_COMMAND))
        return

    repo_roots = (asking, state_root)
    asked = {normalize_changed(path, repo_roots) for path in changed_files}
    result = compute_affected(graph, changed_files, repo_roots=repo_roots)
    print(_format_header(query, asking=asking, asked=asked))
    print(_format_result(result, changed_count=len(changed_files)))
