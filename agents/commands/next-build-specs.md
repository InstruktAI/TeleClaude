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

## Language context

You MUST use `telec docs index | grep '{language}'` to surface language-specific required reads,
and use `telec docs get {snippet_id}` to read them ALL — they contain mandatory language idioms.
Discover the project's test framework, runner commands, expected-failure mechanism, and file patterns
from the codebase (package config, Makefile, existing tests).

## Purpose

Write executable test specifications (expected-failure-marked tests) from approved requirements.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug
- todos/{slug}/requirements.md

## Outputs

- Expected-failure-marked test files committed to the worktree
- Report: SPEC BUILD COMPLETE: {slug}

## Steps

- Load language-specific testing docs (see Language context above)
- Read requirements.md thoroughly
- For each behavioral requirement, write test(s) that assert the expected behavior
- Mark every test with the project's expected-failure mechanism (discover from codebase)
- Handle missing modules gracefully per project convention
- Use table-driven patterns for specification tables with multiple input/output cases
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
