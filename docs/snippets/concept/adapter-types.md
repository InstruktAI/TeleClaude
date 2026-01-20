---
id: teleclaude/concept/adapter-types
type: concept
scope: project
description: Distinction between UI adapters and transport adapters in TeleClaude.
requires:
  - glossary.md
---

Purpose
- Clarify the two adapter categories and the responsibilities they carry.

Concept
- UI adapters handle human-facing messaging, topics, and UX rules.
- Transport adapters provide cross-computer request/response and streaming semantics.

Invariants
- UI adapters do not implement cross-computer execution.
- Transport adapters do not render human UX or manage message cleanup.
- AdapterClient is the only component that routes between adapters.
