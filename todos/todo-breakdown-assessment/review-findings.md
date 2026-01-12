# Code Review: todo-breakdown-assessment

**Reviewed**: 2026-01-12
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| next_prepare detects input.md and checks breakdown.assessed | ✅ | `next_prepare` branches on input.md + breakdown state. |
| AI assessment uses Definition of Ready criteria | ⚠️ | Prompt only lists single-session, verifiability, atomicity; missing scope clarity + uncertainty. |
| Complex todos split into new todo folders with input.md each | ⚠️ | Steps exist, but conflict with “do NOT write or modify any files” in the same command. |
| Dependencies updated in dependencies.json | ⚠️ | Documented in steps, but same conflict as above can block execution. |
| Roadmap updated with split todos in execution order | ⚠️ | Documented in steps, but same conflict as above can block execution. |
| breakdown.md created as reasoning artifact | ⚠️ | Documented in steps, but same conflict as above can block execution. |
| state.json updated with breakdown status | ⚠️ | Documented in steps, but same conflict as above can block execution. |
| Simple todos proceed to requirements.md creation normally | ✅ | `next_prepare` continues when breakdown.todos is empty. |
| next-prepare.md has clear assessment instructions | ⚠️ | Criteria incomplete and role conflict introduces ambiguity. |
| prime-orchestrator addition fits in one sentence | ✅ | Single-sentence prep flow present. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [comments] `~/.agents/commands/next-prepare.md:10` — The command says “You do NOT write or modify any files,” but the breakdown steps require creating new todos, updating roadmap/dependencies, and writing breakdown.md. This contradiction will stop the architect from executing the breakdown work in autonomous mode.
  - Suggested fix: Clarify that the breakdown assessment section authorizes file edits (or move those actions to orchestrator-only instructions and keep the architect purely advisory).
- [comments] `~/.agents/commands/next-prepare.md:38` — Definition of Ready criteria are incomplete (missing scope clarity and uncertainty level), so the assessment can skip required evaluation dimensions.
  - Suggested fix: Expand criteria to include all five Definition of Ready checks from requirements.
- [tests] `teleclaude/core/next_machine.py:984` — New breakdown branches (input.md assessment path and container detection) are not covered by tests; existing tests only cover generic HITL paths.
  - Suggested fix: Add unit tests that assert behavior for (1) input.md with unassessed breakdown, (2) assessed breakdown with todos producing container response, and (3) assessed breakdown with empty todos proceeding to requirements.

## Suggestions (nice to have)

- [comments] `~/.agents/commands/next-prepare.md:60` — Fix spelling (“wether” → “whether”) to keep prompts clean and professional.

## Strengths

- Breakdown state schema is integrated into default state without breaking existing state reads.
- `next_prepare` adds a clear container guard to prevent preparing parent todos after split.
- Orchestrator guidance keeps breakdown logic in next-prepare, consistent with single-responsibility.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Resolve the role conflict in `next-prepare.md` so breakdown steps can be executed.
2. Include full Definition of Ready criteria in the assessment prompt.
3. Add unit tests for breakdown-specific paths in `next_prepare`.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Role conflict in next-prepare.md | Clarified that file modifications are authorized DURING breakdown assessment, with explicit list of files that can be modified | N/A (file in global config) |
| Incomplete Definition of Ready criteria | Expanded criteria to include all 5: Single-Session Completability, Verifiability, Atomicity, Scope Clarity, and Uncertainty Level | N/A (file in global config) |
| Missing unit tests for breakdown paths | Added 9 comprehensive tests covering: input.md unassessed, container detection, empty todos proceeding, autonomous dispatch, and helper functions | ffd5e07 |
| Spelling error: wether → whether | Fixed during criteria expansion | N/A (file in global config) |

**Note:** The first two issues involve `~/.agents/commands/next-prepare.md` which is outside this repository (global user config). These changes have been applied to that file but cannot be committed in this worktree.
