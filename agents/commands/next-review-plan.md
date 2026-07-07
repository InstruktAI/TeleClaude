---
argument-hint: '[slug]'
description: Worker command - review implementation plan against policies, DoD gates, and review lanes
---

# Review Plan

You are now the Architect in plan review mode.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/review-plan.md

## Purpose

Validate `implementation-plan.md` against policies, Definition of Done gates, and review lane expectations. Stamp a binary verdict via `telec todo stamp {slug} --verdict approve|needs_work --phase plan_review`.

<!-- @include: ~/.teleclaude/docs/snippets/slug-resolution-target.md -->

## Steps

Complete the procedure above.

## Discipline

The reservation lane is easy to skip because it has no artifact of its own: before
stamping a verdict, run `uv run python tools/lint/binding_reservation.py --slug
{slug} --binding <spec_id>:<scenario_id>` for every scenario the plan declares it
will bind. A binding already reserved by a different in-flight slug is a
Requirement-Violation under the Test coverage lane (`definition-of-done-lanes`) —
do not approve past it.
