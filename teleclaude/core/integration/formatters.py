"""Integration instruction formatters — structured messages returned to agents.

No imports from state_machine.py or step_functions.py (circular-import guard).

All commands assume the agent's cwd is the integration worktree. Commands that
target the project root (repo root sync, stash recovery) receive ``project_root``
and emit explicit ``git -C <project_root>`` prefixes.
"""

from __future__ import annotations

import shlex

from teleclaude.core.integration.checkpoint import ParkedCandidate
from teleclaude.core.integration.git_ops import RepoRootSyncOutcome, RepoRootSyncResult

# Integrators bypass the commit-first review gate (system_role == "integrator" exempts them in
# the handler), so their commit instruction goes straight to --approved with
# a quoted message. Single source of truth — referenced by every integration
# decision template that ends with a commit step.
_COMMIT_CMD_INSTRUCTION = "telec code commit --approved '<your message>'"
_PARKED_CANDIDATE_LINE = "- {slug}: {reason}"
_PARKED_CANDIDATE_SEPARATOR = "\n"
_PARKED_CANDIDATES_SECTION = "\n\nParked candidates:\n{items}"
_NO_PARKED_CANDIDATES = ""
_REPO_ROOT_PATH_LINE_SEPARATOR = "\n"
_REPO_ROOT_NO_PATHS = "  (none)"
_REPO_ROOT_PATH_INDENT = "  - "
_REPO_ROOT_READY_RESULT = "Cannot render a synchronization instruction for a ready repo-root result"
_REPO_ROOT_SPLIT_HISTORY_TEMPLATE = """INTEGRATION DECISION: REPO ROOT SPLIT HISTORY

Repo-root main has expected split history with origin/main.

Ahead commits: {ahead_count}
Behind commits: {behind_count}

Incoming files:
{incoming_paths}

Dirty overlap:
{dirty_overlap_paths}

All git commands targeting repo root must use: `git -C {project_root}`

If the working tree is clean, merge origin/main into local main and resolve any
conflicts. Never rebase repo-root main, and never let the state machine merge it
for you. If the merge cannot be resolved, stop and ask the human.

NEXT: Reconcile repo-root split history, then call telec todo integrate"""
_REPO_ROOT_DIRTY_OVERLAP_TEMPLATE = """INTEGRATION DECISION: REPO ROOT DIRTY OVERLAP

Incoming origin/main changes overlap uncommitted repo-root work:
{dirty_overlap_paths}

All git commands targeting repo root must use: `git -C {project_root}`

Do not stash, overwrite, rebase, merge across, or mutate these paths while a
live owner or attribution uncertainty protects them. Keep the prescribed
clearance reminder active through the quiet window.

After the quiet window, run this read-only ownership query for the complete
blocking set exactly as listed above:

`telec code owners {dirty_overlap_command_paths}`

On every later clearance-reminder beat while the same complete set remains
dirty, run a fresh ownership query. For each newly observed owner, send one
coordination message containing that owner's complete attributed subset; never
send another message to an owner already coordinated for this blocking set.
When a prior owner disappears, take the now-null path into inspection custody.

For a latest result with no live owner and zero undetermined sessions, inspect
the null-owned path and preserve discernible intent in a sanctioned path-scoped
commit or revert abandoned residue. A positive undetermined-session count blocks
revert authority for that query result; do not treat its null paths as abandoned.

Count later reminder beats for each unchanged live-owner/path group and for a
positive undetermined-session count. If either remains for three consecutive
later beats after first observation, escalate once with the complete current
owner groups, paths, and privacy-safe undetermined count; cancel
`integrator-main-clearance`, remain alive as the non-mutating blocker beacon,
and do not repeat coordination or escalation for that blocking set.

NEXT: Wait through the quiet window, then resolve the complete blocking set with
telec code owners and follow the ownership/custodianship flow above."""
_REPO_ROOT_FAILURE_TEMPLATE = """INTEGRATION ERROR: REPO ROOT SYNC {outcome}

Repo-root synchronization stopped while running `{operation}`.

Git diagnostic:
{diagnostic}

All git commands targeting repo root must use: `git -C {project_root}`

This is a Git operation failure, not a split-history diagnosis. Inspect and
resolve the failed operation without stashing, rebasing, or automatically merging.

NEXT: Resolve the Git operation failure, then call telec todo integrate"""


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
3. Run: {_COMMIT_CMD_INSTRUCTION}
4. Then call: telec todo integrate

NEXT: Compose and execute telec code commit, then call telec todo integrate""" + _format_anomalies(warnings or [])


def _format_conflict_decision(
    slug: str,
    branch: str,
    conflicted_files: list[str],
    worktree: str,
    *,
    warnings: list[str] | None = None,
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

If the conflict cannot be grounded confidently, abandon this candidate:
1. Run: git -C {worktree} reset --hard HEAD
2. Call: telec todo integrate

This parks the candidate and its dependents for the current drain, then continues
with every independent candidate.

NEXT: Resolve conflicts, stage, commit with telec code commit, then call telec todo integrate""" + _format_anomalies(
        warnings or []
    )


