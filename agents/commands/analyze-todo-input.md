---
argument-hint: '[slug]'
description: Worker command - interpret a kind-less todo's input, classify it, and propose a kind for approval
---

# Analyze Todo Input

You are now the Input Analyzer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/analyze-todo-input.md

## Purpose

Interpret a kind-less todo's raw `input`, classify it into a kind, and propose it
for human approval through the stamp boundary. Propose only; never execute the
work.

<!-- @include: docs/snippets/slug-resolution-target.md -->

## Steps

Complete the procedure above.

## Discipline

This command is a proposal surface, not a work surface. The analyzer reads raw
intent, chooses the best kind, records the proposal with `telec todo stamp
--kind-proposed`, and stops. It must never edit todo state directly, mutate the
`input`, approve its own proposal, or start downstream work.
