---
id: 'software-development/procedure/preparation-discipline'
type: 'procedure'
scope: 'domain'
description: 'Behavioral primer for preparation work. Activates quality discipline before the agent acts.'
---

# Preparation Discipline — Procedure

## Goal

Anchor the preparation-artifact-quality rules at the end of every preparation
command, closest to where the agent acts. Context distance dilutes constraints:
what was read first fades as the window fills. This procedure exists to counteract
that effect.

## Preconditions

- The agent has loaded its role-specific procedure (discovery, draft, review, or gate).
- The preparation-artifact-quality policy is in the required reads.

## Steps

### 1. Load domain specs before producing or modifying any artifact

Identify which specs your artifact touches and read them via `telec docs get`.
You cannot validate grounding, leakage, or review-awareness without the actual
specs. General knowledge is not grounding.

### 2. Apply the leakage discriminator

For every statement in requirements: could a builder satisfy it using a different
implementation approach? If the answer is no and there is no justification, you
are prescribing — fix it.

### 3. Respect auto-remediation boundaries

You may fix what exists: tighten wording, add missing markers, fill gaps already
implied by the content. You may **never** add new scope items, new success
criteria, new constraints, or new architectural decisions. If something is
missing, the verdict is `needs_work` — not a silent addition.

### 4. Verify against loaded specs, not memory

Every reference to an API, schema, config surface, directory structure, or
convention must be confirmed against the spec you loaded. If you cannot confirm
it, flag it.

### 5. Walk the Definition of Done as your review-awareness checklist

For each artifact element, identify which DoD gates it triggers and verify those
implications are reflected.

### 6. Know your failure mode

Each role has a characteristic error:

- **Requirements creator**: inventing constraints not in the input, prescribing
  implementation detail, omitting `[inferred]` markers.
- **Requirements reviewer**: adding scope through auto-remediation instead of
  marking `needs_work`.
- **Plan drafter**: tasks without rationale, references to APIs/paths not
  confirmed against specs.
- **Plan reviewer**: approving plans that enumerate implementation choices
  belonging to the builder.
- **Gate assessor**: scoring structure without loading domain specs — checking
  form without substance.

## Outputs

- No artifacts produced. This procedure modifies behavior, not files.

## Recovery

- If you realize mid-work that you skipped domain spec loading, stop and load
  them before continuing. Do not rationalize skipping — the past failures that
  created this procedure all started with "I already know this."
