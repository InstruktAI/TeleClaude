---
argument-hint: '[optional focus or slug]'
description: Prime command - bootstrap orchestrator context from creative and software development lifecycles
---

# Prime Orchestrator

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/creative/procedure/lifecycle/overview.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md

## Purpose

Prime the orchestrator with full lifecycle awareness. The complete progression is:
create (optional) → prepare → work → integrate.

After priming, stay in the current session and load the appropriate command as an
inline skill when directed:

- `/next-create` for creative work (design spec, art, visuals)
- `/next-prepare` for preparation (requirements, planning, readiness)
- `/next-work` for implementation (build, review, fix, finalize)

## Inputs

- Optional focus: "$ARGUMENTS" (slug, phase, or objective)

## Outputs

- Primed orchestration context
- Loaded inline command when directed by the user

## Steps

1. Read all required snippets before any decision.
2. If a focus/slug is provided, inspect current todo/roadmap state and determine which lifecycle stage applies.
3. If no focus is provided, summarize available work and wait for user direction.
4. When the user indicates what they want, load the appropriate command inline.

## Discipline

You are the orchestrator bootstrapping context. Read, orient, and load the right
command when directed. Do not dispatch workers from this command.
