"""Integration instruction formatters — structured messages returned to agents.

No imports from state_machine.py or step_functions.py (circular-import guard).

All commands assume the agent's cwd is the integration worktree. Commands that
target the project root (repo root sync, stash recovery) receive ``project_root``
and emit explicit ``git -C <project_root>`` prefixes.
"""

from __future__ import annotations

# Integrators bypass the commit-first review gate (system_role == "integrator" exempts them in
# the handler), so their commit instruction goes straight to --approved with
# a quoted message. Single source of truth — referenced by every integration
# decision template that ends with a commit step.
_COMMIT_CMD_INSTRUCTION = "telec code commit --approved '<your message>'"


def _format_anomalies(warnings: list[str]) -> str:
    """Render accumulated anomalies for agent-facing output. Empty when no warnings."""
    if not warnings:
        return ""
    items = "\n".join(f"- {w}" for w in warnings)
    return f"\n\n## Action Required\n\nThe following issues need resolution before ending this session:\n{items}"


def _format_commit_decision(
    slug: str,
    branch: str,
    diff_stats: str,
    branch_log: str,
    requirements: str,
    impl_plan: str,
    *,
    warnings: list[str] | None = None,
) -> str:
    return f"""INTEGRATION DECISION: SQUASH COMMIT REQUIRED

Candidate: {slug} (branch: {branch})

The branch has been squash-merged in the integration worktree (trees/_integration/).
Staged changes are ready for commit.

## Diff Stats
{diff_stats or "(no staged changes stat available)"}

## Branch Commit History
{branch_log or "(no history available)"}

## Requirements
{requirements[:2000] if requirements else "(not available)"}

## Implementation Plan
{impl_plan[:2000] if impl_plan else "(not available)"}

## Your Task
1. Review the above context
2. Compose a commit message:
   - Subject: clear, imperative, scoped (e.g. "feat({slug}): deliver {slug}")
   - Body: summarize what changed, key decisions, scope
   - Footer: TeleClaude Co-Authored-By trailer
3. Run: {_COMMIT_CMD_INSTRUCTION}
4. Then call: telec todo integrate

NEXT: Compose and execute telec code commit, then call telec todo integrate""" + _format_anomalies(warnings or [])


def _format_conflict_decision(
    slug: str, branch: str, conflicted_files: list[str], *, warnings: list[str] | None = None
) -> str:
    file_list = "\n".join(f"  - {f}" for f in conflicted_files) if conflicted_files else "  (none detected)"
    return f"""INTEGRATION DECISION: CONFLICT RESOLUTION REQUIRED

Candidate: {slug} (branch: {branch})

The squash merge of {branch} into main encountered conflicts:
{file_list}

## Resolution Rules

**Cardinal rule: preserve the best of both worlds.** Never pick one side wholesale.
Both branches contain intentional work — merge both contributions.

Full procedure: `telec docs get software-development/procedure/lifecycle/integrate`
(see CONFLICT RESOLUTION REQUIRED section)

## Steps
1. Read each conflicted file — understand the **intent** on both sides
2. Merge both contributions (do not use `--theirs` or `--ours`)
3. Verify: all API surface and behavior from both sides preserved
4. Stage resolved files: git add <files>
5. Run: {_COMMIT_CMD_INSTRUCTION}
6. Call: telec todo integrate

If unresolvable, call telec todo integrate without committing.

NEXT: Resolve conflicts, stage, commit with telec code commit, then call telec todo integrate""" + _format_anomalies(
        warnings or []
    )


