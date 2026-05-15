---
id: 'software-development/procedure/lifecycle/prepare/discipline'
type: 'procedure'
domain: 'software-development'
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

- The agent has loaded its role-specific procedure (intake, architecture, specs, plan, review, or gate).
- The preparation-artifact-quality policy is in the required reads.

## Steps

### 0. Re-entry is the base case

Re-entry is the default for prepare dispatches — fresh production is the
special case (first time only). Dispatches that ask a worker to produce or
review a downstream artifact (build-specs, prepare-plan, review-architecture,
review-specs, review-plan, drift review) carry a
`Dispatch reason: <reason>` header so the worker knows which behavior to
pick. Reasons are: `fresh`, `findings-fix`, `upstream-changed`,
`provenance-missing`. Each prescribes a different behavior; do not assume
fresh write. PRD/intake dispatches do NOT carry the header — those phases are
gated on the absence of a PRD artifact and are unconditionally fresh-or-refine
passes; the worker derives behavior from the current artifact state, not from a
reason header.

### 1. Load domain specs before producing or modifying any artifact

Identify which specs your artifact touches and read them via `telec docs get`.
You cannot validate grounding, leakage, or review-awareness without the actual
specs. General knowledge is not grounding.

### 2. Apply the leakage discriminator

For every statement in the PRD: could a builder satisfy it using a different
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

## Outputs

- No artifacts produced. This procedure modifies behavior, not files.

## Recovery

- If you realize mid-work that you skipped domain spec loading, stop and load
  them before continuing. Do not rationalize skipping — the past failures that
  created this procedure all started with "I already know this."
