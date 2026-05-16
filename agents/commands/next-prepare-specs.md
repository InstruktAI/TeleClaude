---
argument-hint: '[slug]'
description: Worker command - write prose test specifications from approved prepare artifacts
---

# Prepare Test Specifications

You are now the Test Spec Author.

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/prepare-specs.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
- @docs/_snippets/slug-resolution.md

## Purpose

Write a language-agnostic prose `test-specs` artifact from approved PRD and optional approved architecture.

## Inputs

- Slug: "$ARGUMENTS"
- Approved `prd` artifact
- Approved `architecture` artifact when present and not skipped
- Existing `spec-review-findings` when present

## Outputs

- `test-specs` via `telec todo artifacts write {slug} test-specs <content>`

## Steps

Follow the prepare-specs procedure.

## Discipline

Follow the prepare-specs procedure's discipline.
