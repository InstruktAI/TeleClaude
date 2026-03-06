---
argument-hint: '[slug]'
description: Worker command - draft implementation plan from approved requirements
---

# Prepare Plan Draft

You are now the Architect in plan drafting mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md

## Purpose

Produce `implementation-plan.md` and `demo.md` from approved requirements. Single-agent work.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/requirements.md` (approved)
- `todos/{slug}/input.md` (original intent)

## Outputs

- `todos/{slug}/implementation-plan.md` — review-aware, rationale-rich
- `todos/{slug}/demo.md` — draft demonstration plan
- `todos/{slug}/state.yaml` — grounding metadata with referenced paths

## Steps

- Follow the plan draft procedure.
