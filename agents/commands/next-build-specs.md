---
argument-hint: '[slug]'
description: Worker command - translate prose test specifications into executable tests
---

# Build Test Specifications

You are now the Test Spec Builder.

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/build.md
- @~/.teleclaude/docs/_snippets/slug-resolution.md

## Purpose

Translate approved prose `test-specs` into language-appropriate executable tests
inside the worktree, then make those tests pass.

## Inputs

- Slug: "$ARGUMENTS"
  [OPTIONAL: only when slug was provided]:
- Approved `test-specs` artifact
- Approved `implementation-plan` artifact

## Outputs

- Executable tests in the repository's test framework
- Code fixes needed to make the translated tests pass

## Steps

- Follow the build procedure.
- Read the prose test specs and implementation plan.
- Add the smallest executable tests that cover the specified behavior.
- Run the targeted tests and fix implementation gaps required by those tests.
- Commit the resulting worktree changes through the normal build flow.

## Discipline

You are in the worktree. Translate specs into real test coverage and keep the
scope to behavior already approved in prepare.
