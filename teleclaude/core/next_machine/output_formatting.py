"""Output formatters — plain text responses for the orchestrator AI.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.next_machine._types import REVIEW_DIFF_NOTE
from teleclaude.core.next_machine.prepare_diff_dispatch import DispatchReason, format_dispatch_reason
from teleclaude.paths import COMMANDS_DIR

if TYPE_CHECKING:
    from teleclaude.core.next_machine.git_ops import ArtifactDriftStatus

__all__ = [
    "MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE",
    "ORCHESTRATOR_IDLE_INVARIANT",
    "PENDING_DRIFT_CONTEXT_PREFIX",
    "PREPARE_SLUG_REQUIRED_MESSAGE",
    "REVIEW_DIFF_NOTE",
    "ToolCallRequest",
    "dispatch_or_reuse",
    "format_blocker_resolution",
    "format_command_loader_message",
    "format_error",
    "format_finalize_handoff_complete",
    "format_kickback_terminal",
    "format_orchestration_watch_instruction",
    "format_pending_classes_for_dispatch",
    "format_prepared",
    "format_procedure_load",
    "format_stash_debt",
    "format_tool_call",
    "format_uncommitted_changes",
    "format_work_entry_drift_bounce",
    "format_work_entry_substantive_handoff",
    "format_worker_redispatch",
    "parse_human_in_loop",
]


ORCHESTRATOR_IDLE_INVARIANT = (
    "INVARIANT: Never invoke the next state-machine call (telec todo prepare/work/integrate) "
    "while a worker referenced in this script is still active. "
    "Always wait for the named worker(s) to emit agent_stop first."
)
PENDING_DRIFT_CONTEXT_PREFIX = "PENDING_DRIFT"
PREPARE_SLUG_REQUIRED_MESSAGE = "No slug was provided. `telec todo prepare` requires an explicit active todo slug."
MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE = (
    "No active todo exists for {slug}. The slug may be absent, delivered, removed, or not currently active."
)
_ORCHESTRATION_WATCH_ARM_TEMPLATE = (
    "Arm the durable orchestration-watch reminder with `telec reminders set orchestration-watch "
    "--machine {machine} --slug {slug}`. The prescribed profile owns the 300-second cadence."
)
_ORCHESTRATION_WATCH_REPLACE_TEMPLATE = (
    "Replace the durable orchestration-watch reminder with `telec reminders set orchestration-watch "
    "--machine {machine} --slug {slug}` so its prescribed cadence restarts from this feedback."
)
_MODE_FLAG_TEMPLATE = ' --mode "{mode}"'
_PENDING_DRIFT_STATUS = "pending"
_DRIFT_CLASS_ORDER = {
    "code": 0,
    "upstream-artifact": 1,
    "owned-snippet": 2,
    "upstream-snippet": 3,
    "age": 4,
}


class ToolCallRequest(dict[str, object]):  # guard: loose-dict - dynamic payload
    """Structured request mapping for orchestrator tool-call formatting.

    Fields consumed by format_tool_call:
        command: SlashCommand enum or string (required)
        args: worker arguments (required)
        project: project root path (required)
        subfolder: worktree subfolder relative to project (required)
        post_block: tailored WHEN-WORKER-COMPLETES instructions (optional)
        pre_dispatch: pre-dispatch steps (optional)
        additional_context: extra context for the worker (optional)
        note: trailing note appended to the output (optional)
        recommended_mode: recommended thinking mode (fast|med|slow) for this worker (optional)
    """


def _drift_class_sort_key(name: str) -> tuple[int, str]:
    """Return stable taxonomy order for known drift classes."""
    return (_DRIFT_CLASS_ORDER.get(name, len(_DRIFT_CLASS_ORDER)), name)


def format_pending_classes_for_dispatch(
    drift_result: dict[str, dict[str, ArtifactDriftStatus]],
) -> str:
    """Render pending drift classes for the drift analyzer dispatch context."""
    pending_parts: list[str] = []
    for artifact_name in sorted(drift_result):
        pending_classes = sorted(
            (
                class_name
                for class_name, status in drift_result[artifact_name].items()
                if status == _PENDING_DRIFT_STATUS
            ),
            key=_drift_class_sort_key,
        )
        if pending_classes:
            pending_parts.append(f"{artifact_name}=[{','.join(pending_classes)}]")
    if not pending_parts:
        return ""
    return f"{PENDING_DRIFT_CONTEXT_PREFIX}: {'; '.join(pending_parts)}"


def format_blocker_resolution(
    slug: str,
    instruction: str,
    *,
    blockers: list[str] | None = None,
    context: str = "",
) -> str:
    """Format a verbatim execution script for non-dispatch prepare instructions.

    Used when the prepare state machine reaches a state that requires a
    concrete next action without dispatching a worker — approval gates,
    non-drift blockers, no-active-work, structural-holder, and loop-limit cases.
    """
    parts = ["IMPORTANT: This output is an execution script. Follow it verbatim.", ""]
    parts.append(f"SLUG: {slug or '<none>'}")
    parts.append("")
    if context:
        parts.append(context)
        parts.append("")
    if blockers:
        parts.append("BLOCKERS:")
        for blocker in blockers:
            parts.append(f"- {blocker}")
        parts.append("")
    parts.append("NEXT ACTION:")
    parts.append(instruction)
    return "\n".join(parts)


def _command_text(value: object) -> str:
    """Return the slash-command literal for enum or string inputs."""
    if hasattr(value, "value"):
        return str(value.value)  # pyright: ignore[reportAttributeAccessIssue]  # guarded by hasattr
    return str(value)


def _format_slash_command(value: object) -> str:
    """Return a slash-prefixed command literal."""
    return f"/{_command_text(value).lstrip('/')}"


def _format_pre_dispatch_block(pre_dispatch: str) -> str:
    """Format the optional pre-dispatch block."""
    if not pre_dispatch:
        return ""
    return f"""STEP 0 - BEFORE DISPATCHING:
{pre_dispatch}

