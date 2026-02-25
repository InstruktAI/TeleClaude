---
argument-hint: '[slug]'
description: Prepare router command - choose draft or gate explicitly
---

# Prepare

You are now the Prepare router.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## Purpose

This command is only a router. Choose exactly one mode and execute only that mode.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

One of or both SEQUENTIAL dispatch choice(s):

1. `/next-prepare-draft`: run inline yourself and gain awareness for the next step, which needs delegation.
2. `/next-prepare-gate`: MUST be delegated to a NEW worker session. Use EXACTLY THIS COMMAND: `run_agent_command(command="next-prepare-gate", args="<slug>")`. The router session MUST NOT execute gate.

Never dispatch draft and gate in the same worker turn.

## Steps

1. Inspect todo state.
2. If artifacts are missing or weak, run `/next-prepare-draft`, and continue to step 4.
3. If upon startup artifacts exist and need formal DOR validation, dispatch gate to a new worker session (do not run gate inline in router session).
4. If YOU just ran `/next-prepare-draft`, then dispatch gate using `run_agent_command(command="next-prepare-gate", args="<slug>")`.
