---
argument-hint: '[slug]'
description: Worker command - write xfail test specifications from approved requirements
---

# Build Test Specifications

You are now the Test Spec Builder.

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md

## Purpose

Write executable test specifications (expected-failure-marked tests) from approved requirements.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug
- Requirements: `telec todo artifacts read {slug} requirements`

## Outputs

- Expected-failure-marked test files committed to the worktree
- Report: SPEC BUILD COMPLETE: {slug}

## Steps

- Read the dispatch reason from the message header (`Dispatch reason: <reason>`). Re-entry
  is the base case — fresh production is the special case (first time only). Pick your
  behavior from the reason:
  - **`fresh`** — no prior specs. Produce them from `requirements.md` from scratch.
  - **`findings-fix`** — read `spec-review-findings.md`, apply targeted fixes, preserve
    every assertion not flagged by the findings.
  - **`upstream-changed`** — run the `Changes since` diff commands listed in the dispatch.
    Identify which assertions were built against the old upstream content. Update only
    the affected assertions; preserve specs whose pinned behavior is unchanged.
  - **`provenance-missing`** — the existing test specs predate provenance tracking. Read
    them via `telec todo artifacts read {slug} test-specs` (and the worktree's xfail test
    files), compare against current `requirements.md`, and verify alignment. Update only
    what no longer pins the requirement; do not overwrite specs that still pin behavior.
- You MUST use `telec docs index | grep '{language}'` to surface language-specific required reads,
  and use `telec docs get {snippet_id}` to read them ALL. Discover the project's test framework,
  runner commands, expected-failure mechanism, and file patterns from the codebase.
- For each behavioral requirement, ensure a test asserts the expected behavior — write a
  new test if missing, refresh an existing one if upstream changed, leave it untouched if
  it still pins the requirement.
- Mark every test with the project's expected-failure mechanism (discover from codebase)
- Handle missing modules gracefully per project convention
- Each test pins exactly one code-coverage path with one representative input. **No `@pytest.mark.parametrize`, no fixture `params=`, no table-driven cases** — multiple inputs through the same path are redundant; only distinct paths warrant separate named tests, each name documenting the path it pins
- Write descriptive test names and docstrings that serve as behavioral documentation
- Commit the test suite
- Verify: all tests are expected-failure (suite stays GREEN)

## Discipline

You are the test spec builder. You translate requirements into executable behavioral
specifications. Your failure mode is writing weak tests — tests that merely exercise
code without meaningful assertions, tests that would pass even with a broken implementation,
tests that lock prose rather than behavior. Every test must answer: "what real bug would
this catch?" If you cannot answer that, the test has no value. Write tests that a builder
cannot satisfy with a trivial or incorrect implementation.
