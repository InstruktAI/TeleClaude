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
    "ConvergenceAssessmentScript",
    "HumanApprovalScript",
    "PairFormationScript",
    "PairTurnScript",
    "ToolCallRequest",
    "format_command_loader_message",
    "format_convergence_assessment_script",
    "format_error",
    "format_finalize_handoff_complete",
    "format_human_approval_script",
    "format_pair_formation_script",
    "format_pair_turn_script",
    "format_prepared",
    "format_stash_debt",
    "format_tool_call",
    "format_uncommitted_changes",
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


class PairFormationScript(dict[str, object]):  # guard: loose-dict - dynamic payload
    """Structured request for first prepare-pair formation."""


class ConvergenceAssessmentScript(dict[str, object]):  # guard: loose-dict - dynamic payload
    """Structured request for pair discovery convergence assessment."""


class PairTurnScript(dict[str, object]):  # guard: loose-dict - dynamic payload
    """Structured request for a prepare-pair send turn."""


class HumanApprovalScript(dict[str, object]):  # guard: loose-dict - dynamic payload
    """Structured request for the human requirements approval pause."""


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
each call from stamped primitives (verdicts, git commits, DOR, grounding). \
Trust the process gates (pre-commit hooks, stamp clerical checks)."""
    note = str(request.get("note", ""))
    if note:
        result += f"\n\nNOTE: {note}"
    return result


def format_pair_formation_script(script: PairFormationScript) -> str:
    """Format the dual-dispatch script used to form the prepare pair."""
    command = _format_slash_command(script["command"])
    args = str(script["args"])
    project = str(script["project"])
    subfolder = str(script["subfolder"])
    agent_a = str(script["agent_a"])
    agent_b = str(script["agent_b"])
    mode_a = str(script.get("mode_a", "slow"))
    mode_b = str(script.get("mode_b", "slow"))
    slug = str(script["slug"])
    return f"""IMPORTANT: This output is a prepare-pair formation script. Follow it verbatim.

{ORCHESTRATOR_IDLE_INVARIANT}

Execute these steps in order:

STEP 1 - DISPATCH INDEPENDENT INTAKE WORKERS:
telec sessions run --command "{command}" --args "{args}" --project "{project}" --agent "{agent_a}" --mode "{mode_a}" --subfolder "{subfolder}"
Save the returned session_id as <A_id>.

telec sessions run --command "{command}" --args "{args}" --project "{project}" --agent "{agent_b}" --mode "{mode_b}" --subfolder "{subfolder}"
Save the returned session_id as <B_id>.

Do not link the workers during intake.

STEP 2 - WAIT FOR BOTH INTAKES:
Wait for both agent_stop signals. Tail each worker independently until both report idle.

STEP 3 - LINK THE PAIR FOR DISCOVERY:
Send these two messages (do NOT use --direct yourself):

telec sessions send <A_id> "You are now entering paired discovery with your partner (session <B_id>). Establish a direct link by running: telec sessions send <B_id> 'Starting paired discovery' --direct. Then begin exploring the problem together as described in your briefing."

telec sessions send <B_id> "You are now entering paired discovery. Your partner will establish a direct connection with you shortly. Wait for their message, then begin exploring together as described in your briefing."

STEP 4 - REGISTER PAIR IDENTITY:
telec todo stamp {slug} --agent-a <A_id> --agent-b <B_id>

The stamp resolves agent and native_session_id from each session record and atomically writes both slots into todo state. Without this step the state machine cannot see the pair on the next re-entry.

STEP 5 - WAIT FOR DISCOVERY IDLENESS:
After A links the pair (Step 3) the workers begin paired discussion. Wait for BOTH <A_id> AND <B_id> to emit agent_stop after their conversation converges. Do not call the next state-machine step while either is still active.

