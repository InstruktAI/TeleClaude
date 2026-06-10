---
argument-hint: '[slug]'
description: Worker command - interpret a kind-less todo's input, classify it, and assign a kind
---

# Analyze Todo Input

You are now the Input Analyzer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/analyze-todo-input.md

## Purpose

Interpret a kind-less todo's raw `input`, classify it into a kind, assign it
through the stamp boundary, and stop.

<!-- @include: docs/snippets/slug-resolution-target.md -->

## Steps

1. Resolve the target slug from `$ARGUMENTS`.
2. Read the todo's `input` artifact.
3. Classify the input as `feature`, `change`, `bug`, or `task`.
4. Run `telec todo stamp <slug> --kind-assign <kind> [content]`.
5. Stop without executing the todo's work.

## Discipline

This command is a route surface, not a work surface. The analyzer reads raw
intent, chooses the best kind, records the assignment with `telec todo stamp
--kind-assign`, and stops. It must never edit todo state directly, mutate the
`input`, or start downstream work.
