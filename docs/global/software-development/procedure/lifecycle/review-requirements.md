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

### 3. Classify findings by severity

Assign each finding a severity level before routing:

- **trivial** — localized, high-confidence fix with no intent change (e.g., adding a
  missing `[inferred]` marker, tightening vague verification wording). Auto-remediation
  allowed inline.
- **substantive** — scope or intent ambiguity the reviewer cannot resolve unilaterally
  (missing requirement, wrong constraint, missing verification path). Routes to
  `needs_work` — the discovery worker must address it.
- **architectural** — unresolved design decision or systemic contradiction requiring human
  input before the work can proceed. Routes to `needs_decision` and blocks the machine.

Record findings in `state.yaml` under `requirements_review.findings`:

```yaml
findings:
  - id: "req-01"
    severity: "substantive"   # trivial | substantive | architectural
    summary: "R3 missing verification path for edge case X"
    status: "open"            # open | resolved
    resolved_at: ""
```

The `findings` list in `state.yaml` is the authoritative record. The markdown file
`todos/{slug}/requirements-review-findings.md` is the human-readable reference — write it
when unresolved findings exist, remove it when all are resolved.

### 4. Auto-remediate trivial findings

Default behavior is to act in place for **trivial** findings only. If a finding is
localized, high-confidence, and does not alter human intent, fix `requirements.md`
directly in this same pass and mark the finding `resolved`.

Allowed in-place fixes:

- Adding missing `[inferred]` markers.
- Tightening vague verification wording.
- Filling review-awareness gaps for implications already present in the
  requirements.
- Removing implementation leakage (replacing specific paths/fields/counts
  with references to governing specs).

Not allowed — assign `substantive` or `architectural` severity instead:

- Adding new scope items.
- Adding new success criteria.
- Adding new constraints.
- Inventing new intent not traceable to `input.md`.
- Settling unresolved product decisions.
- Introducing architectural choices that were not grounded.

The boundary: auto-remediation fixes what exists. It does not expand what
the requirements cover.

### 5. Write verdict

Update `todos/{slug}/state.yaml`:

```yaml
requirements_review:
  verdict: "approve" | "needs_work" | "needs_decision"
  reviewed_at: "<now ISO8601>"
  findings_count: <n>
  findings: [...]
```

Verdict rules (based on highest severity of unresolved findings):

- `approve` — all findings resolved (trivial findings auto-remediated, none remain open).
- `needs_work` — one or more `substantive` findings remain unresolved. The discovery
  worker will be re-dispatched to address them.
- `needs_decision` — one or more `architectural` findings remain unresolved. The machine
  sets `prepare_phase` to BLOCKED and notifies the human.

### 6. Commit and report

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

- If unresolved `substantive` findings remain after auto-remediation, mark `needs_work`
  with specific gaps listed. The machine re-dispatches the discovery worker.
- If unresolved `architectural` findings remain, mark `needs_decision`. The machine
  blocks and surfaces the decision to the human.
- If requirements are missing critical context or intent is ambiguous, do not
  invent intent; classify as `substantive` or `architectural` and route accordingly.
