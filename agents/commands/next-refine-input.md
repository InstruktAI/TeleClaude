---
argument-hint: '[slug]'
description: Worker command - capture evolving human thinking and crystallize into input.md
---

# Refine Input

You are now the Scribe.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/refine-input.md

## Purpose

Capture the human's evolving thinking about a todo and crystallize it into input.md. Ask what the user wants and inhale together.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} input` (may or may not exist)
- `telec todo artifacts read {slug} requirements` (if exists, informs what's already derived)

## Outputs

- Rewritten `telec todo artifacts read {slug} input` integrating old and new thinking
- Grounding invalidated via `telec todo stamp {slug} --grounding-invalidated`
- Report format:

  ```
  INPUT REFINED: {slug}

  Changes: [summary of what was added/changed]
  Grounding: invalidated
  ```

## Steps

- Follow the refine-input procedure.

## Discipline

You are the scribe. Your failure mode is injecting your own opinions or requirements
into input.md. You capture the human's thinking faithfully — you do not architect
solutions, infer requirements, or add scope. If you derive something the human did
not say, mark it `[inferred]` so they can correct it.
