"""Output formatters — plain text responses for the orchestrator AI.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import PAREN_OPEN, REVIEW_DIFF_NOTE

__all__ = ["REVIEW_DIFF_NOTE", "POST_COMPLETION", "format_tool_call", "format_error", "format_prepared",
           "format_uncommitted_changes", "format_finalize_handoff_complete", "format_stash_debt"]

POST_COMPLETION: dict[str, str] = {
    "next-build": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. Call {next_call}
3. If next_work returns BUILD GATES FAILED or ARTIFACT VERIFICATION FAILED:
   - Send the failure details to the builder (do NOT end the session)
   - Wait for builder to report completion again
   - Repeat from step 2
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-bugs-fix": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. Call {next_call}
3. If next_work returns BUILD GATES FAILED or ARTIFACT VERIFICATION FAILED:
   - Send the failure details to the builder (do NOT end the session)
   - Wait for builder to report completion again
   - Repeat from step 2
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-review-build": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data to extract verdict
2. If verdict is APPROVE:
   a. telec sessions end <session_id>
   b. telec todo mark-phase {args} --phase review --status approved   c. Call {next_call}
3. If verdict is REQUEST CHANGES — PEER CONVERSATION PROTOCOL (keep reviewer alive):
   a. DO NOT end the reviewer session — keep it alive throughout peer iteration
   b. telec todo mark-phase {args} --phase review --status changes_requested   c. Dispatch fixer: telec sessions run --command /next-fix-review --args {args} \\
        --project <project-root> --subfolder trees/{args}
   d. Save <reviewer_session_id> and <fixer_session_id>
   e. Tell the reviewer to start a direct conversation with the fixer:
        telec sessions send <reviewer_session_id> "A fixer is active at <fixer_session_id>. \\
        Start a direct conversation: telec sessions send <fixer_session_id> '<your findings summary>' --direct. \\
        Collaborate until all findings are resolved, then update review-findings.md verdict \\
        to APPROVE and report FIX COMPLETE." (you will use regular send, NOT --direct)
   f. Wait for fixer to complete (monitor via heartbeat; do not poll continuously)
   g. When fixer reports FIX COMPLETE:
      - Read review-findings.md verdict
      - If APPROVE: telec sessions end <fixer_session_id>, telec sessions end <reviewer_session_id>,
          telec todo mark-phase {args} --phase review --status approved,
          call {next_call}
      - If still REQUEST CHANGES: telec sessions end <fixer_session_id>,
          telec sessions end <reviewer_session_id>,
          call {next_call} (state machine manages the round count and limit)
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-fix-review": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. telec sessions end <session_id>
3. telec todo mark-phase {args} --phase review --status pending4. Call {next_call}
5. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
6. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-defer": """WHEN WORKER COMPLETES:
1. Read worker output. Confirm deferrals_processed in state.yaml
2. telec sessions end <session_id>
3. Call {next_call}
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-finalize": """# state.yaml lives in the worktree only — never commit it to main directly.

WHEN WORKER COMPLETES:
1. Read worker output via get_session_data.
2. Accept completion only for the dispatched worker session `<session_id>`.
   Ignore notifications from any other session.
3. Confirm worker reported exactly `FINALIZE_READY: {args}` in session `<session_id>` transcript.
   If missing: send worker feedback to report FINALIZE_READY and stop (do NOT apply).
4. telec todo mark-finalize-ready {args} --worker-session-id <session_id>
5. telec sessions end <session_id>
6. Call {next_call}
7. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
8. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-build-specs": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. telec sessions end <session_id>
3. Call {next_call}
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-review-specs": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. telec sessions end <session_id>
3. Call {next_call}
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
}


def format_tool_call(
    command: str,
    args: str,
    project: str,
    guidance: str,
    subfolder: str,
    note: str = "",
    next_call: str = "",
    completion_args: str | None = None,
    pre_dispatch: str = "",
    additional_context: str = "",
) -> str:
    """Format a literal tool call for the orchestrator to execute."""
    raw_command = command.lstrip("/")
    formatted_command = f"/{raw_command}"

    # Get post-completion instructions for this command
    post_completion = POST_COMPLETION.get(command, "")
    if post_completion:
        next_call_display = next_call.strip()
        if next_call_display and PAREN_OPEN not in next_call_display and " " not in next_call_display:
            next_call_display = f"{next_call_display}()"
        completion_value = completion_args if completion_args is not None else args
        # Substitute {args} and {next_call} placeholders
        post_completion = post_completion.format(args=completion_value, next_call=next_call_display)

    pre_dispatch_block = ""
    if pre_dispatch:
        pre_dispatch_block = f"""STEP 0 - BEFORE DISPATCHING:
{pre_dispatch}

"""

    _escaped_ctx = additional_context.replace("\n", "\\n") if additional_context else ""
    additional_context_flag = f' --additional-context "{_escaped_ctx}"' if additional_context else ""
    additional_context_block = (
        f"\nADDITIONAL CONTEXT FOR WORKER:\n{additional_context}\n" if additional_context else ""
    )

    result = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

