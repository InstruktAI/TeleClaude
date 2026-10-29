"""Handler for ``telec todo stamp``, split out of todo.py to respect module size."""

from __future__ import annotations

import json as _json
from typing import TypedDict

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import project_reference
from teleclaude.cli.telec.handlers._arg_parsing import ParsedArgs, parse_command_args
from teleclaude.cli.telec.surface import TODO_STAMP
from teleclaude.cli.telec.surface_types import Flag
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.types.todos import TaskStamp

__all__ = ["_handle_todo_stamp"]
_MISSING_STAMP_FLAG_MESSAGE = (
    "Missing stamp flag (--verdict, --prd-approved, --architecture-skipped, "
    "--task-approved, --drift-reviewed, --build-complete, "
    "--finalize-ready, --deferrals-processed, --design-spec-confirmed, "
    "--art-approved, --visuals-approved, --kickback, --task-firing-started, --task-outcome, "
    "--diagnosis-settled, --diagnosis-unresolved)"
)


class _TodoStampBody(TypedDict):
    slug: str
    stamp_type: str
    value: str
    phase: str | None
    cwd: str


def _handle_todo_stamp(args: list[str]) -> None:
    """Handle telec todo stamp."""
    parsed = parse_command_args(TODO_STAMP, args)
    if parsed.has(F.FLAG_STAMP_BUILD_STARTED):
        print("--build-started is machine-owned; run telec todo work <slug> to enter build.")
        raise SystemExit(1)

    slug, stamp_type, value, phase = _parse_todo_stamp_args(parsed)

    if not slug:
        print("Usage: telec todo stamp <slug> --verdict approve --phase <phase>")
        raise SystemExit(1)
    if not stamp_type:
        print(_MISSING_STAMP_FLAG_MESSAGE)
        raise SystemExit(1)
    if stamp_type == "verdict" and not phase:
        print("--verdict requires --phase <phase>")
        raise SystemExit(1)
    if stamp_type == "kickback" and not value:
        print("--kickback requires --reason <reason>")
        raise SystemExit(1)
    if stamp_type == "diagnosis_unresolved" and not value:
        print("--diagnosis-unresolved requires --reason <reason>")
        raise SystemExit(1)

    body: _TodoStampBody = {
        "slug": slug,
        "stamp_type": stamp_type,
        "value": value or "",
        "phase": phase,
        "cwd": project_reference(),
    }
    response = tool_api_call("POST", "/todos/stamp", json_body=body)
    if isinstance(response, dict) and response.get("status") == "ok":
        if stamp_type == "build_complete":
            print(
                f"Recorded build-complete claim for {slug}; build gates run on the next telec todo work {slug} dispatch."
            )
            return
        label = f"{stamp_type}={value}" if value else stamp_type
        if phase:
            label = f"{label} phase={phase}"
        print(f"Stamped {label} for {slug}")
        return
    print_json(response)


def _parse_todo_stamp_args(parsed: ParsedArgs) -> tuple[str | None, str | None, str | None, str | None]:
    """Derive (slug, stamp_type, value, phase) from a parsed ``telec todo stamp`` invocation."""
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Only one slug is allowed: unexpected {positionals[1]!r}")
        raise SystemExit(1)
    slug = positionals[0] if positionals else None

    stamp_type: str | None = None
    value: str | None = None
    phase = parsed.value(F.FLAG_STAMP_PHASE)

    if parsed.has(F.FLAG_STAMP_VERDICT):
        stamp_type = "verdict"
        value = parsed.value(F.FLAG_STAMP_VERDICT)
    for flag, mapped_type in _STAMP_BOOLEAN_FLAGS.items():
        if parsed.has(flag):
            stamp_type = mapped_type
            value = "true"
    for flag, mapped_type in _STAMP_REASON_FLAGS.items():
        if parsed.has(flag):
            stamp_type = mapped_type
            value = parsed.value(flag)
    if parsed.has(F.FLAG_STAMP_DRIFT_REVIEWED):
        drift_values = parsed.values(F.FLAG_STAMP_DRIFT_REVIEWED)
        if len(drift_values) != 3:
            print(
                f"--drift-reviewed requires exactly 3 values: <artifact> <verdict> <reason> (got {len(drift_values)})"
            )
            raise SystemExit(1)
        stamp_type = "drift_reviewed"
        value = _json.dumps({"artifact": drift_values[0], "verdict": drift_values[1], "reason": drift_values[2]})
    if parsed.has(F.FLAG_STAMP_FINALIZE_READY):
        stamp_type = "finalize_ready"
        value = ""
    if parsed.has(F.FLAG_STAMP_KICKBACK):
        stamp_type = "kickback"
    if parsed.has(F.FLAG_STAMP_DIAGNOSIS_UNRESOLVED):
        stamp_type = "diagnosis_unresolved"
    if parsed.has(F.FLAG_STAMP_TASK_FIRING_STARTED):
        stamp_type = TaskStamp.FIRING_STARTED
        value = ""
    if parsed.has(F.FLAG_STAMP_TASK_OUTCOME):
        stamp_type = "task_outcome"
        phase = parsed.value(F.FLAG_STAMP_TASK_OUTCOME)
    reason_value = parsed.value(F.FLAG_STAMP_REASON)
    if reason_value is not None:
        value = reason_value

    return slug, stamp_type, value, phase


_STAMP_BOOLEAN_FLAGS: dict[Flag, str] = {
    F.FLAG_STAMP_PRD_APPROVED: "prd_approved",
    F.FLAG_STAMP_TASK_APPROVED: "task_approved",
    F.FLAG_STAMP_DIAGNOSIS_SETTLED: "diagnosis_settled",
    F.FLAG_STAMP_REQUIREMENTS_READY: "requirements_ready",
    F.FLAG_STAMP_PLAN_READY: "plan_ready",
    F.FLAG_STAMP_DEFERRALS_PROCESSED: "deferrals_processed",
    F.FLAG_STAMP_DESIGN_SPEC_CONFIRMED: "creative_design_spec_confirmed",
    F.FLAG_STAMP_ART_APPROVED: "creative_art_approved",
    F.FLAG_STAMP_VISUALS_APPROVED: "creative_visuals_approved",
    F.FLAG_STAMP_BUILD_COMPLETE: "build_complete",
}

_STAMP_REASON_FLAGS: dict[Flag, str] = {
    F.FLAG_STAMP_ARCHITECTURE_SKIPPED: "architecture_skipped",
}
