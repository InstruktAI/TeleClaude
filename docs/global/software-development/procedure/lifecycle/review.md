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

### Paradigm-Fit Assessment (Required Lane)

Every review must include a paradigm-fit assessment that checks whether the implementation follows the existing codebase paradigms:

1. **Data flow**: Does the implementation use the established data layer (API, models, state management), or does it bypass it with inline hacks (direct filesystem access, hardcoded paths, ad-hoc parsing)?
2. **Component reuse**: Does the implementation reuse and parameterize existing components, or does it copy-paste them with minimal changes?
3. **Pattern consistency**: Does the implementation follow the patterns established by adjacent code (message passing, widget composition, naming conventions)?

Paradigm violations are **Important** findings at minimum. A copy-paste of an existing component that should have been parameterized is an Important finding. An inline filesystem hack that bypasses the data layer is a Critical finding.

### Zero-Finding Justification

If a review produces 0 Important or higher findings across all lanes, the reviewer must include a "Why No Issues" section in `review-findings.md` with:

1. Specific evidence of paradigm-fit verification (which patterns were checked).
2. Specific evidence that requirements were met (which requirements were validated and how).
3. Explicit statement that copy-paste duplication was checked and none found (or justified).

A review with 0 findings and no justification section is incomplete and will be rejected by the orchestrator.

### Manual Verification Evidence

For deliveries that include user-facing changes (UI, CLI output, interactive behavior), the reviewer must document verification evidence:

1. What was tested manually (or what could not be tested and why).
2. Observable behavior that confirms the requirement is met.
3. Any UI elements that should be visible but were not checked.

If manual verification is not possible in the review environment, the reviewer must explicitly note this gap as a finding.

## Preconditions

- `todos/{slug}/requirements.md` exists.
- `todos/{slug}/implementation-plan.md` exists.
- `todos/{slug}/quality-checklist.md` exists and includes Build/Review sections.
- Build phase completed for the slug.

## Steps

1. If no slug provided, select the first item with phase `active` in `state.yaml` that lacks `review-findings.md`.
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
5. Update only the Review section in `quality-checklist.md`.
   - Do not edit Build or Finalize sections.
6. Run review lanes in parallel where possible:

   ```bash
   git diff $(git merge-base HEAD main)..HEAD --name-only
   git diff $(git merge-base HEAD main)..HEAD
   ```

7. Validate deferrals:
   - If `deferrals.md` exists, confirm each deferral is justified.
   - If unjustified, add a finding and set verdict to REQUEST CHANGES.
8. Ensure all implementation-plan tasks are checked; otherwise, add a finding and set verdict to REQUEST CHANGES.
9. Validate Build section in `quality-checklist.md` is fully checked.
   - If not, add a finding and set verdict to REQUEST CHANGES.
10. Update only the Review section in `quality-checklist.md`.
    - Do not edit Build or Finalize sections.
11. Run review lanes in parallel where possible:

    | Aspect   | When to use              | Skill                      | Task                                               |
    | -------- | ------------------------ | -------------------------- | -------------------------------------------------- |
    | code     | Always                   | next-code-reviewer         | Find bugs and pattern violations                   |
    | tests    | Test files changed       | next-test-analyzer         | Evaluate coverage and quality                      |
    | errors   | Error handling changed   | next-silent-failure-hunter | Find silent failures                               |
    | types    | Types added/modified     | next-type-design-analyzer  | Validate type design                               |
    | comments | Comments/docs added      | next-comment-analyzer      | Check accuracy                                     |
    | logging  | Logging changed or noisy | next-code-reviewer         | Enforce logging policy; reject ad-hoc debug probes |
    | simplify | After other reviews pass | next-code-simplifier       | Simplify without behavior changes                  |

12. Logging hygiene check (required):
    - Reject temporary debug probes (e.g., `print("DEBUG: ...")`, one-off file/line probes).
    - Require structured logger usage per logging policy.
    - Escalate violations as at least Important findings.
13. Test quality hygiene check (required):

- Reject tests that lock narrative documentation wording or style.
- Allow exact-string assertions only for execution-significant tokens/contracts.
- Prefer behavior/structure assertions (parsed outputs, references, idempotence, emitted actions).

11. Write findings to `todos/{slug}/review-findings.md`.
12. Set `todos/{slug}/state.yaml` field `review` to `approved` or `changes_requested`.
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
- Updated `todos/{slug}/state.yaml` with review status.
- A commit containing the review findings.

## Recovery

- If review cannot be completed, report the blocker with context and stop.
