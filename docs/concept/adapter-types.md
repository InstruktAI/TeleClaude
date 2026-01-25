---
description: Distinction between UI adapters and transport adapters in TeleClaude.
id: teleclaude/concept/adapter-types
scope: project
type: concept
---

# Adapter Types — Concept

## Purpose

- @docs/concept/glossary

- Clarify the two adapter categories and the responsibilities they carry.

- Inputs: external user input (UI) or remote transport events.
- Outputs: normalized command objects or remote command transport.

- UI adapters handle human-facing messaging, topics, and UX rules.
- Transport adapters provide cross-computer request/response for remote execution.

- UI adapters do not implement cross-computer execution.
- Transport adapters do not render human UX or manage message cleanup.
- AdapterClient is the only component that routes between adapters.

- Mixing responsibilities causes boundary violations and routing bugs.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