Execute these steps in order (FOLLOW TO THE LETTER!):

{pre_dispatch_block}STEP 1 - DISPATCH:
{guidance}

Based on the above guidance and the work item details, select the best agent and thinking mode.

Dispatch metadata: command="{formatted_command}" args="{args}" project="{project}" subfolder="{subfolder}"
{additional_context_block}
telec sessions run --command "{formatted_command}" --args "{args}" --project "{project}" --agent "<your selection>" --mode "<your selection>" --subfolder "{subfolder}"{additional_context_flag}
Legacy dispatch marker: command="{formatted_command}" subfolder="{subfolder}"
Save the returned session_id.
Command metadata: command="{formatted_command}" args="{args}" subfolder="{subfolder}".

STEP 2 - START BACKGROUND TIMER:
Bash(command="sleep 300", run_in_background=true)
Save the returned task_id.

STEP 3 - WAIT:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
Do NOT call any more tools UNTIL one of the events below fires.
When an event fires, you MUST immediately act on it — do NOT wait for user input.

WHAT HAPPENS NEXT (one of these will occur):

A) NOTIFICATION ARRIVES (worker completed):
   - The timer is now irrelevant (let it expire or ignore it)
   - Follow WHEN WORKER COMPLETES below

B) TIMER COMPLETES (no notification after 5 minutes):
   THIS IS YOUR ACTIVATION TRIGGER. You MUST act immediately:
   - Check on the session: telec sessions tail <session_id> --tools --thinking
   - If still running: reset timer (sleep 300, run_in_background=true) and WAIT again
   - If completed/idle: follow WHEN WORKER COMPLETES below
   - If stuck/errored: intervene or escalate to user
   Do NOT stop after checking — either reset the timer or execute completion steps.

C) YOU SEND ANOTHER MESSAGE TO THE AGENT BECAUSE IT NEEDS FEEDBACK OR HELP:
   - Cancel the old timer: KillShell(shell_id=<task_id>)
   - Start a new 5-minute timer: Bash(command="sleep 300", run_in_background=true)
   - Save the new task_id for the reset timer

D) NO-OP SUPPRESSION (NON-CHATTY ORCHESTRATION):
   - Never send no-op follow-ups like "No new input", "No further input", "Remain idle", or "Continue standing by".
   - Only send telec sessions send when there is actionable content:
     1) concrete gate failure details,
     2) a direct answer to an explicit worker question, or
     3) a user-directed change in plan.
   - If none apply, do not send another worker message; continue the state-machine loop.

{post_completion}

ORCHESTRATION PRINCIPLE: Guide process, don't dictate implementation.
You are an orchestrator, not a micromanager. Workers have full autonomy.
- NEVER run tests, lint, or make in/targeting worktrees
- NEVER edit or commit files in worktrees
- NEVER cd into worktrees — stay in the main repo root
- ALWAYS end the worker session when its step completes — no exceptions
- NEVER send no-op acknowledgements/keepalive chatter to workers
- Trust the process gates (pre-commit hooks, mark_phase clerical checks)
- If mark_phase rejects, the state machine routes to the fix — do NOT fix it yourself"""
    if note:
        result += f"\n\nNOTE: {note}"
    return result


def format_error(code: str, message: str, next_call: str = "") -> str:
    """Format an error message with optional next step."""
    result = f"ERROR: {code}\n{message}"
    if next_call:
        result += f"\n\nNEXT: {next_call}"
    return result


def format_prepared(slug: str) -> str:
    """Format a 'prepared' message indicating work item is ready."""
    return f"""PREPARED: todos/{slug} is ready for work.

DECISION REQUIRED: Continue preparation work, or start the build/review cycle with telec todo work {slug}."""


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to resolve worktree uncommitted changes."""
    return f"""UNCOMMITTED CHANGES in {WORKTREE_DIR}/{slug}

NEXT: Resolve these changes according to the commit policy, then call telec todo work {slug} to continue."""


def format_finalize_handoff_complete(slug: str, next_call: str, child_session_ids: list[str] | None = None) -> str:
    """Format the slug-scoped handoff step after finalize readiness is recorded."""
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
