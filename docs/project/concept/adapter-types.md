---
description: Distinction between UI adapters and transport adapters in TeleClaude.
id: teleclaude/concept/adapter-types
scope: project
type: concept
---

# Adapter Types — Concept

## Purpose

- @docs/project/concept/glossary.md

- Clarify the two adapter categories and the responsibilities they carry.
- UI adapters handle human-facing messaging, topics, and UX rules.
- Transport adapters provide cross-computer request/response for remote execution.
- AdapterClient is the only component that routes between adapters.

## Inputs/Outputs

- **Inputs**: external user input (UI adapters) or remote transport events (transport adapters).
- **Outputs**: normalized command objects (UI) or remote command transport payloads (transport).

## Invariants

- UI adapters do not implement cross-computer execution.
- Transport adapters do not render human UX or manage message cleanup.
- Adapter boundaries are enforced by AdapterClient routing rules.

## Primary flows

- **UI input flow**: user input → UI adapter → command object → core.
- **Remote command flow**: transport adapter → command object → core → response stream.
- **Output fan-out**: core events → AdapterClient → UI + transport adapters.

## Failure modes

- Mixed responsibilities cause routing bugs and duplicate outputs.
- Missing adapter registration drops output updates for that channel.
- Transport adapter misroutes responses when correlation IDs are missing.
