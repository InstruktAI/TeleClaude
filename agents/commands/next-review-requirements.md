---
argument-hint: '[slug]'
description: Worker command - review requirements.md against quality standard and write verdict
---

# Review Requirements

You are now the Architect in requirements review mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/review-requirements.md

## Purpose

Validate `requirements.md` against the requirements quality standard and write a binary verdict to `state.yaml`.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/requirements.md` (the artifact under review)
- `todos/{slug}/input.md` (the source it was derived from)

## Outputs

- Verdict in `todos/{slug}/state.yaml`
- `todos/{slug}/requirements-review-findings.md` if findings exist
- All review artifacts committed to git

## Steps

- Follow the review-requirements procedure.
- Commit all changes. Go idle.
