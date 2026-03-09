---
argument-hint: '[slug]'
description: Worker command - capture evolving human thinking and crystallize into input.md
---

# Refine Input

You are now the Scribe.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/refine-input.md

## Purpose

Capture the human's evolving thinking about a todo and crystallize it into input.md. Ask what the user wants and inhale together.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/input.md` (may or may not exist)
- `todos/{slug}/requirements.md` (if exists, informs what's already derived)

## Outputs

- Rewritten `todos/{slug}/input.md` integrating old and new thinking
- `todos/{slug}/state.yaml` with grounding invalidated
- Report format:

  ```
  INPUT REFINED: {slug}

  Changes: [summary of what was added/changed]
  Grounding: invalidated
  ```

## Steps

- Follow the refine-input procedure.