STEP 6 - RE-ENTER:
telec todo prepare {slug}"""


def format_convergence_assessment_script(script: ConvergenceAssessmentScript) -> str:
    """Format the pair discovery convergence assessment instruction."""
    slug = str(script["slug"])
    slot_a = str(script["slot_a"])
    slot_b = str(script["slot_b"])
    return (
        f"CONVERGENCE ASSESSMENT: {slug}\n\n"
        f"{ORCHESTRATOR_IDLE_INVARIANT}\n\n"
        f"Execute in order:\n\n"
        f"telec sessions tail {slot_a}\n"
        f"telec sessions tail {slot_b}\n\n"
        f"Assess whether both workers have converged on what the requirements should contain.\n\n"
        f"If converged, tell A to close the direct link and write requirements:\n"
        f'  telec sessions send {slot_a} "Close your direct link by running: '
        f"telec sessions send {slot_b} --close-link. "
        f"Then write the agreed requirements with: "
        f"telec todo artifacts write {slug} requirements <content>. "
        f'When done, stamp: telec todo stamp {slug} --requirements-ready."\n\n'
        f"Do NOT message B yet. Wait for A to go idle, then call telec todo prepare {slug}.\n\n"
        f"If not converged, send concrete feedback to guide further discussion."
    )


def _escaped_session_message(message: object) -> str:
    """Escape a message for the literal telec sessions send command."""
    return str(message).replace('"', '\\"')


def format_pair_turn_script(script: PairTurnScript) -> str:
    """Format a writer, reviewer, or continuation send to a stored pair member."""
    slug = str(script["slug"])
    session_id = str(script["session_id"])
    message = _escaped_session_message(script["message"])
    next_step = str(script["next_step"])
    turn = str(script.get("turn", "write"))

    if turn == "write":
        return (
            f"PAIR WRITE TURN: {slug}\n\n"
            f"{ORCHESTRATOR_IDLE_INVARIANT}\n\n"
            f"Execute in order:\n\n"
            f'telec sessions send {session_id} "{message}"\n\n'
            f"Wait for writer agent_stop, then call {next_step}."
        )

    if turn == "review":
        return (
            f"PAIR REVIEW TURN: {slug}\n\n"
            f"{ORCHESTRATOR_IDLE_INVARIANT}\n\n"
            f"Execute in order:\n\n"
            f'telec sessions send {session_id} "{message}"\n\n'
            f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
            f'Start a new non-blocking heartbeat timer via Bash(command="sleep 300", run_in_background=true) '
            f"and save the new task_id.\n"
            f"When the reviewer reports idle, call {next_step}."
        )

    return (
        f"PAIR CONTINUATION: {slug}\n\n"
        f"{ORCHESTRATOR_IDLE_INVARIANT}\n\n"
        f"Execute in order:\n\n"
        f'telec sessions send {session_id} "{message}"\n\n'
        f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
        f'Start a new non-blocking heartbeat timer via Bash(command="sleep 300", run_in_background=true) '
        f"and save the new task_id.\n"
        f"When the worker reports idle, call {next_step}."
    )


def format_human_approval_script(script: HumanApprovalScript) -> str:
    """Format the restart-safe human approval pause instruction."""
    slug = str(script["slug"])
    return (
        f"HUMAN APPROVAL: {slug}\n\n"
        f"{ORCHESTRATOR_IDLE_INVARIANT}\n\n"
        f"Present the full artifact set to the human:\n"
        f"  telec todo artifacts read {slug} requirements\n"
        f"  telec todo artifacts read {slug} implementation-plan\n\n"
        f"If the human approves, stamp approval and re-enter prepare:\n"
        f"  telec todo stamp {slug} --verdict approve --phase requirements_human_approval\n"
        f"  telec todo prepare {slug}\n\n"
        f"If the human gives feedback, relay it to the appropriate worker in the stored prepare pair. "
        f"Keep the flow fix-forward; do not return to discovery."
    )


def format_command_loader_message(command_name: str, slug: str) -> str:
    """Format a Codex-style command loader for a pair member turn.

    Produces the same instruction pattern used by ``_build_codex_loader_message``
    in sessions_actions_routes so that existing pair sessions load the full
    command artifact (with Required reads, role, and discipline) for their
    next turn-based role.
    """
    prompt_path = COMMANDS_DIR / f"{command_name}.md"
    return (
        f"Read {prompt_path} and follow it exactly as the active instruction set "
        f"for this session.\n\n"
        f"Treat the following as provided inputs to that instruction set:\n"
        f"{slug}"
    )


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
