---
id: 'project/spec/runtime-operations-truth'
type: 'spec'
scope: 'project'
description: 'Practical contract for documenting daemon background operations and their real user impact.'
---

# Runtime Operations Truth — Spec

## What it is

This file is here to answer one practical question during incidents:

"Which background thing is broken, and what should I check first?"

It is not an architecture overview.
It is an operator cheat sheet.

Use it when:

- output looks frozen,
- notifications are delayed,
- API feels flaky,
- daemon seems "up" but behavior is off.

## Canonical fields

Every runtime operation entry must include these fields:

- **Operation name**: exact loop/worker name used in code.
- **Run frequency**: how often it runs by default.
- **Purpose**: one sentence of what it actually does.
- **If it fails, users see**: concrete symptom, not technical wording.
- **Self-recovery**: `yes`, `partial`, or `no`.
- **First checks**: first commands/log patterns to inspect.
- **Safe recovery action**: approved command path to restore service.

Recommended table format:

- Operation
- Frequency
- What it does
- User symptom if broken
- Self-recovery
- First checks
- Recovery action

## Allowed values

Self-recovery status:

- `yes`: normally heals without operator action.
- `partial`: may heal but can stay degraded.
- `no`: needs operator action.

Recovery actions must use project-approved service commands.

## Known caveats

- Frequencies can drift if code defaults change.
- "Daemon is running" does not mean every operation is healthy.
- Keep this file focused on real symptoms and first actions; do not turn it into generic ops theory.