"""


def format_send_command(session_id: str, message: str) -> str:
    """Render a shell-safe `telec sessions send` command for emitted scripts.

    Emitted scripts are executed verbatim by orchestrators, so the message is
    quoted as a single shell token; command substitution and quotes inside it
    stay inert.
    """
    return f"telec sessions send {session_id} {shlex.quote(message)}"


def format_orchestration_watch_instruction(*, machine: str, slug: str, restart_cadence: bool) -> str:
    """Render a prescribed orchestration-watch command with concrete owner inputs."""
    template = _ORCHESTRATION_WATCH_REPLACE_TEMPLATE if restart_cadence else _ORCHESTRATION_WATCH_ARM_TEMPLATE
    return template.format(machine=shlex.quote(machine), slug=shlex.quote(slug))


def format_worker_redispatch(
    session_id: str,
    *,
    slug: str,
    machine: str,
    message: str,
    advance_call: str,
) -> str:
    """Format the canonical script for reusing a live worker session."""
    return (
        f"WORKER RE-DISPATCH (reuse): {slug}\n\n"
        f"Execute in order:\n\n"
        f"{format_send_command(session_id, message)}\n\n"
        f"{format_orchestration_watch_instruction(machine=machine, slug=slug, restart_cadence=True)}\n"
        f"When the worker reports idle, call {advance_call}."
    )


def dispatch_or_reuse(
    worker_id: str | None,
    *,
    request: ToolCallRequest,
    slug: str,
    message: str,
    advance_call: str,
) -> str:
    """Reuse a live worker when present, otherwise format a fresh dispatch."""
    if worker_id is not None:
        return format_worker_redispatch(
            worker_id,
            slug=slug,
            machine=_command_text(request["command"]).lstrip("/"),
            message=message,
            advance_call=advance_call,
        )
    return format_tool_call(request)


def _format_additional_context(request: ToolCallRequest) -> tuple[str, str]:
    """Return the additional-context CLI flag and rendered block."""
    additional_context = str(request.get("additional_context", ""))
    if not additional_context:
        return "", ""
    escaped_context = additional_context.replace("\n", "\\n")
    return (
        f" --additional-context {shlex.quote(escaped_context)}",
        f"\nADDITIONAL CONTEXT FOR WORKER:\n{additional_context}\n",
    )


def parse_human_in_loop(context: str) -> bool:
    """Return the human-in-loop mode encoded in ``additional_context``."""
    for line in context.splitlines():
        key, separator, raw_value = line.partition(":")
        if separator and key.strip().lower() == "human_in_loop":
            return raw_value.strip().lower() != "false"
    return True


def format_tool_call(request: ToolCallRequest) -> str:
    """Format a literal tool call for the orchestrator to execute.

    The dispatch plumbing (STEP 1/2/3, tailing discipline, reminder rule,
    no-op suppression) is emitted on every dispatch. The tailored post_block
    describes what to do when the worker idles. It is appended verbatim.
    """
    raw_command = _command_text(request["command"]).lstrip("/")
    formatted_command = _format_slash_command(raw_command)
    args = str(request["args"])
    project = str(request["project"])
    subfolder = str(request["subfolder"])
    post_block = str(request.get("post_block", ""))
    pre_dispatch_block = _format_pre_dispatch_block(str(request.get("pre_dispatch", "")))
    additional_context_flag, additional_context_block = _format_additional_context(request)

    recommended_mode = str(request.get("recommended_mode", ""))
    mode_flag = recommended_mode and _MODE_FLAG_TEMPLATE.format(mode=recommended_mode)
    reminder_instruction = format_orchestration_watch_instruction(
        machine=raw_command,
        slug=args,
        restart_cadence=False,
    )
    reminder_reset_instruction = format_orchestration_watch_instruction(
        machine=raw_command,
        slug=args,
        restart_cadence=True,
    )

    result = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

{ORCHESTRATOR_IDLE_INVARIANT}

Execute these steps in order (FOLLOW TO THE LETTER!):

{pre_dispatch_block}STEP 1 - DISPATCH:
Dispatch metadata: command="{formatted_command}" args="{args}" project="{project}" subfolder="{subfolder}"
{additional_context_block}
telec sessions run --command "{formatted_command}" --args "{args}" --path "{project}"{mode_flag} \
  --subfolder "{subfolder}"{additional_context_flag}
Save the returned session_id.

STEP 2 - ARM THE BACKUP REMINDER AND INITIALIZE MARKER:
{reminder_instruction}
Save the current time as <marker_timestamp> for the tailing discipline.
INTENT — read this before continuing: the notification is the completion signal; you will be told.
This reminder is a backup check-in only — its sole purpose is to re-engage YOUR judgment when you
have heard nothing. It does not watch or assess the worker; you do.

STEP 3 - WAIT PASSIVELY:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
Do nothing until an event arrives in your conversation. No tailing between events, no extra
watchers, or parallel wake mechanisms.

TAILING DISCIPLINE (every arriving event — a notification or orchestration-watch reminder —
licenses exactly one tail; no event, no tail):
- First tail: default latest-turn window (no --since). Save the latest message timestamp as <marker_timestamp>.
- All subsequent tails: use --since <marker_timestamp>. Update marker after each tail.
Each telec sessions tail response includes `last_input_at`, `last_activity`,
`last_agent_stop_at`, and computed `agent_status`.

Status semantics:
- `active`: the session is non-terminal and the latest observed activity is not an authoritative stop.
- `idle`: the session is terminal (`closing`/`closed` or `closed_at` set), or the latest turn has an agent stop with no later input.
- `unknown`: no `last_activity` has been recorded yet.

REMINDER RULE:
- On notification arrival: tail once and act on what you read.
- On reminder arrival (you heard nothing): tail once and judge what you see. Silence may be deep
  work, saturation, or a dead worker — that assessment is yours, never a script's.
- If `agent_status` is `active` or `unknown`: the recurring reminder remains armed; return to passive waiting.
- If `agent_status` is `idle`: run `telec reminders cancel orchestration-watch`, then proceed to the
  WHEN WORKER COMPLETES section below.
- RECOVERY: `telec reminders list`; if orchestration-watch is absent, arm it with the STEP 2 command.

FEEDBACK MESSAGES:
- When sending a message to the worker because it needs feedback: {reminder_reset_instruction}
- Only send telec sessions send when there is actionable content: concrete gate failure details, a direct answer to a worker question, or a user-directed plan change.

{post_block}

ORCHESTRATION PRINCIPLE:
You are an orchestrator. Execute the state machine's output verbatim. \
The state machine owns session lifecycle and dispatch decisions; phase is derived \
each call from stamped primitives (verdicts, approvals, skip stamps, drift review). \
Trust the process gates (pre-commit hooks, stamp clerical checks)."""
    note = str(request.get("note", ""))
    if note:
        result += f"\n\nNOTE: {note}"
    return result


