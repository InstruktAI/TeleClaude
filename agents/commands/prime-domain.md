---
argument-hint: '[domain]'
description: Load the platform's process-enforcement baseline for the named domain before producing or reviewing artifacts evaluated under platform policy.
---

# Prime Domain

You are now the Domain Primer.

## Purpose

Load the platform's process-enforcement baseline for the named domain into the active session's context, so subsequent decisions cite platform policy.

## Inputs

- `domain` argument: one of `software-development`, `creative`.

## Outputs

- The full text of the matching deployed baseline file is read into context.

## Steps

1. Resolve the `domain` argument to its deployed baseline path:
   - `software-development` → `~/.teleclaude/docs/software-development/baseline.md`
   - `creative` → `~/.teleclaude/docs/creative/baseline.md`
2. Read the file in full.
3. Treat its contents as mandatory context for the rest of the session.

## Discipline

Read the file in full, not in part. The file is the inflated concatenation of every baseline snippet for the domain and is sized to be read once at entry. Partial reads leave platform policies unloaded.
