---
argument-hint: '[slug]'
description: Worker command - review code against requirements, output findings with verdict
---

# Review

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/principle/architecture-boundary-purity.md
- @~/.teleclaude/docs/software-development/concept/reviewer.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/linting-requirements.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/review.md

## Purpose

Review code changes against requirements and architecture and produce a verdict.

## Inputs

- Slug: `"$ARGUMENTS"`
- Worktree for the slug

## Outputs

- `todos/{slug}/review-findings.md`
- Verdict: APPROVE or REQUEST CHANGES
- Report format:

  ```
  REVIEW COMPLETE: {slug}

  Verdict: [APPROVE | REQUEST CHANGES]
  Findings: {count}
  ```

## Steps

- **If `todos/{slug}/bug.md` exists:** This is a bug fix. Use `bug.md` as the requirement source instead of `requirements.md`. Verify:
  - Fix addresses the symptom described in `bug.md`
  - Root cause analysis is sound
  - Fix is minimal and targeted
  - Investigation and documentation sections are complete
- **Otherwise:** Regular todo review. The Orchestrator has verified the clerical state of this build. Trust the state.yaml and implementation plan. Review code changes in the worktree against requirements and architecture.
- Treat orchestrator-managed planning/state drift as non-blocking review noise:
  - `todos/roadmap.yaml`
  - `todos/{slug}/state.yaml`
- Do not request commits or raise findings solely for those files unless review scope explicitly includes planning/state edits.
- Update only `## Review Gates (Reviewer)` in `todos/{slug}/quality-checklist.md` (if it exists).
- Write findings to `todos/{slug}/review-findings.md` with verdict: APPROVE or REQUEST CHANGES.