def format_command_loader_message(command_name: str, slug: str) -> str:
    """Format a Codex-style command loader for a dispatched prepare worker.

    Produces the same instruction pattern used by ``_build_codex_loader_message``
    in sessions_actions_routes so workers load the full command artifact
    (with Required reads, role, and discipline) for their current phase.
    """
    prompt_path = COMMANDS_DIR / f"{command_name}.md"
    return (
        f"Read {prompt_path} and follow it exactly as the active instruction set "
        f"for this session.\n\n"
        f"Treat the following as provided inputs to that instruction set:\n"
        f"{slug}"
    )


def format_procedure_load(
    *,
    slug: str,
    command_name: str,
    hat: str,
    expected: str,
    reason: DispatchReason | None = None,
    diffs: list[tuple[str, str, str, str]] | None = None,
    additional_context: str = "",
) -> str:
    """Format a procedure-load instruction for the active prepare session.

    Used by the prepare state machine when the next phase is a drafting phase
    (intake, architecture, test specs, plan) or the bug lane's interrogation
    step, which the driving session also performs inline. The same session
    reads the phase's procedure and does the phase's work. Reviewer phases
    keep using ``format_tool_call`` because they are legitimate cross-model
    dispatches.

    When ``reason`` is supplied, an explicit ``Dispatch reason: <reason>``
    header is prepended so a re-entry drafting phase (currently only the plan
    phase) tells the worker why it was dispatched instead of falling silently
    to the fresh default. When ``reason`` is ``None`` the output is unchanged,
    so non-plan draft dispatches are untouched.

    ``additional_context``, when non-empty, is appended as its own section —
    used by the bug lane's interrogation load to name the live diagnosis peer
    session to question.
    """
    loader = format_command_loader_message(command_name, slug)
    body = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

