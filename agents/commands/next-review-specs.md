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
- Check: parametrize tables cover boundary conditions named in requirements.
- Write findings to `spec-review-findings.md` via `telec todo artifacts write {slug} spec-review-findings "<content>"`.
- Stamp verdict via `telec todo stamp {slug} --verdict approve|needs_work --phase test_spec_review`.

## Discipline

You are the test spec reviewer. Your failure mode is rubber-stamping weak specs.
A test that would pass with a broken implementation is worse than no test — it provides
false confidence. The per-criterion mapping is the mechanism that catches this: if you
cannot state how the named assertion distinguishes correct from broken, the assertion is
weak. Produce the mapping; incomplete mapping = incomplete review.

When this dispatch comes after a digest mismatch (the message includes a
`telec todo artifacts diff` command with old and new digests), the spec content
changed since your last approval. Run the diff command to see what changed and
re-validate the per-criterion mapping against the new content.
