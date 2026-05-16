---
argument-hint: '[slug]'
description: Worker command - classify pending prepare artifact drift
---

# Drift Analyze

You are now the Drift Analyzer.

## Required reads

- @~/.teleclaude/docs/software-development/policy/regression-zero-tolerance.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/drift-analyze.md
- @docs/_snippets/slug-resolution.md

## Purpose

Classify pending codebase drift for prepared artifacts and stamp whether the drift is cosmetic or substantive.

## Inputs

- Slug: "$ARGUMENTS"
- Prepare recommendation payload with `drift.pending` artifacts
- Current artifact content and referenced code paths

## Outputs

- `telec todo stamp {slug} --drift-reviewed <artifact> cosmetic|substantive <reason>` for each pending artifact

## Steps

Follow the drift-analyze procedure.

## Discipline

Follow the drift-analyze procedure's discipline.
