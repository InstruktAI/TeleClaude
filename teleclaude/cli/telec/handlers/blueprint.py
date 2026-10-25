"""Handler for the ``telec repo blueprint`` command."""

from __future__ import annotations

from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import REPO_BLUEPRINT_AFFECTED
from teleclaude.core.blueprint.affected import AffectedResult, compute_affected, load_graph
from teleclaude.core.blueprint.query import BlueprintQueryState, query_current_blueprint
from teleclaude.core.integration.post_commit_maintenance import ON_DEMAND_MAINTENANCE_COMMAND
from teleclaude.project_root import resolve_invocation_roots

__all__ = ["handle_code_blueprint"]

_BLUEPRINT_USAGE = "Usage: telec repo blueprint affected <changed-files>"
_AFFECTED_USAGE = "Usage: telec repo blueprint affected <changed-files>"
_FALLBACK_PREFIX = "blueprint unavailable — fall back to manual exploration"
_RECOVERY_LINE = "Recover with: {reference}"
_UNAVAILABLE_RESULT_TEMPLATE = "{prefix}: {reason}"


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


def _handle_blueprint_affected(args: list[str]) -> None:
    parsed = parse_command_args(REPO_BLUEPRINT_AFFECTED, args)
    changed_files = [a for a in parsed.positionals if a]
    if not changed_files:
        print("At least one changed file is required.")
        print(_AFFECTED_USAGE)
        raise SystemExit(1)

    state_root = resolve_invocation_roots().require_project_root()
    query = query_current_blueprint(state_root)
    if query.state is not BlueprintQueryState.FRESH or query.generation is None:
        print(_UNAVAILABLE_RESULT_TEMPLATE.format(prefix=_FALLBACK_PREFIX, reason=query.reason))
        if query.recovery_reference:
            print(_RECOVERY_LINE.format(reference=query.recovery_reference))
        return

    graph = load_graph(query.generation.graph)
    if graph is None:
        print(f"{_FALLBACK_PREFIX}: blueprint graph could not be read")
        print(_RECOVERY_LINE.format(reference=ON_DEMAND_MAINTENANCE_COMMAND))
        return

    result = compute_affected(graph, changed_files, repo_root=state_root)
    print(_format_result(result, changed_count=len(changed_files)))
