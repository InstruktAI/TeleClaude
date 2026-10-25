"""Local inspection and recovery for canonical-main maintenance records."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import (
    REPO_MAINTENANCE_DRAIN,
    REPO_MAINTENANCE_RETRY,
    REPO_MAINTENANCE_STATUS,
)
from teleclaude.core.integration._maintenance_records import (
    EventActivation,
    MaintenanceActionRecord,
    MaintenanceRecordState,
    activation_key,
    commit_activation_key,
    event_activation_key,
)
from teleclaude.core.integration.post_commit_maintenance import (
    MaintenanceStatus,
    drain_maintenance,
    maintenance_status,
    replay_command,
    retry_failed_action,
)
from teleclaude.project_root import resolve_invocation_roots

_USAGE = "Usage: telec repo maintenance {status|drain|retry}"
_RETRY_USAGE = "Usage: telec repo maintenance retry (--after-sha <sha> | --event-id <id>) --action <id>"
_NO_ACTION_RECORDS = "No outstanding or failed maintenance action records."
_NO_JUDGMENT_MARKER = "No integrator judgment is pending."
_MISSING_VALUE = "none"
_INVALID_COMMAND = "Unknown maintenance command."
_RETRY_REQUIRES_FAILED = "Retry requires a failed action record; inspect with telec repo maintenance status."
_DRAIN_FAILED = "Maintenance drain is ineligible here or a terminal failure remains; inspect status."
_RETRY_FAILED = "Maintenance action remains failed after retry; inspect telec repo maintenance status."
_RETRY_SUCCEEDED = "Maintenance action retry completed."
_ACTIVATION_LINE = "Activation {after_sha} (queued {queued_at})"
_EVENT_ACTIVATION_LINE = "Event activation {event_type} {event_id} (queued {queued_at})"
_RECORD_LINE = "  {action_id}: {state}; exit_code={exit_code}; finished_at={finished_at}"
_RECORD_RECOVERY_LINE = "  Recover with: {command}"
_MARKER_ACTIVATION_LINE = "  {after_sha} activated_at={activated_at}"
_MARKER_READINESS_LINE = "Integrator judgment ready_at={ready_at}"
_MARKER_RECOVERY_LINE = "  Resume with: telec repo maintenance drain"


class MaintenanceCommand(StrEnum):
    """Closed vocabulary of local maintenance operations."""

    STATUS = "status"
    DRAIN = "drain"
    RETRY = "retry"


def handle_code_maintenance(args: list[str]) -> None:
    """Route the hidden local maintenance inspection and recovery commands."""
    if not args:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2)
    try:
        command = MaintenanceCommand(args[0])
    except ValueError:
        print(_INVALID_COMMAND, file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2) from None
    operands = args[1:]
    if command is MaintenanceCommand.STATUS:
        parsed = parse_command_args(REPO_MAINTENANCE_STATUS, operands)
        if parsed.positionals:
            print(_USAGE, file=sys.stderr)
            raise SystemExit(2)
        _print_status(maintenance_status(_invocation_root()))
        return
    if command is MaintenanceCommand.DRAIN:
        parsed = parse_command_args(REPO_MAINTENANCE_DRAIN, operands)
        if parsed.positionals:
            print(_USAGE, file=sys.stderr)
            raise SystemExit(2)
        if not drain_maintenance(_invocation_root()):
            print(_DRAIN_FAILED, file=sys.stderr)
            raise SystemExit(1)
        return
    _retry(operands)


def _invocation_root() -> Path:
    """Return the actual checkout root so worktrees fail drain eligibility."""
    return resolve_invocation_roots().repository_root


def _retry(args: list[str]) -> None:
    """Validate a failed record, retry it, and report any remaining failure."""
    parsed = parse_command_args(REPO_MAINTENANCE_RETRY, args)
    after_values = parsed.values(F.FLAG_MAINTENANCE_AFTER_SHA)
    event_values = parsed.values(F.FLAG_MAINTENANCE_EVENT_ID)
    action_values = parsed.values(F.FLAG_MAINTENANCE_ACTION)
    if parsed.positionals or len(after_values) + len(event_values) != 1 or len(action_values) != 1:
        print(_RETRY_USAGE, file=sys.stderr)
        raise SystemExit(2)
    root = _invocation_root()
    key = commit_activation_key(after_values[0]) if after_values else event_activation_key(event_values[0])
    action_id = action_values[0]
    status = maintenance_status(root)
    failed_record = next(
        (
            record
            for record in status.records
            if activation_key(record.activation) == key
            and record.action_id == action_id
            and record.state is MaintenanceRecordState.FAILED
        ),
        None,
    )
    if failed_record is None:
        print(_RETRY_REQUIRES_FAILED, file=sys.stderr)
        raise SystemExit(1)
    if not retry_failed_action(root, key, action_id):
        print(_RETRY_FAILED, file=sys.stderr)
        raise SystemExit(1)
    print(_RETRY_SUCCEEDED)


def _print_status(status: MaintenanceStatus) -> None:
    """Print every action record and the checkout-scoped judgment state."""
    if not status.records:
        print(_NO_ACTION_RECORDS)
    for key in sorted({activation_key(record.activation) for record in status.records}):
        activation_records = tuple(record for record in status.records if activation_key(record.activation) == key)
        first_record = activation_records[0]
        print(_activation_line(first_record))
        for record in activation_records:
            _print_record(record)
    marker = status.judgment_marker
    if marker is None:
        print(_NO_JUDGMENT_MARKER)
        return
    ready_at = marker.ready_at or _MISSING_VALUE
    print(_MARKER_READINESS_LINE.format(ready_at=ready_at))
    for activation in marker.activations:
        print(_MARKER_ACTIVATION_LINE.format(after_sha=activation.after_sha, activated_at=activation.activated_at))
    if marker.ready_at is None:
        print(_MARKER_RECOVERY_LINE)


def _activation_line(record: MaintenanceActionRecord) -> str:
    """Name the activation a record belongs to and when it was queued."""
    activation = record.activation
    if isinstance(activation, EventActivation):
        return _EVENT_ACTIVATION_LINE.format(
            event_type=activation.event_type, event_id=activation.event_id, queued_at=record.queued_at
        )
    return _ACTIVATION_LINE.format(after_sha=activation.after_sha, queued_at=record.queued_at)


def _print_record(record: MaintenanceActionRecord) -> None:
    """Print one action state and the exact recovery command for failures."""
    print(
        _RECORD_LINE.format(
            action_id=record.action_id,
            state=record.state.value,
            exit_code=record.exit_code if record.exit_code is not None else _MISSING_VALUE,
            finished_at=record.finished_at or _MISSING_VALUE,
        )
    )
    if record.state is MaintenanceRecordState.FAILED:
        print(_RECORD_RECOVERY_LINE.format(command=replay_command(record.activation, record.action_id)))
