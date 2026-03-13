---
id: 'software-development/procedure/lifecycle/prepare/review-requirements'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Requirements review phase. Validate requirements.md against quality standard and write verdict to state.yaml.'
---

# Review Requirements — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

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
- Apply the domain-context loading rule from the preparation artifact quality
  policy: identify which specs the requirements touch and load them before
  validation begins.

### 2. Validate against quality standard

Check each criterion from the preparation artifact quality policy. Every
failure is a finding.

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

Apply the grounding rule from the preparation artifact quality policy. Verify
against the domain specs loaded in step 1, not against general knowledge.

#### Review-awareness

Apply the DoD-driven review-awareness rule from the preparation artifact
quality policy. Walk each DoD section and verify that the requirements
reflect the implications.

#### No implementation leakage

Apply the implementation leakage rule from the preparation artifact quality
policy. Use the concrete signals and discriminator test to identify leakage.

#### Inference transparency

Anything inferred from codebase or documentation rather than explicitly stated
in `input.md` is marked `[inferred]`. If inferences are unmarked, the human
cannot distinguish what they said from what the system assumed.

### 3. Auto-remediate localized findings

Default behavior is to act in place. If a finding is localized, high-confidence,
and does not alter human intent, the reviewer should fix `requirements.md`
directly in this same pass instead of handing it back.

Allowed in-place fixes:

- Adding missing `[inferred]` markers.
- Tightening vague verification wording.
- Filling review-awareness gaps for implications already present in the
  requirements.
- Removing implementation leakage (replacing specific paths/fields/counts
  with references to governing specs).

Not allowed — route via `needs_work` instead:

- Adding new scope items.
- Adding new success criteria.
- Adding new constraints.
- Inventing new intent not traceable to `input.md`.
- Settling unresolved product decisions.
- Introducing architectural choices that were not grounded.

The boundary: auto-remediation fixes what exists. It does not expand what
the requirements cover.

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
