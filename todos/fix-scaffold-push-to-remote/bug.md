# Bug: telec bugs report (and telec todo scaffold) do not push scaffold commits to origin/main. Workers branch from origin/main and cannot find todo artifacts. The scaffold commit stays local, blocking all downstream work dispatch.

## Symptom

telec bugs report (and telec todo scaffold) do not push scaffold commits to origin/main. Workers branch from origin/main and cannot find todo artifacts. The scaffold commit stays local, blocking all downstream work dispatch.

## Detail

## Bug Description

When `telec bugs report` or `telec todo scaffold` creates a scaffold commit on main,
it does not push the commit to `origin/main`. Since worktrees branch from `origin/main`,
workers cannot find the todo artifacts (bug.md, state.yaml, etc.).

## Steps to Reproduce

1. Run `telec bugs report "some bug description" --slug some-bug`
2. Observe: scaffold commit is created locally on main
3. Run `telec todo work some-bug`
4. State machine returns `REMOTE_SYNC_FAILED` because artifacts are not on `origin/main`

## Expected Behavior

Scaffold commits (which are `[skip ci]` bookkeeping) should be pushed to `origin/main`
automatically after creation, using `TELECLAUDE_ALLOW_MAIN_PUSH=1` to bypass the git
wrapper's agent push block.

## Root Cause

The scaffold flow commits locally but has no push step. The git wrapper blocks agent
pushes to main by default, but provides `TELECLAUDE_ALLOW_MAIN_PUSH=1` as an override
for exactly this kind of automation bookkeeping.

## Impact

Blocks ALL bug reports and todo scaffolds from proceeding to work dispatch without
manual intervention to push.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

Confirmed that `telec bugs report`, `telec todo scaffold`, `telec todo dump`, and `telec todo split` create local scaffold artifacts but do not commit or push them to `origin/main`. This causes workers (which branch from `origin/main`) to fail finding the artifacts.

While `next_work` (orchestrator) calls `_ensure_todo_on_remote_main` to sync artifacts before starting work, this push was also blocked by the `.githooks/pre-push` guardrail, which didn't respect the `TELECLAUDE_ALLOW_MAIN_PUSH=1` override used for automation bookkeeping.

## Root Cause

1. The CLI handlers for bug reporting and todo scaffolding were missing the commit/push step.
2. The `.githooks/pre-push` hook was too restrictive and did not allow pushes even when `TELECLAUDE_ALLOW_MAIN_PUSH=1` was set.

## Fix Applied

1. Updated `.githooks/pre-push` to allow pushes if `TELECLAUDE_ALLOW_MAIN_PUSH=1`.
2. Updated CLI handlers in `teleclaude/cli/telec/handlers/bugs.py` and `teleclaude/cli/telec/handlers/todo.py` to call `_ensure_todo_on_remote_main` after scaffolding. This ensures artifacts are pushed immediately from the caller's context.
