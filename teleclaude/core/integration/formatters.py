"""Integration instruction formatters — structured messages returned to agents.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations


def _format_commit_decision(
    slug: str,
    branch: str,
    diff_stats: str,
    branch_log: str,
    requirements: str,
    impl_plan: str,
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
3. Run: git -C trees/_integration commit -m '<your message>'
4. Then call: telec todo integrate

NEXT: Compose and execute git commit in trees/_integration, then call telec todo integrate"""


def _format_conflict_decision(slug: str, branch: str, conflicted_files: list[str]) -> str:
    file_list = "\n".join(f"  - {f}" for f in conflicted_files) if conflicted_files else "  (none detected)"
    return f"""INTEGRATION DECISION: CONFLICT RESOLUTION REQUIRED

Candidate: {slug} (branch: {branch})

The squash merge of {branch} into main encountered conflicts in trees/_integration/:
{file_list}

## Your Task
1. Examine each conflicted file in trees/_integration/ and understand the code context
2. Resolve all conflict markers (<<<< ==== >>>>)
3. Stage resolved files: git -C trees/_integration add <files>
4. Compose a commit message capturing the delivery intent (same quality as squash commit)
5. Run: git -C trees/_integration commit -m '<your message>'
6. Then call: telec todo integrate

If conflicts are unresolvable, call: telec todo integrate
(The state machine will detect no commit was made and re-prompt.
To explicitly block the candidate, the agent must mark_blocked via queue.)

NEXT: Resolve conflicts in trees/_integration, stage, commit, then call telec todo integrate"""


def _format_push_rejected(rejection_reason: str, slug: str) -> str:
    return f"""INTEGRATION DECISION: PUSH REJECTION RECOVERY

Candidate: {slug}

Push from integration worktree to origin/main was rejected.
Rejection output:
{rejection_reason}

## Your Task
1. Diagnose the rejection (likely non-fast-forward — another commit landed)
2. Fetch and rebase in the integration worktree:
   git -C trees/_integration fetch origin
   git -C trees/_integration rebase origin/main
3. Resolve any new conflicts if present
4. Push again: git -C trees/_integration push origin HEAD:main
5. Then call: telec todo integrate

NEXT: Rebase in trees/_integration, resolve (if needed), push, then call telec todo integrate"""


def _format_lease_busy(holder_session_id: str) -> str:
    return f"""INTEGRATION ERROR: LEASE_BUSY

Another integrator session ({holder_session_id}) already holds the integration lease.
Only one integrator may run at a time.

Exit this session immediately. The active integrator will drain the queue.

NEXT: End this session — another integrator is already active"""


def _format_pull_blocked(pull_stderr: str, slug: str) -> str:
    return f"""INTEGRATION DECISION: REPO ROOT SYNC BLOCKED

Candidate: {slug} — delivery pushed to origin/main successfully.

Syncing local main with origin/main failed because of dirty local files:
{pull_stderr}

The delivery is safe on origin. But local main is now behind, and agents
starting work on local main will see stale files as truth.

## Your Task
1. Tell the user: "Integration delivered {slug} to origin/main, but local main
   has dirty files that block the pull. I need to stash local changes, pull, and
   restore them — but only when no other agent sessions are active on local main.
   Confirm when ready."
2. Wait for the user's confirmation.
3. Run the following commands in sequence:
   TELECLAUDE_INTEGRATION_STASH=1 git stash
   git pull --ff-only origin main
   TELECLAUDE_INTEGRATION_STASH=1 git stash pop
4. If stash pop succeeds cleanly, call: telec todo integrate
5. If stash pop produces conflicts:
   - Files deleted by the delivery that had local edits are obsolete — accept the delivered version
   - Real work that should be ported to new locations: move manually, then stage
   - After all conflicts resolved: TELECLAUDE_INTEGRATION_STASH=1 git stash drop
   - Then call: telec todo integrate

NEXT: Inform user, wait for confirmation, stash/pull/pop, resolve conflicts if any, then call telec todo integrate"""


def _format_queue_empty(items_processed: int, items_blocked: int, duration_ms: int) -> str:
    return f"""INTEGRATION COMPLETE: Queue empty

Candidates processed: {items_processed}
Candidates blocked: {items_blocked}
Duration: {duration_ms}ms

The integration queue is empty.

NEXT: End this session — integration complete"""


def _format_error(code: str, message: str) -> str:
    return f"INTEGRATION ERROR: {code}\n{message}"
