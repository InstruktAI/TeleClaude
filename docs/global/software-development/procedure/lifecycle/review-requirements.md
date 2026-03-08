---
id: 'software-development/procedure/lifecycle/review-requirements'
type: 'procedure'
scope: 'domain'
description: 'Requirements review phase. Validate requirements.md against quality standard and write verdict to state.yaml.'
---

# Review Requirements — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md

## Goal

Validate `requirements.md` against the requirements quality standard and write a binary verdict to `state.yaml`. This is a preparation review, not a code review.

## Preconditions

- `todos/{slug}/requirements.md` exists.
- `todos/{slug}/input.md` exists (the source the requirements were derived from).

## Steps

### 1. Read context

- `todos/{slug}/requirements.md` — the artifact under review.
- `todos/{slug}/input.md` — the original human thinking.
- `todos/roadmap.yaml` — the slug's description.
- Relevant codebase files referenced in the requirements.

### 2. Validate against quality standard

Check each criterion. Every failure is a finding.

#### Completeness

Every intent expressed in `input.md` is captured as a concrete requirement or
explicitly deferred with justification. No silent gaps where the human said
something and the requirements ignored it.

#### Testability

Each requirement has a verification path: a test, observable behavior, or
measurable outcome. Reject "works correctly," "is fast," "handles edge cases"
without specifics. Each requirement must answer: "how does the builder prove
this is done?"

#### Grounding

Requirements reference codebase patterns, existing APIs, or documented
conventions — not invented abstractions. If the codebase has an established
way to do X, the requirement says "using the existing X pattern." Requirements
that prescribe approaches contradicting codebase patterns are findings.

#### Review-awareness

Requirements anticipate what the code reviewer will check:
- If a requirement implies CLI changes: help text and config surface updates stated.
- If it implies new behavior: test expectations stated.
- If it touches security boundaries: validation and auth expectations stated.
- If it touches documentation: doc update expectations stated.

Missing review-awareness is a finding — it means the builder will miss it and
the reviewer will catch it too late.

#### No implementation leakage

Requirements state what and why, never how. If a requirement prescribes a
specific implementation approach, it belongs in the implementation plan, not
here. Exception: constraints like "must use the existing adapter pattern"
are requirements because they constrain the solution space.

#### Inference transparency

Anything inferred from codebase or documentation rather than explicitly stated
in `input.md` is marked `[inferred]`. If inferences are unmarked, the human
cannot distinguish what they said from what the system assumed.

### 3. Auto-remediate localized findings

Default behavior is to act in place. If a finding is localized, high-confidence,
and does not alter human intent, the reviewer should fix `requirements.md`
directly in this same pass instead of handing it back.

Typical in-place fixes include:

- Adding missing `[inferred]` markers.
- Tightening vague verification wording.
- Filling explicit review-awareness omissions (tests/docs/config mentions).

Do not auto-remediate when the change would invent new intent, settle unresolved
product decisions, or introduce an architectural choice that was not grounded.
Leave those findings unresolved and route via `needs_work`.

### 4. Write verdict

Update `todos/{slug}/state.yaml`:

```yaml
requirements_review:
  verdict: "approve" | "needs_work"
  reviewed_at: "<now ISO8601>"
  findings_count: <n>
```

Verdict rules:

- `approve` only when unresolved Critical and unresolved Important findings are both zero.
- `needs_work` when any unresolved Critical or Important finding remains.
- Suggestion findings may remain unresolved under `approve`.

If unresolved findings exist, write them to
`todos/{slug}/requirements-review-findings.md` with severity levels
(Critical, Important, Suggestion) following the same format as code review findings.

If no unresolved findings remain, remove stale `requirements-review-findings.md`
if present.

### 5. Commit and report

Commit the verdict and any findings. Report:

```
REQUIREMENTS REVIEW: {slug}

Verdict: [APPROVE | NEEDS WORK]
Findings: {count}
```

## Outputs

- Verdict in `todos/{slug}/state.yaml`.
- `todos/{slug}/requirements-review-findings.md` if findings exist.
- Commit containing review artifacts.

## Recovery

- If unresolved Critical or Important findings remain after auto-remediation,
  mark `needs_work` with specific gaps listed.
- If requirements are missing critical context or intent is ambiguous, do not
  invent intent; mark `needs_work`.
