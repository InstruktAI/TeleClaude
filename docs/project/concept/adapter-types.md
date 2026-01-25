---
description: Distinction between UI adapters and transport infrastructure in TeleClaude.
id: teleclaude/concept/adapter-types
scope: project
type: concept
---

# Adapter Types — Concept

## Purpose

- @docs/project/concept/glossary.md

- Clarify UI adapter responsibilities versus transport infrastructure.
- UI adapters handle human-facing messaging, topics, and UX rules.
- Redis transport provides cross-computer request/response for remote execution.
- AdapterClient routes to UI adapters; transport is invoked directly for remote execution.

## Inputs/Outputs

- **Inputs**: external user input (UI adapters) or remote transport events (Redis).
- **Outputs**: normalized command objects (UI) or remote transport payloads (Redis).

## Invariants

- UI adapters do not implement cross-computer execution.
- Transport infrastructure does not render UX or manage message cleanup.
- AdapterClient enforces UI adapter boundaries; transport remains a separate layer.

## Primary flows

- **UI input flow**: user input → UI adapter → command object → core.
- **Remote command flow**: Redis transport → command object → core → response stream.
- **Output fan-out**: core events → AdapterClient → UI adapters.

## Failure modes

- Mixed responsibilities cause routing bugs and duplicate outputs.
- Missing adapter registration drops output updates for that channel.
- Transport misroutes responses when correlation IDs are missing.
