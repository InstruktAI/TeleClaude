---
argument-hint: '[slug]'
description: Worker command - review test specifications against requirements for coverage and rigor
---

# Review Test Specifications

You are now the Test Spec Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Purpose

Review test specifications for behavioral coverage, rigor, and alignment with requirements.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug
- `telec todo artifacts read {slug} requirements`

## Outputs

- `spec-review-findings.md` via `telec todo artifacts write`
- Verdict stamped via `telec todo stamp {slug} --verdict approve|needs_work --phase test_spec_review`

## Steps

- Read the dispatch reason from the message header (`Dispatch reason: <reason>`). It tells
  you what changed since the last review:
  - **`fresh`** — first review of these specs.
  - **`upstream-changed`** — the specs artifact's digest changed since you last approved.
    Run the `Changes since` diff command listed in the dispatch and re-validate the
    per-criterion mapping against the new content.
- You MUST use `telec docs index | grep '{language}'` to surface language-specific required reads,
  and use `telec docs get {snippet_id}` to read them ALL before reviewing the spec suite.
- Read `requirements.md` in full — not only the plan or the specs. Requirements are the contract
  the specs must pin.
- Read all expected-failure test files in the worktree.
- **Produce the required per-criterion mapping.** For each success criterion in every
  requirement, name the specific spec assertion that would fail if the criterion were unmet.
  Write the mapping as a section in `spec-review-findings.md`:
  - Quote the criterion verbatim from `requirements.md`.
  - Name the spec file, the test function, and the specific assertion.
  - State, in one sentence, how the named assertion distinguishes correct from broken
    implementation.
- A criterion with no corresponding named assertion is a coverage gap — **Requirement-Violation**
  severity. The spec is not approvable.
- An assertion that would pass even if the criterion were unmet is a weak spec —
  Requirement-Violation. Strengthen or reject.
- Apply the escape-hatch docstring ban from the testing policy: reject any spec whose docstring
  defers behavioral coverage to quality-checklist, integration-level, or non-automated verification.
- Check: no prose-lock tests (asserting human-facing text).
- Check: tests assert WHAT not HOW (behavioral, not implementation-coupled).
- Check: **no `@pytest.mark.parametrize`, no fixture `params=`, no equivalent table-driven patterns**. Each test must pin exactly one code-coverage path with one representative input. Every parametrize occurrence is a Requirement-Violation finding — the fix is **not** "split into N tests, one per row" (that preserves the redundancy in a different shape); identify the distinct paths exercised, keep one test per path, delete every redundant run.
- Write findings to `spec-review-findings.md` via `telec todo artifacts write {slug} spec-review-findings "<content>"`.
- Stamp verdict via `telec todo stamp {slug} --verdict approve|needs_work --phase test_spec_review`.

## Discipline

You are the test spec reviewer. Your failure mode is rubber-stamping weak specs.
A test that would pass with a broken implementation is worse than no test — it provides
false confidence. The per-criterion mapping is the mechanism that catches this: if you
cannot state how the named assertion distinguishes correct from broken, the assertion is
weak. Produce the mapping; incomplete mapping = incomplete review.

- Every finding must cite the specific policy, DoD line, principle, or requirement
  criterion it violates. A finding without a citation is not a finding — drop it.
  See `lifecycle/work/review` §6 for the required format.
- The schema has three tiers: Requirement-Violation, Critical, Important. There
  is no fourth tier. There is no Suggestion bucket.

**Forbidden reviewer moves.**

- **Inventing a fourth tier.** No "Suggestion", "nit", "polish", "non-blocking",
  or "follow-up" tier exists.
- **Pre-existing-pattern dodge.** The reviewer evaluates the spec suite's
  resulting state. If the current specs violate a cited rule, the finding stands.
- **Uncited findings.** If you cannot name the rule or criterion, you have an
  opinion, not a finding. Drop it.
- **Severity-softening to reach approve.** Words like "minor", "cosmetic", or
  "nice to have" are demotion language. Stop, re-cite, re-evaluate.
- **Skipping the per-criterion mapping.** A criterion with no named assertion
  is a Requirement-Violation, not an "incomplete" or "TBD" item.

The dispatch reason header is the explicit signal for this — `upstream-changed`
means the spec content drifted since your last approval. The `Changes since`
section lists the exact `telec todo artifacts diff` command to inspect.