SLUG: {slug}

NEXT ACTION:
Put on the {hat} hat. Read the procedure for this turn:

{loader}

The wider prepare lifecycle is still yours. This is one focused phase. The
procedure is loaded inline; no new session is dispatched.

EXPECTED DELIVERABLE: {expected}

WHEN THE PHASE'S WORK IS COMPLETE:
Call `telec todo prepare {slug}` to advance the state machine. The state
machine will route the next action — dispatch a reviewer, pause for human
approval, load the next phase's procedure, or terminate at PREPARED / BLOCKED."""
    if additional_context:
        body = f"{body}\n\n{additional_context}"
    if reason is None:
        return body
    return format_dispatch_reason(body, slug, reason, diffs)


def format_error(code: str, message: str, next_call: str = "") -> str:
    """Format an error message with optional next step."""
    result = f"ERROR: {code}\n{message}"
    if next_call:
        result += f"\n\nNEXT: {next_call}"
    return result


def format_prepared(
    slug: str,
    session_ids_to_end: list[str] | None = None,
    auto_continue_operations: list[str] | None = None,
    *,
    suppress_self_end: bool = False,
) -> str:
    """Format the PREPARED terminal message for the prepare state machine.

    Cleanup is the single cleanup point for the prepare lifecycle. When
    auto-continue operations exist, they run before cleanup so fresh dispatches
    are started before the current session ends.
    """
    operations = ""
    if auto_continue_operations:
        operation_lines = "\n".join(auto_continue_operations)
        operations = f"AUTO-CONTINUE:\nExecute in order:\n{operation_lines}\n\n"

    cleanup_lines = list(f"telec sessions end {sid}" for sid in session_ids_to_end or [])
    if not suppress_self_end:
        cleanup_lines.append("telec sessions end self")
    cleanup = "\n".join(cleanup_lines)
    cleanup_block = f"{cleanup}\n\n" if cleanup else ""

    terminal_note = (
        "AUTO-CONTINUE dispatched dependent prepare work."
        if auto_continue_operations
        else (
            f"{slug} is prepared; any drift is reconciled. If you reached this as a terminal "
            f"prepare, run the cleanup above and self-end. If you bounced here in-line from "
            f"telec todo work {slug} to reconcile drift, skip the self-end and resume that "
            f"work — you know your own lineage."
        )
    )
    if auto_continue_operations:
        return f"PREPARED: {slug} is ready for work.\n\n{operations}{cleanup_block}{terminal_note}"

    return f"{cleanup_block}PREPARED: {slug} is ready for work.\n\n{terminal_note}"


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to resolve worktree uncommitted changes."""
    return f"""UNCOMMITTED CHANGES in {WORKTREE_DIR}/{slug}

NEXT: Resolve these changes according to the commit policy, then call telec todo work {slug} to continue."""


def _work_entry_analyze_post_block(slug: str) -> str:
    return f"""WHEN WORKER COMPLETES:
