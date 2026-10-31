"""Integrator-owned checkpoint judgment, discharge, and force-fire behavior."""

import re
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.constants import LOG_CHECK_ACTION_ID, CheckpointAction, CheckpointModel, JudgmentOwner
from teleclaude.core.roles import RoleName
from teleclaude.hooks.checkpoint._directives import _ESCAPE_HATCH, _RESPONSE_POLICY, _surface_run
from teleclaude.hooks.checkpoint._evidence import (
    _command_has_evidence,
    _iter_shell_command_records,
    _segment_matches_evidence,
)
from teleclaude.hooks.checkpoint._git import _split_shell_segments
from teleclaude.hooks.integrator_judgment_marker import (
    discharge_integrator_judgment,
    read_integrator_judgment_marker,
)
from teleclaude.shell_path_parser import executable_command_tokens
from teleclaude.utils.transcript import TurnTimeline

__all__ = ["_defers_to_integrator", "_integrator_judgment_checkpoint"]

logger = get_logger("teleclaude.hooks.checkpoint")  # Preserve the package's record identity.

_INTEGRATOR_MAINTENANCE_ACTION_LINE = "{index}. {action}"
_INTEGRATOR_MAINTENANCE_ACTIONS_LABEL = "Outstanding actions: {actions}"
_INTEGRATOR_LOG_JUDGMENT_TITLE = "Integrator post-activation log judgment"
_INTEGRATOR_LOG_JUDGMENT_REQUIRED_ACTIONS = (
    "Required actions (complete before direct-main publication or next integration):"
)
_INTEGRATOR_MAIN_PUBLICATION_ACTION = (
    "{index}. Judge the logs against the activated changes. If they show a material failure, "
    "leave canonical local main unpushed, recover or fix forward, and repeat the log check. "
    "If the change is sound and local main is ahead of origin/main, run "
    "`git push origin main:main` from the canonical project root and verify origin/main "
    "contains the committed head. The committer owns review; do not inspect or wait for other sessions' review "
    "verdicts. Unrelated uncommitted paths are not part of the push and do not block it. "
    "If main is already synchronized, no push is owed."
)
_INTEGRATOR_ROLE = RoleName.INTEGRATOR.value
_INTEGRATOR_JUDGMENT_NOT_READY_EVENT = "integrator_judgment_not_ready"
_INTEGRATOR_JUDGMENT_FORCE_FIRE_EVENT = "Checkpoint payload computed (integrator maintenance force-fire)"
_INTEGRATOR_LOG_JUDGMENT_MODE = "integrator_log_judgment"

_SINCE_FLAG = "--since"
_WINDOW_PATTERN = re.compile(r"(\d+)([smhd])")
_WINDOW_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_INTEGRATOR_WINDOW_MARGIN_MINUTES = 2
_MINUTE_SECONDS = 60
_ROUNDING_SECONDS = 59
_WINDOW_MINUTES_SUFFIX = "m"


def _has_post_ready_log_check_evidence(
    timeline: TurnTimeline,
    evidence_markers: tuple[str, ...],
    earliest_activated_at: str,
    ready_at: str,
) -> bool:
    """Require a post-readiness log command whose since-window covers activation."""
    earliest = datetime.fromisoformat(earliest_activated_at)
    ready = datetime.fromisoformat(ready_at)
    for _index, record, command in _iter_shell_command_records(timeline):
        if record.had_error or not record.result_observed or record.timestamp is None:
            continue
        call_time = record.timestamp
        if call_time.tzinfo is None:
            call_time = call_time.replace(tzinfo=UTC)
        if call_time <= ready or not _command_has_evidence(command, list(evidence_markers)):
            continue
        since_seconds = _log_since_seconds(command, evidence_markers)
        if since_seconds is not None and since_seconds >= (call_time - earliest).total_seconds():
            return True
    return False


def _log_since_seconds(command: str, evidence_markers: tuple[str, ...]) -> int | None:
    """Read the documented --since duration from the matching command segment."""
    for segment in _split_shell_segments(command):
        if not any(_segment_matches_evidence(segment, marker) for marker in evidence_markers):
            continue
        tokens = executable_command_tokens(segment)
        if _SINCE_FLAG not in tokens:
            continue
        flag_index = tokens.index(_SINCE_FLAG)
        if flag_index + 1 >= len(tokens):
            continue
        match = _WINDOW_PATTERN.fullmatch(tokens[flag_index + 1])
        if match is None:
            continue
        return int(match.group(1)) * _WINDOW_UNIT_SECONDS[match.group(2)]
    return None


