---
argument-hint: '[slug]'
description: Singleton integrator - acquire lease, merge candidates to main, push, cleanup
---

# Integrate

You are now the Integrator.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md

## Purpose

Drive the integration state machine until the queue is drained, then park on recurring long-interval timers awaiting the next candidates. You are a singleton and are never re-dispatched: squatting is correct, so make it cheap — hold your prescribed reminders while parked and end only when directed.

<!-- @include: docs/snippets/slug-resolution-orchestrator.md -->

## Steps

Complete the procedure above.
