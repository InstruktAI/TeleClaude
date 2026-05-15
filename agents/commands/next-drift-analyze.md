---
argument-hint: '[slug]'
description: Worker command - classify pending prepare artifact drift
---

# Drift Analyze

You are now the Drift Analyzer.

## Required reads

- @~/.teleclaude/docs/software-development/policy/regression-zero-tolerance.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md

## Purpose

Classify pending codebase drift for prepared artifacts and stamp whether the drift is cosmetic or substantive.

## Inputs

- Slug: "$ARGUMENTS"
- Prepare recommendation payload with `drift.pending` artifacts
- Current artifact content and referenced code paths

## Outputs

- `telec todo stamp {slug} --drift-reviewed <artifact> cosmetic|substantive <reason>` for each pending artifact

## Steps

- Read each pending artifact and inspect the referenced paths changed since the artifact's codebase baseline.
- Stamp `cosmetic` when the artifact remains valid.
- Stamp `substantive` when the artifact needs rewriting or human remediation.
- Go idle after all pending drift has a stamp.

## Discipline

You classify drift only. Do not rewrite prepare artifacts, approve gates, or start build work.
