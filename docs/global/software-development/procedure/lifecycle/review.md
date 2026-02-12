---
description: 'Review phase. Verify requirements, code quality, tests, and deliver verdict with findings.'
id: 'software-development/procedure/lifecycle/review'
scope: 'domain'
type: 'procedure'
---

# Review — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/linting-requirements.md

## Goal

Verify the implementation against requirements and standards, and deliver a binary verdict with structured findings.

## Preconditions

- `todos/{slug}/requirements.md` exists.
- `todos/{slug}/implementation-plan.md` exists.
- `todos/{slug}/quality-checklist.md` exists and includes Build/Review sections.
- Build phase completed for the slug.

## Steps

1. If no slug provided, select the first `[>]` item in `todos/roadmap.md` that lacks `review-findings.md`.
2. Read:
   - `todos/{slug}/requirements.md`
   - `todos/{slug}/implementation-plan.md`
   - `README.md`, `AGENTS.md`, and `docs/*` for project patterns
3. Use merge-base to focus review scope:

   ```bash
   git diff $(git merge-base HEAD main)..HEAD --name-only
   git diff $(git merge-base HEAD main)..HEAD
   ```

4. Validate deferrals:
   - If `deferrals.md` exists, confirm each deferral is justified.
   - If unjustified, add a finding and set verdict to REQUEST CHANGES.
5. Ensure all implementation-plan tasks are checked; otherwise, add a finding and set verdict to REQUEST CHANGES.
6. Validate Build section in `quality-checklist.md` is fully checked.
   - If not, add a finding and set verdict to REQUEST CHANGES.
7. Update only the Review section in `quality-checklist.md`.
   - Do not edit Build or Finalize sections.
8. Run review lanes in parallel where possible:

   | Aspect   | When to use              | Skill                      | Task                                               |
   | -------- | ------------------------ | -------------------------- | -------------------------------------------------- |
   | code     | Always                   | next-code-reviewer         | Find bugs and pattern violations                   |
   | tests    | Test files changed       | next-test-analyzer         | Evaluate coverage and quality                      |
   | errors   | Error handling changed   | next-silent-failure-hunter | Find silent failures                               |
   | types    | Types added/modified     | next-type-design-analyzer  | Validate type design                               |
   | comments | Comments/docs added      | next-comment-analyzer      | Check accuracy                                     |
   | logging  | Logging changed or noisy | next-code-reviewer         | Enforce logging policy; reject ad-hoc debug probes |
   | simplify | After other reviews pass | next-code-simplifier       | Simplify without behavior changes                  |

9. Logging hygiene check (required):
   - Reject temporary debug probes (e.g., `print("DEBUG: ...")`, one-off file/line probes).
   - Require structured logger usage per logging policy.
   - Escalate violations as at least Important findings.
10. Test quality hygiene check (required):

- Reject tests that lock narrative documentation wording or style.
- Allow exact-string assertions only for execution-significant tokens/contracts.
- Prefer behavior/structure assertions (parsed outputs, references, idempotence, emitted actions).

11. Write findings to `todos/{slug}/review-findings.md`.
12. Set `todos/{slug}/state.json` field `review` to `approved` or `changes_requested`.
13. Commit the review findings.
14. Report summary and verdict to the caller.

## Report format

```
REVIEW COMPLETE: {slug}

Critical:
- [Issue]

Important:
- [Issue]

Suggestions:
- [Issue]

Verdict: APPROVE | REQUEST CHANGES
```

## Outputs

- `todos/{slug}/review-findings.md` with structured severity sections.
- Updated `todos/{slug}/state.json` with review status.
- A commit containing the review findings.

## Recovery

- If review cannot be completed, report the blocker with context and stop.
