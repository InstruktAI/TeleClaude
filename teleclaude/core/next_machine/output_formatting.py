"""Output formatters — plain text responses for the orchestrator AI.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import TYPE_CHECKING

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import REVIEW_DIFF_NOTE
from teleclaude.paths import COMMANDS_DIR

if TYPE_CHECKING:
    from teleclaude.core.next_machine.git_ops import ArtifactDriftStatus

__all__ = [
    "ORCHESTRATOR_IDLE_INVARIANT",
    "PENDING_DRIFT_CONTEXT_PREFIX",
    "REVIEW_DIFF_NOTE",
    "ToolCallRequest",
    "format_blocker_resolution",
    "format_command_loader_message",
    "format_error",
    "format_finalize_handoff_complete",
    "format_pending_classes_for_dispatch",
    "format_prepared",
    "format_procedure_load",
    "format_stash_debt",
    "format_tool_call",
    "format_uncommitted_changes",
    "format_work_entry_drift_bounce",
    "parse_human_in_loop",
]


ORCHESTRATOR_IDLE_INVARIANT = (
    "INVARIANT: Never invoke the next state-machine call (telec todo prepare/work/integrate) "
    "while a worker referenced in this script is still active. "
    "Always wait for the named worker(s) to emit agent_stop first."
)
PENDING_DRIFT_CONTEXT_PREFIX = "PENDING_DRIFT"
_PENDING_DRIFT_STATUS = "pending"
_DRIFT_CLASS_ORDER = {
    "code": 0,
    "upstream-artifact": 1,
    "owned-snippet": 2,
    "upstream-snippet": 3,
    "dependency-graph": 4,
    "age": 5,
}


class ToolCallRequest(dict[str, object]):  # guard: loose-dict - dynamic payload
    """Structured request mapping for orchestrator tool-call formatting.

    Fields consumed by format_tool_call:
        command: SlashCommand enum or string (required)
        args: worker arguments (required)
        project: project root path (required)
        guidance: agent selection guidance text (required)
        subfolder: worktree subfolder relative to project (required)
        post_block: tailored WHEN-WORKER-COMPLETES instructions (optional)
        pre_dispatch: pre-dispatch steps (optional)
        additional_context: extra context for the worker (optional)
        note: trailing note appended to the output (optional)
        recommended_mode: recommended thinking mode (fast|med|slow) for this
            worker; when set, fills the --mode slot and steers the orchestrator
            instead of leaving the choice open (optional)
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
    non-drift blockers, no-active-work, split-holder, and loop-limit cases.
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

    The dispatch plumbing (STEP 1/2/3, tailing discipline, heartbeat rule,
    no-op suppression) is emitted on every dispatch. The tailored post_block
    describes what to do when the worker idles. It is appended verbatim.
    """
    raw_command = _command_text(request["command"]).lstrip("/")
    formatted_command = _format_slash_command(raw_command)
    args = str(request["args"])
    project = str(request["project"])
    guidance = str(request["guidance"])
    subfolder = str(request["subfolder"])
    post_block = str(request.get("post_block", ""))
    pre_dispatch_block = _format_pre_dispatch_block(str(request.get("pre_dispatch", "")))
    additional_context_flag, additional_context_block = _format_additional_context(request)

    recommended_mode = str(request.get("recommended_mode", ""))
    mode_slot = recommended_mode if recommended_mode else "<your selection>"
    if recommended_mode:
        mode_selection_line = (
            "Based on the above guidance and the work item details, select the best agent. "
            f"Recommended thinking mode for this worker: {recommended_mode} — use it unless you "
            "have a specific reason to override."
        )
    else:
        mode_selection_line = (
            "Based on the above guidance and the work item details, select the best agent and thinking mode."
        )

    result = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

{ORCHESTRATOR_IDLE_INVARIANT}

Execute these steps in order (FOLLOW TO THE LETTER!):

{pre_dispatch_block}STEP 1 - DISPATCH:
{guidance}

{mode_selection_line}

PARALLELIZATION (pick the one matching your agent choice; append to --additional-context):
- claude:
    "Independent sub-tasks MUST be parallelized via TeamCreate — one team, multiple workers in a single call. Sequential dispatch of independent work is a failure mode; default to TeamCreate whenever two or more sub-tasks have no data dependency."
- codex:
    "When work decomposes into independent subtasks, immediately spawn bounded explorer/worker sub-agents for them and keep the critical path moving locally. Do not serialize non-blocking discovery, implementation, or verification; wait only when a result blocks integration, then merge/close agents."
- gemini:
    "Mandate: Identify independent sub-tasks and concurrently delegate them to sub-agents using `invoke_agent` in a single turn. Ensure parallel sub-agents do not mutate the same files; otherwise, execute them simultaneously without setting `wait_for_previous`."

Dispatch metadata: command="{formatted_command}" args="{args}" project="{project}" subfolder="{subfolder}"
{additional_context_block}
telec sessions run --command "{formatted_command}" --args "{args}" --project "{project}" \
  --agent "<your selection>" --mode "{mode_slot}" --subfolder "{subfolder}"{additional_context_flag}
Save the returned session_id.

STEP 2 - START THE BACKUP HEARTBEAT TIMER AND INITIALIZE MARKER:
Bash(command="sleep 300", run_in_background=true)
Save the returned task_id.
Save the current time as <marker_timestamp> for the tailing discipline.
INTENT — read this before continuing: the notification is the completion signal; you will be told.
This timer is a backup check-in only — its sole purpose is to re-engage YOUR judgment when you have
heard nothing. It is not a control loop and it does not watch the worker; you do.
- The timer is always a bare sleep. It never tests conditions, never invokes telec, never loops.
  (A shell test deciding "done/not done" is assessment smuggled into automation — forbidden.)
- Exactly one timer exists at a time. Kill the old (KillShell) before starting a new one.
- 300 seconds is the floor. NEVER set a tighter heartbeat.

STEP 3 - WAIT PASSIVELY:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
Do nothing until an event arrives in your conversation. No tailing between events, no extra
watchers, no tighter timers.

TAILING DISCIPLINE (every arriving event — a notification or your backup timer completing —
licenses exactly one tail; no event, no tail):
- First tail: default latest-turn window (no --since). Save the latest message timestamp as <marker_timestamp>.
- All subsequent tails: use --since <marker_timestamp>. Update marker after each tail.
Each telec sessions tail response includes `last_input_at`, `last_activity`,
`last_agent_stop_at`, and computed `agent_status`.

Status semantics:
- `active`: the session is non-terminal and the latest observed activity is not an authoritative stop.
- `idle`: the session is terminal (`closing`/`closed` or `closed_at` set), or the latest turn has an agent stop with no later input.
- `unknown`: no `last_activity` has been recorded yet.

HEARTBEAT RULE:
- On notification arrival: tail once and act on what you read.
- On timer completion (you heard nothing): tail once and judge what you see. Silence may be deep
  work, saturation, or a dead worker — that assessment is yours, never a script's.
- If `agent_status` is `active`: reset ONE bare backup timer and return to passive waiting.
- If `agent_status` is `idle`: proceed to the WHEN WORKER COMPLETES section below.
- If `agent_status` is `unknown`: reset ONE bare backup timer and return to passive waiting.
- RECOVERY: if you cannot tell whether your timer survived (restart, compaction): kill any timers
  you can, start ONE bare timer, resume passive waiting. Never compensate for uncertainty with
  extra watchers or shorter intervals.

FEEDBACK MESSAGES:
- When sending a message to the worker because it needs feedback: cancel the old timer via KillShell(shell_id=<task_id>), start a new backup heartbeat timer via Bash(command="sleep 300", run_in_background=true), and save the new task_id.
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
) -> str:
    """Format a procedure-load instruction for the active prepare session.

    Used by the prepare state machine when the next phase is a drafting phase
    (intake, architecture, test specs, plan). The same session reads the
    phase's procedure inline and does the phase's work. Reviewer phases keep
    using ``format_tool_call`` because they are legitimate cross-model
    dispatches.
    """
    loader = format_command_loader_message(command_name, slug)
    return f"""IMPORTANT: This output is an execution script. Follow it verbatim.

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
            f"DECISION REQUIRED: Continue preparation work, or start the build/review cycle "
            f"with telec todo work {slug}."
        )
    )
    if auto_continue_operations:
        return f"PREPARED: {slug} is ready for work.\n\n{operations}{cleanup_block}{terminal_note}"

    return f"{cleanup_block}PREPARED: {slug} is ready for work.\n\n{terminal_note}"


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to resolve worktree uncommitted changes."""
    return f"""UNCOMMITTED CHANGES in {WORKTREE_DIR}/{slug}

NEXT: Resolve these changes according to the commit policy, then call telec todo work {slug} to continue."""


def format_work_entry_drift_bounce(slug: str, drift_status_per_artifact: Mapping[str, str]) -> str:
    """Format the work-entry bounce back to prepare when drift is unresolved."""
    lines = ["DRIFT STATUS:"]
    for artifact, status in sorted(drift_status_per_artifact.items()):
        lines.append(f"- {artifact}: {status}")
    drift_block = "\n".join(lines)
    return f"""IMPORTANT: This output is an execution script. Follow it verbatim.

WORK_ENTRY_DRIFT: {slug} has unresolved prepare-artifact drift. Worktree setup was not started.

{drift_block}

NEXT ACTION:
1. Call `telec todo prepare {slug}`.
2. Follow the prepare state machine's drift-analysis or re-derivation instructions.
3. When prepare reaches PREPARED again, call `telec todo work {slug}`."""


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
