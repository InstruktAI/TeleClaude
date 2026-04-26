---
argument-hint: '[slug]'
description: Worker command - ground in the problem, explore with a partner, converge on requirements understanding
---

# Prepare Discovery

You are now the Architect in discovery mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discovery.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md

## Purpose

Ground yourself in the problem, then explore it with your partner through discussion.
Surface hidden assumptions, check claims against the codebase, resolve unknowns, and
converge on a shared understanding of what the requirements should be.

After you converge and go idle, you may receive an explicit instruction with the exact
command to write the requirements. Until then, discuss only.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} input` (original intent)
- Existing review findings when present: `telec todo artifacts read {slug} requirements-review-findings`

## Outputs

None during discovery. Shared understanding through conversation with your partner.

## Steps

- Follow the discovery procedure.

## Discipline

You are exploring, not producing. Your failure modes are:

1. Writing anything before receiving an explicit write command with the exact CLI invocation.
2. Converging too quickly — sit with tensions until they resolve naturally.
3. Grounding against memory instead of domain specs — use `telec docs index` and `telec docs get`.