def _integrator_judgment_log_window(earliest_activated_at: str, now: datetime) -> str:
    """Build a rounded-up activation window with margin for the command to run."""
    earliest = datetime.fromisoformat(earliest_activated_at)
    elapsed = max(0, int(((now - earliest).total_seconds() + _ROUNDING_SECONDS) // _MINUTE_SECONDS))
    return f"{elapsed + _INTEGRATOR_WINDOW_MARGIN_MINUTES}{_WINDOW_MINUTES_SUFFIX}"


def _defers_to_integrator(action: CheckpointAction, role: str | None) -> bool:
    """Return whether an integrator-owned action belongs to another session."""
    return action.judged_by is JudgmentOwner.INTEGRATOR and role != _INTEGRATOR_ROLE


def _build_integrator_log_judgment_checkpoint(
    action_ids: list[str],
    model: CheckpointModel,
    window: str,
) -> str | None:
    """Build a checkpoint message from outstanding post-activation log actions.

    Surfaces only main-only judgment actions recorded by integration. The prose
    also directs publication after judgment; that instruction is not another
    modeled checkpoint action.
    """
    judgment_actions = [
        model.actions[action_id]
        for action_id in action_ids
        if action_id in model.actions and model.actions[action_id].main_only
    ]
    if not judgment_actions:
        return None

    category_names = [action.id for action in sorted(judgment_actions, key=lambda a: (a.precedence, a.id))]
    lines: list[str] = [
        _INTEGRATOR_LOG_JUDGMENT_TITLE,
        "",
        _INTEGRATOR_MAINTENANCE_ACTIONS_LABEL.format(actions=", ".join(category_names)),
        "",
        _INTEGRATOR_LOG_JUDGMENT_REQUIRED_ACTIONS,
    ]
    for i, action in enumerate(sorted(judgment_actions, key=lambda a: (a.precedence, a.id)), 1):
        lines.append(
            _INTEGRATOR_MAINTENANCE_ACTION_LINE.format(
                index=i,
                action=_surface_run(action, window),
            )
        )
    if LOG_CHECK_ACTION_ID in category_names:
        lines.append(_INTEGRATOR_MAIN_PUBLICATION_ACTION.format(index=len(judgment_actions) + 1))
    lines.extend(
        [
            "",
            _RESPONSE_POLICY,
            "",
            _ESCAPE_HATCH,
        ]
    )
    return "\n".join(lines)


def _integrator_judgment_checkpoint(
    *,
    role: str | None,
    project_path: str,
    timeline: TurnTimeline,
    model: CheckpointModel,
    session_id: str,
    receiver_ingress_id: str,
) -> str | None:
    """Discharge a ready marker or compose the integrator's force-fire checkpoint."""
    if role != _INTEGRATOR_ROLE:
        return None

    marker = read_integrator_judgment_marker(project_path)
    if marker is not None and marker.ready_at is None:
        logger.info(
            _INTEGRATOR_JUDGMENT_NOT_READY_EVENT,
            activation_ids=[activation.after_sha for activation in marker.activations],
        )
    elif marker is not None and marker.ready_at is not None:
        action_ids = [
            action_id
            for action_id in marker.action_ids
            if action_id == LOG_CHECK_ACTION_ID and action_id in model.actions
        ]
        if action_ids:
            action = model.actions[LOG_CHECK_ACTION_ID]
            earliest_activation = min(
                marker.activations,
                key=lambda activation: activation.activated_at,
            ).activated_at
            if _has_post_ready_log_check_evidence(
                timeline,
                action.effective_evidence(),
                earliest_activation,
                marker.ready_at,
            ):
                discharge_integrator_judgment(project_path, marker)
            else:
                window = _integrator_judgment_log_window(earliest_activation, datetime.now(UTC))
                log_judgment_message = _build_integrator_log_judgment_checkpoint(
                    action_ids,
                    model,
                    window,
                )
                if log_judgment_message:
                    logger.info(
                        _INTEGRATOR_JUDGMENT_FORCE_FIRE_EVENT,
                        receiver_ingress_id=receiver_ingress_id,
                        session_id=session_id,
                        project_path=project_path,
                        mode=_INTEGRATOR_LOG_JUDGMENT_MODE,
                        actions=len(action_ids),
                        message_len=len(log_judgment_message),
                    )
                    return log_judgment_message
    return None