def _format_content_gate_conflict(
    slug: str, branch: str, rejection_reason: str, worktree: str, *, warnings: list[str] | None = None
) -> str:
    return f"""INTEGRATION DECISION: CONTENT-GATE CONFLICT — INTEGRATOR-OWNED

Candidate: {slug} (branch: {branch})

Push from the integration worktree to origin/main was rejected by the
pre-push content gate (`telec code lint --all` failed on the squash content).
This is invariant under rebase — treat it as a logical merge conflict on a
repo-wide invariant, in the same class as a textual merge conflict. No
upstream owner exists once a candidate is in the integration pipeline: you own
this conflict.

Rejection output:
{rejection_reason}

## Your Task
1. Reproduce: cd {worktree} && telec code lint --all
2. If mechanically groundable, resolve it there — for example, for a
   double-bound scenario, read both tests and drop the redundant binding when
   they observe the same behavior, or author the distinct scenario and retag.
   Write into the live contract body only, never inside a pending
   planned-change region.
3. Stage and commit: {_COMMIT_CMD_INSTRUCTION}
4. Call: telec todo integrate to re-push

If the fix cannot be grounded confidently, do not commit. Call telec todo
integrate again to re-surface this instruction and escalate to a human — the
integration line stays stopped on this candidate until the conflict is
resolved.

NEXT: Resolve the content-gate conflict and commit, or escalate to a human,
then call telec todo integrate""" + _format_anomalies(warnings or [])


def _format_push_rejected(rejection_reason: str, slug: str, worktree: str, *, warnings: list[str] | None = None) -> str:
    # Fast-forward-race recovery only: a content-gate rejection is classified and
    # routed to CONTENT_GATE_BLOCKED before this formatter is ever reached.
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


def _format_queue_empty(
    items_processed: int,
    items_blocked: int,
    duration_ms: int,
    parked: list[ParkedCandidate],
    *,
    warnings: list[str] | None = None,
) -> str:
    has_warnings = bool(warnings)
    parked_section = (
        _PARKED_CANDIDATES_SECTION.format(
            items=_PARKED_CANDIDATE_SEPARATOR.join(
                _PARKED_CANDIDATE_LINE.format(slug=candidate["slug"], reason=candidate["reason"])
                for candidate in parked
            )
        )
        if parked
        else _NO_PARKED_CANDIDATES
    )
    next_line = (
        "NEXT: Resolve the issues above before ending this session."
        if has_warnings
        else (
            "NEXT: Hold the prescribed recurring queue watcher with "
            "`telec reminders set integrator-queue-watch` and await the next candidates. "
            "End only when directed."
        )
    )
    return f"""INTEGRATION COMPLETE: Queue empty

Candidates processed: {items_processed}
Candidates blocked: {items_blocked}
Duration: {duration_ms}ms{parked_section}

The integration queue is empty.

{next_line}""" + _format_anomalies(warnings or [])


def _format_repo_root_paths(paths: tuple[str, ...]) -> str:
    """Render repo-relative paths without changing their facts."""
    if not paths:
        return _REPO_ROOT_NO_PATHS
    return _REPO_ROOT_PATH_LINE_SEPARATOR.join(f"{_REPO_ROOT_PATH_INDENT}{path}" for path in paths)


def _format_repo_root_split_history(result: RepoRootSyncResult, project_root: str) -> str:
    """Render the agent-owned split-history reconciliation instruction."""
    return _REPO_ROOT_SPLIT_HISTORY_TEMPLATE.format(
        ahead_count=result.ahead_count,
        behind_count=result.behind_count,
        incoming_paths=_format_repo_root_paths(result.incoming_paths),
        dirty_overlap_paths=_format_repo_root_paths(result.dirty_overlap_paths),
        project_root=project_root,
    )


def _format_repo_root_dirty_overlap(result: RepoRootSyncResult, project_root: str) -> str:
    """Render the non-destructive foreign-work wait instruction."""
    return _REPO_ROOT_DIRTY_OVERLAP_TEMPLATE.format(
        dirty_overlap_paths=_format_repo_root_paths(result.dirty_overlap_paths),
        dirty_overlap_command_paths=shlex.join(result.dirty_overlap_paths),
        project_root=project_root,
    )


def _format_repo_root_failure(result: RepoRootSyncResult, project_root: str) -> str:
    """Render a Git operation failure without misclassifying it as divergence."""
    return _REPO_ROOT_FAILURE_TEMPLATE.format(
        outcome=result.outcome.value,
        operation=result.failed_operation or result.outcome.value,
        diagnostic=result.diagnostic,
        project_root=project_root,
    )


_REPO_ROOT_SYNC_FORMATTERS = {
    RepoRootSyncOutcome.SPLIT_HISTORY: _format_repo_root_split_history,
    RepoRootSyncOutcome.DIRTY_OVERLAP: _format_repo_root_dirty_overlap,
    RepoRootSyncOutcome.FETCH_FAILED: _format_repo_root_failure,
    RepoRootSyncOutcome.GRAPH_INSPECTION_FAILED: _format_repo_root_failure,
    RepoRootSyncOutcome.DIRTY_STATE_INSPECTION_FAILED: _format_repo_root_failure,
    RepoRootSyncOutcome.FAST_FORWARD_FAILED: _format_repo_root_failure,
    RepoRootSyncOutcome.BOOKKEEPING_PUSH_FAILED: _format_repo_root_failure,
}


def _format_repo_root_sync_instruction(result: RepoRootSyncResult, project_root: str) -> str:
    """Render the typed non-ready repo-root decision for an agent."""
    if result.is_ready:
        raise ValueError(_REPO_ROOT_READY_RESULT)
    return _REPO_ROOT_SYNC_FORMATTERS[result.outcome](result, project_root)


def _format_error(code: str, message: str) -> str:
    return f"INTEGRATION ERROR: {code}\n{message}"


__all__ = [
    "_format_anomalies",
    "_format_commit_decision",
    "_format_conflict_decision",
    "_format_content_gate_conflict",
    "_format_error",
    "_format_lease_busy",
    "_format_push_rejected",
    "_format_queue_empty",
    "_format_repo_root_sync_instruction",
]