def _format_push_rejected(rejection_reason: str, slug: str, worktree: str, *, warnings: list[str] | None = None) -> str:
    return f"""INTEGRATION DECISION: PUSH REJECTION RECOVERY

Candidate: {slug}

Push from integration worktree to origin/main was rejected.
Rejection output:
{rejection_reason}

## Your Task
1. Diagnose the rejection (likely non-fast-forward — another commit landed)
2. Fetch and rebase (each command targets the integration worktree):
   git -C {worktree} fetch origin
   git -C {worktree} rebase origin/main
3. Resolve any new conflicts if present
4. Push again: git -C {worktree} push origin HEAD:main
5. Then call: telec todo integrate

NEXT: Fetch, rebase, resolve (if needed), push, then call telec todo integrate""" + _format_anomalies(warnings or [])


def _format_lease_busy(holder_session_id: str) -> str:
    return f"""INTEGRATION ERROR: LEASE_BUSY

Another integrator session ({holder_session_id}) already holds the integration lease.
Only one integrator may run at a time.

Exit this session immediately. The active integrator will drain the queue.

NEXT: End this session — another integrator is already active"""


def _format_post_delivery_check(slug: str, project_root: str, worktree: str) -> str:
    return f"""INTEGRATION DECISION: POST-DELIVERY CHECK

Candidate {slug} delivered successfully.

Run: `cd {project_root} && .venv/bin/python tools/post_pull_check.py`
Follow any instructions, if given.
Then: `cd {worktree} && telec todo integrate`"""


def _format_queue_empty(
    items_processed: int, items_blocked: int, duration_ms: int, *, warnings: list[str] | None = None
) -> str:
    has_warnings = bool(warnings)
    next_line = (
        "NEXT: Resolve the issues above before ending this session."
        if has_warnings
        else "NEXT: End this session — integration complete"
    )
    return f"""INTEGRATION COMPLETE: Queue empty

Candidates processed: {items_processed}
Candidates blocked: {items_blocked}
Duration: {duration_ms}ms

The integration queue is empty.

{next_line}""" + _format_anomalies(warnings or [])


def _format_autostash_orphaned(stash_list: str, project_root: str) -> str:
    return f"""INTEGRATION ERROR: AUTOSTASH_ORPHANED

git pull --autostash succeeded but left an un-popped stash on repo root.
Dirty working tree changes conflicted with incoming changes from origin/main.

Current stash list:
{stash_list}

## Your Task
1. Pop the stash: `git -C {project_root} stash pop`
2. Resolve any conflicts between local changes and pulled content
3. Stage resolved files: `git -C {project_root} add <resolved files>`
4. If pop left unresolved conflict state: `git -C {project_root} stash drop` after resolving
5. Re-run: `telec todo integrate`

NEXT: Pop the orphaned stash on repo root, resolve conflicts, then call telec todo integrate"""


def _format_repo_root_diverged(stderr: str, project_root: str) -> str:
    return f"""INTEGRATION DECISION: REPO ROOT SYNC REQUIRED

Repo root main has diverged from origin/main after delivery push.

git pull --ff-only output:
{stderr.strip()}

All git commands targeting repo root must use: `git -C {project_root}`

If the working tree is clean: rebase local main onto origin/main (linear history,
no merge commit), resolve any conflicts preserving both sides, then call
telec todo integrate.

If dirty files block the sync: they are concurrent agents' uncommitted WIP — never
stash, overwrite, or rebase across them. This block is transient (they commit within
minutes). Do not idle or escalate — set a non-blocking heartbeat (~2-3 min), re-check
`git -C {project_root} status --short` each beat, and resume the instant it is clean.
Escalate to the human only if it stays dirty ~15-20 min (a stuck change, not WIP).

NEXT: Resolve divergence on repo root (or heartbeat-retry while blocked by dirty
WIP), then call telec todo integrate"""


def _format_error(code: str, message: str) -> str:
    return f"INTEGRATION ERROR: {code}\n{message}"


__all__ = [
    "_format_anomalies",
    "_format_autostash_orphaned",
    "_format_commit_decision",
    "_format_conflict_decision",
    "_format_error",
    "_format_lease_busy",
    "_format_post_delivery_check",
    "_format_push_rejected",
    "_format_queue_empty",
    "_format_repo_root_diverged",
]
