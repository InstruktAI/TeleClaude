---
id: 'software-development/procedure/lifecycle/prepare/review-requirements'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Requirements review phase. Validate the human-approved requirements artifact against the quality standard and stamp the review verdict.'
---

# Review Requirements — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Validate the human-approved `requirements` artifact against the requirements
quality standard and stamp a binary verdict. This is a preparation review of
artifact craftsmanship — not a code review and not a scope review.

## Preconditions

- `telec todo artifacts read {slug} requirements` exists and has been human-approved.

**Source of intent.** The human-approved `requirements` artifact is the sole
source of intent for this review. Do not read `input`. Do not reference
`input` in findings. The `input` artifact is a jumping-off pad for the human
at the start of a todo; once requirements are human-approved, `input` is
discarded as a source of intent. The human's approval at the requirements
digest you are reviewing is the contract. If you believe scope is wrong,
that is a `needs_decision` for the human — not a citation against `input`.

## Steps

### 1. Read context

- `telec todo show {slug}`.
- `telec todo artifacts read {slug} requirements`.
- Relevant codebase files referenced in the requirements.
- Apply the domain-context loading rule from the preparation artifact quality
  policy: identify which specs the requirements touch and load them before
  validation begins.

### 2. Validate against quality standard

Check each criterion from the preparation artifact quality policy. Every
failure is a finding.

#### Testability

Each requirement must have verification criteria that are concrete enough
for a reader to produce, per criterion, the following translation:

> "A test asserting X would fail if this criterion were unmet."

The reviewer performs this translation for every success criterion as a
required step and records the translations in the requirements-review
findings. A criterion that cannot be translated into a named failing test
in this form is not testable — mark `needs_work` with a rewrite request.
Reject vague criteria ("works correctly," "is fast," "handles edge cases")
by writing the specific failing-test form they would need.

The translation is a reviewer output, not a mental check. A review without
the per-criterion translations is incomplete.

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

Anything inferred from codebase, documentation, or grounding — rather than
stated directly in the requirements text — is marked `[inferred]`. The
reviewer checks marker presence against the `requirements` artifact itself.
If inferences are unmarked, a future reader cannot distinguish stated intent
from system-derived elaboration.

### 3. Auto-remediate localized findings

Default behavior is to act in place. If a finding is localized, high-confidence,
and does not alter approved intent, the reviewer should fix `requirements`
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
- Inventing new intent not present in the approved `requirements`.
- Settling unresolved product decisions.
- Introducing architectural choices that were not grounded.

The boundary: auto-remediation fixes what exists. It does not expand what
the requirements cover.

### 4. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase requirements_review
# or
telec todo stamp {slug} --verdict needs_work --phase requirements_review
```

Verdict rules:

- `approve` only when unresolved Critical and unresolved Important findings are both zero.
- `needs_work` when any unresolved Critical or Important finding remains.

If unresolved findings exist, write them via
`telec todo artifacts write {slug} requirements-review-findings <content>` with severity levels
(Critical, Important) following the same format as code review findings, including
the policy citation requirement defined in `lifecycle/work/review` §6.

If no unresolved findings remain, do not write a new findings artifact.

### 5. Commit and report

Commit all files in the worktree. Report:

```
REQUIREMENTS REVIEW: {slug}

Verdict: [APPROVE | NEEDS WORK]
Findings artifact: requirements-review-findings when NEEDS WORK
```

## Outputs

- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} requirements-review-findings` if findings exist.
- Commit containing review artifacts.

## Recovery

- If unresolved Critical or Important findings remain after auto-remediation,
  mark `needs_work` with specific gaps listed.
- If a requirement is ambiguous, mark `needs_work` — do not invent intent and
  do not consult `input` to disambiguate.
