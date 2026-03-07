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

### 3. Write verdict

Update `todos/{slug}/state.yaml`:

```yaml
requirements_review:
  verdict: "approve" | "needs_work"
  reviewed_at: "<now ISO8601>"
  findings_count: <n>
```

If findings exist, write them to `todos/{slug}/requirements-review-findings.md`
with severity levels (Critical, Important, Suggestion) following the same format
as code review findings.

### 4. Commit and report

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

- If requirements are missing critical context, mark `needs_work` with specific
  gaps listed. Do not attempt to fill the gaps — that is the triangulation team's job.
