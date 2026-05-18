"""Output formatters — plain text responses for the orchestrator AI.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import REVIEW_DIFF_NOTE
from teleclaude.paths import COMMANDS_DIR

__all__ = [
    "ORCHESTRATOR_IDLE_INVARIANT",
    "REVIEW_DIFF_NOTE",
    "ToolCallRequest",
    "format_blocker_resolution",
    "format_command_loader_message",
    "format_error",
    "format_finalize_handoff_complete",
    "format_prepared",
    "format_skill_load",
    "format_stash_debt",
    "format_tool_call",
    "format_uncommitted_changes",
    "parse_human_in_loop",
]


ORCHESTRATOR_IDLE_INVARIANT = (
    "INVARIANT: Never invoke the next state-machine call (telec todo prepare/work/integrate) "
    "while a worker referenced in this script is still active. "
    "Always wait for the named worker(s) to emit agent_stop first."
)


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
    """


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


def _format_additional_context(request: ToolCallRequest) -> tuple[str, str]:
    """Return the additional-context CLI flag and rendered block."""
    additional_context = str(request.get("additional_context", ""))
    if not additional_context:
        return "", ""
    escaped_context = additional_context.replace("\n", "\\n")
    return (
        f' --additional-context "{escaped_context}"',
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

    result = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

{ORCHESTRATOR_IDLE_INVARIANT}

Execute these steps in order (FOLLOW TO THE LETTER!):

{pre_dispatch_block}STEP 1 - DISPATCH:
{guidance}

Based on the above guidance and the work item details, select the best agent and thinking mode.

Dispatch metadata: command="{formatted_command}" args="{args}" project="{project}" subfolder="{subfolder}"
{additional_context_block}
telec sessions run --command "{formatted_command}" --args "{args}" --project "{project}" \
  --agent "<your selection>" --mode "<your selection>" --subfolder "{subfolder}"{additional_context_flag}
Save the returned session_id.

STEP 2 - START NON-BLOCKING HEARTBEAT TIMER AND INITIALIZE MARKER:
Bash(command="sleep 300", run_in_background=true)
Save the returned task_id.
Save the current time as <marker_timestamp> for the tailing discipline.
The timer runs in the background; notifications and timer completion arrive in your conversation.

STEP 3 - WAIT:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
Act on the next event that fires in your conversation — notification or timer completion.

TAILING DISCIPLINE:
- First tail: full window (no --since). Save the latest message timestamp as <marker_timestamp>.
- All subsequent tails: use --since <marker_timestamp>. Update marker after each tail.
Each telec sessions tail response includes `last_input_at`, `last_activity`,
`last_agent_stop_at`, and computed `agent_status`.

Status semantics:
- `active`: `last_activity` exists and the latest observed activity is not the agent stop event.
- `idle`: `last_activity` exists and `last_agent_stop_at == last_activity`.
- `unknown`: no `last_activity` has been recorded yet.

HEARTBEAT RULE:
- On notification arrival or timer completion: tail the session (first time: full window; subsequent: --since <marker_timestamp>).
- Update <marker_timestamp> to the latest message timestamp when new messages appear.
- If `agent_status` is `active`: reset the non-blocking heartbeat timer and wait for the next event.
- If `agent_status` is `idle`: proceed to the WHEN WORKER COMPLETES section below.
- If `agent_status` is `unknown`: wait for the next event.

FEEDBACK MESSAGES:
- When sending a message to the worker because it needs feedback: cancel the old timer via KillShell(shell_id=<task_id>), start a new heartbeat timer via Bash(command="sleep 300", run_in_background=true), and save the new task_id.
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


def format_skill_load(
    *,
    slug: str,
    command_name: str,
    hat: str,
    expected: str,
) -> str:
    """Format a skill-load instruction for the active prepare session.

    Used by the prepare state machine when the next phase is a drafting phase
    (intake, architecture, test specs, plan). The same session loads the
    phase's skill inline and does the phase's work. Reviewer phases keep
    using ``format_tool_call`` because they are legitimate cross-model
    dispatches.
    """
    loader = format_command_loader_message(command_name, slug)
    return f"""IMPORTANT: This output is an execution script. Follow it verbatim.

SLUG: {slug}

NEXT ACTION:
Put on the {hat} hat. Load the /{command_name} skill in this session:

{loader}

The wider prepare lifecycle is still yours. This is one focused phase. The
skill is loaded inline; no new session is dispatched.

EXPECTED DELIVERABLE: {expected}

WHEN THE PHASE'S WORK IS COMPLETE:
Call `telec todo prepare {slug}` to advance the state machine. The state
machine will route the next action — dispatch a reviewer, pause for human
approval, load the next phase's skill, or terminate at PREPARED / BLOCKED."""


def format_error(code: str, message: str, next_call: str = "") -> str:
    """Format an error message with optional next step."""
    result = f"ERROR: {code}\n{message}"
    if next_call:
        result += f"\n\nNEXT: {next_call}"
    return result


def format_prepared(slug: str, session_ids_to_end: list[str] | None = None) -> str:
    """Format the PREPARED terminal message for the prepare state machine.

    When session_ids_to_end is provided, the output begins with end commands
    for each session followed by `telec sessions end self` to end the
    orchestrator. This is the single cleanup point for the prepare lifecycle.
    """
    cleanup = ""
    if session_ids_to_end:
        end_lines = "\n".join(f"telec sessions end {sid}" for sid in session_ids_to_end)
        cleanup = f"{end_lines}\ntelec sessions end self\n\n"
    return (
        f"{cleanup}PREPARED: {slug} is ready for work.\n\n"
        f"DECISION REQUIRED: Continue preparation work, or start the build/review cycle "
        f"with telec todo work {slug}."
    )


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to resolve worktree uncommitted changes."""
    return f"""UNCOMMITTED CHANGES in {WORKTREE_DIR}/{slug}

NEXT: Resolve these changes according to the commit policy, then call telec todo work {slug} to continue."""


def format_finalize_handoff_complete(slug: str, next_call: str, child_session_ids: list[str] | None = None) -> str:
    """Format the slug-scoped handoff step after finalize readiness is recorded.

    Ends worker sessions only — the work orchestrator continues to the next
    queued slug. The work orchestrator self-ends only when the queue is empty.
    """
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

    steps.append(f"{step}. Call {next_call}")

    instructions = "\n".join(steps)
    return f"""FINALIZE HANDOFF COMPLETE: {slug}

INSTRUCTIONS FOR ORCHESTRATOR:
{instructions}"""


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