The worker stamps a --drift-reviewed verdict for every pending artifact and drives no further step.
1. Tail the worker's final output to verify it stamped every pending artifact.
2. Call `telec todo work {slug}` to re-enter the work state machine, which reads the stamped verdict and continues."""


def format_work_entry_drift_bounce(
    *,
    slug: str,
    project_root: str,
    pending_classes: str,
) -> str:
    """Dispatch the drift analyzer from the work-entry bounce on pending drift.

    The work state machine owns the work-entry drift path end-to-end: on a
    ``pending`` collapsed status it dispatches the ``next-drift-analyze`` worker
    and tells the orchestrator to re-enter ``telec todo work`` once the analyzer
    idles. The work orchestrator never calls ``telec todo prepare`` — its only
    verb is ``telec todo work``.
    """
    request = ToolCallRequest(
        command=f"/{SlashCommand.NEXT_DRIFT_ANALYZE.value}",
        args=slug,
        project=project_root,
        subfolder="",
        post_block=_work_entry_analyze_post_block(slug),
        additional_context=pending_classes,
        note=f"Required reading for this worker: {COMMANDS_DIR / f'{SlashCommand.NEXT_DRIFT_ANALYZE.value}.md'}",
    )
    return format_tool_call(request)


def format_work_entry_substantive_handoff(slug: str) -> str:
    """Hand the bounced work orchestrator into prepare to re-derive on substantive drift.

    A substantive work-entry drift bounce hands the same session (same
    ``active_runner`` claim) into the prepare state machine to re-derive the
    affected artifact. Calling ``telec todo prepare {slug}`` next implicitly
    adopts this session as the slug's prepare-orchestrator in place — the
    generic claim-reflection mechanism confers prepare-write authority the
    moment that call runs, before any artifact write happens. Once prepare
    reaches PREPARED again, its own terminal output recognizes this session's
    lineage and directs it to resume work rather than self-end.
    """
    loader = format_command_loader_message(SlashCommand.NEXT_PREPARE.value, slug)
    return f"""IMPORTANT: This output is an execution script. Follow it verbatim.

WORK_ENTRY_SUBSTANTIVE_DRIFT: {slug} has substantive prepare-artifact drift. Worktree setup was not started.

Your slug claim is unchanged. Calling `telec todo prepare {slug}` next will adopt you as {slug}'s prepare-orchestrator in place, carrying prepare-write authority for the re-derivation write.

NEXT ACTION:
Become the prepare orchestrator for {slug}. Read the prepare orchestrator procedure:

{loader}

Then call `telec todo prepare {slug}` and follow its output verbatim. The prepare state machine re-derives the affected artifact and reaches PREPARED — its terminal output will recognize you bounced in from work and tell you to resume work in this same session rather than self-end."""


def format_finalize_handoff_complete(slug: str, child_session_ids: list[str] | None = None) -> str:
    """Format the terminal handoff step after finalize readiness is recorded."""
    steps: list[str] = []
    steps.append(
        f'1. Report: "Candidate {slug} handed off to the integration event chain. '
        f'The integrator will spawn automatically when the projection reports READY."'
    )

    step = 2
    if child_session_ids:
        end_cmds = "\n   ".join(f"telec sessions end {sid}" for sid in child_session_ids)
        steps.append(f"{step}. End child sessions:\n   {end_cmds}")
        step += 1

    steps.append(f"{step}. End this orchestrator session:\n   telec sessions end self")

    instructions = "\n".join(steps)
    return f"""FINALIZE HANDOFF COMPLETE: {slug}

INSTRUCTIONS FOR ORCHESTRATOR:
{instructions}

Work-stage responsibility for {slug} is complete. Do not call telec todo work {slug} again."""


def format_kickback_terminal(slug: str, child_session_ids: list[str] | None = None) -> str:
    """Format the terminal cleanup after a todo is kicked back to plan drafting.

    The kickback stamp already invalidated the implementation-plan and recorded the
    reason in the todo's input. The work machine has released the slug's working
    resources (worktree + local/remote branch + workspace dir). All that remains is
    to end the slug's workers and this orchestrator so the runner re-dispatches a
    fresh prepare that re-derives the plan from the input kickback block.
    """
    steps: list[str] = []
    steps.append(
        f'1. Report: "Todo {slug} was kicked back to plan drafting. Its working resources '
        f"(worktree + branch) were released; the runner will re-dispatch a fresh prepare "
        f'that reads the input kickback block as re-derivation context."'
    )

    step = 2
    if child_session_ids:
        end_cmds = "\n   ".join(f"telec sessions end {sid}" for sid in child_session_ids)
        steps.append(f"{step}. End child sessions:\n   {end_cmds}")
        step += 1

    steps.append(f"{step}. End this orchestrator session:\n   telec sessions end self")

    instructions = "\n".join(steps)
    return f"""KICKBACK TO PLAN DRAFTING: {slug}

INSTRUCTIONS FOR ORCHESTRATOR:
{instructions}

Work-stage responsibility for {slug} is released. Do not call telec todo work {slug} again."""


def format_stash_debt(slug: str, count: int) -> str:
    """Format instruction when repository stash is non-empty."""
    noun = "entry" if count == 1 else "entries"
    return format_error(
        "STASH_DEBT",
        f"Repository has {count} git stash {noun}. Stash workflows are forbidden for AI orchestration.",
        next_call=(
            "Clear all repository stash entries with maintainer-approved workflow, "
            f"then call telec todo work {slug} to continue."
        ),
    )
