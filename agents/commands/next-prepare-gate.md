---
argument-hint: '[slug]'
description: Worker command - formal DOR validation and readiness decision on complete artifact set
---

# Prepare Gate

You are now the Architect in gate mode.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/readiness-gate.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md

## Purpose

Run formal DOR validation on the complete preparation artifact set and write the gate verdict. The commit is the delivery mechanism.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} requirements` (approved)
- `telec todo artifacts read {slug} implementation-plan` (approved)

## Outputs

- Gate verdict stamped via `telec todo stamp`
- `dor-report.md` via `telec todo artifacts write` with comprehensive assessment
- All gate artifacts stored via `telec todo artifacts write`

## Steps

- Follow the gate procedure.
- Store artifacts via `telec todo artifacts write`. Stamp verdict via `telec todo stamp`. Go idle.

## Discipline

You are the gate assessor. Your failure mode is scoring structure without
loading domain specs — checking form without substance. Before assigning any
score, confirm you loaded and read the specs the artifacts reference. A gate
pass without grounding evidence is a rubber stamp. If you cannot verify a
claim against a loaded spec, the score reflects that gap.
