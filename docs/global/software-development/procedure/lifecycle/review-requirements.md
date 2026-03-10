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

### 1b. Load domain-specific specs

Before validation begins, identify which domain specs the requirements touch
and load them. This is mandatory — grounding cannot be verified without the
ground truth.

- Read the requirements and identify the domains they affect (documentation
  system, CLI surface, config surface, messaging, session infrastructure, etc.).
- Run `telec docs index` and load the relevant specs via `telec docs get`.
- Examples: requirements about doc snippets → load the snippet authoring schema.
  Requirements about CLI changes → load the CLI surface spec. Requirements
  about config → load the teleclaude-config spec.

The reviewer must have the domain specs loaded before evaluating grounding,
implementation leakage, or review-awareness. Without them, the review validates
structure but not substance.

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

Verify grounding against the domain specs loaded in step 1b, not against
general knowledge. If a requirement references a taxonomy, schema, config
surface, or API — confirm it matches the actual spec.

#### Review-awareness

Requirements anticipate what the code reviewer will check. Use the Definition
of Done gates as the systematic checklist:

- Walk each DoD section (functionality, code quality, testing, linting,
  security, documentation, commit hygiene, observability).
- For each requirement, identify which DoD gates it triggers.
- Verify those implications are reflected in the requirements — either as
  explicit success criteria or as constraints.

Common gaps to check:
- Requirement implies CLI changes → help text and config surface updates stated.
- Requirement implies new behavior → test expectations stated.
- Requirement implies new config → config wizard, sample, and spec updates stated.
- Requirement implies security boundaries → validation and auth expectations stated.
- Requirement implies documentation changes → doc update expectations stated.
- Requirement implies user-visible behavior → demo coverage stated.

Missing review-awareness is a finding — it means the builder will miss it and
the reviewer will catch it too late.

#### No implementation leakage

Requirements state what and why, never how. If a requirement prescribes a
specific implementation approach, it belongs in the implementation plan, not
here.

Concrete signals of leakage — flag these as findings:
- Enumerating specific directory paths, file names, or file locations.
- Naming specific config field names, YAML keys, or database columns.
- Prescribing specific function signatures, class names, or module structure.
- Specifying counts, minimums, or thresholds that aren't user-facing.
- Listing specific taxonomy types, schema fields, or internal identifiers
  when the requirement could instead reference the governing spec.

Exception: constraints that narrow the solution space are requirements, not
leakage. "Must use the existing adapter pattern" constrains. "Must conform
to the snippet authoring schema" constrains. "Place files under
`docs/project/design/`" prescribes.

The test: could the builder satisfy the requirement using a different
implementation approach? If the requirement forecloses valid alternatives
without justification, it's leakage.

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
