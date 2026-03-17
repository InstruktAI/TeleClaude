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

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
