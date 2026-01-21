---
description: Distinction between UI adapters and transport adapters in TeleClaude.
id: teleclaude/concept/adapter-types
requires:
  - teleclaude/concept/glossary
scope: project
type: concept
---

## Purpose

- Clarify the two adapter categories and the responsibilities they carry.

## Inputs/Outputs

- Inputs: external user input (UI) or remote transport events.
- Outputs: normalized command objects or remote command transport.

## Primary flows

- UI adapters handle human-facing messaging, topics, and UX rules.
- Transport adapters provide cross-computer request/response for remote execution.

## Invariants

- UI adapters do not implement cross-computer execution.
- Transport adapters do not render human UX or manage message cleanup.
- AdapterClient is the only component that routes between adapters.

## Failure modes

- Mixing responsibilities causes boundary violations and routing bugs.
