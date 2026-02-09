---
id: 'project/spec/session-identity-truth'
type: 'spec'
scope: 'project'
description: 'Canonical TeleClaude session identity mapping rules for managed and headless session routes.'
---

# Session Identity Truth — Spec

## What it is

A project-specific identity mapping contract for TeleClaude session attribution.

It defines:

- managed-route identity behavior,
- headless-route identity behavior,
- source-of-truth fields,
- and conflict/recovery rules.

## Canonical fields

Identity documentation must define:

- managed route,
- headless route,
- identity source-of-truth per route,
- native-to-teleclaude mapping source,
- authority rule when identifiers disagree,
- recovery behavior after restart.

Required identity fields:

- TeleClaude session id,
- native session id,
- native log/transcript path,
- mapping record reference.

## Allowed values

Route type:

- `managed`
- `headless`

Authority mode:

- `managed-marker-authoritative`
- `native-mapping-authoritative`

Recovery outcome:

- `reassociate-existing`
- `mint-new`
- `fail-with-diagnostic`

## Known caveats

- Legacy compatibility paths can introduce identity conflicts if not clearly bounded.
- This spec must match receiver and session mapping runtime behavior.
