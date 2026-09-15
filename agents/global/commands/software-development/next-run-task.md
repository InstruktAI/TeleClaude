---
argument-hint: '[slug]'
description: Worker command - execute an authorized task-plan, resolve the firing, and rest according to its outcome
---

# Run Task

You are now the Task runner.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/task/run-task.md

## Purpose

Execute the authorized `task-plan`, record continuity in the `log`, and stamp the
firing's outcome.

<!-- @include: ~/.teleclaude/docs/snippets/slug-resolution-target.md -->

## Steps

Complete the procedure above.

## Discipline

Follow the Run Task procedure's discipline. Read the `log`, execute only the
approved plan, record what happened, and stamp the outcome. A `success` firing
ends the session — a one-shot delivers the todo, a recurring firing records it
and rests until its next due instant. An `error` firing stays alive as the
human-inspection beacon; never self-end while an error is unresolved.
