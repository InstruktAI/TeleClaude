---
argument-hint: '[slug]'
description: Worker command - derive requirements from input using solo or triangulated discovery
---

# Prepare Discovery

You are now the Architect in requirements discovery mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/maintenance/next-prepare-discovery.md

## Purpose

Produce `requirements.md` from `input.md`. Work solo when the input and codebase already
provide enough grounding. Bring in a complementary partner only when a second perspective
is needed to surface hidden assumptions, missing constraints, or unresolved tensions.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/input.md` (original intent)
- Existing `todos/{slug}/requirements-review-findings.md` when present

## Outputs

- `todos/{slug}/requirements.md` — grounded, review-aware requirements
- `todos/{slug}/state.yaml` — updated grounding metadata if touched during discovery

## Steps

- Follow the discovery procedure.
