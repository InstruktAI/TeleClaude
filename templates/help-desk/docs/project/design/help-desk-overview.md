---
id: project/design/help-desk-overview
type: design
scope: project
description: Help desk workspace overview and architecture.
audience: [admin, help-desk]
---

# Help Desk Overview — Design

## Purpose

This workspace is the operator's home base for handling customer interactions. It holds the operator brain, escalation documentation, organization knowledge, and runtime artifacts.

Use `/author-knowledge` to document your escalation rules, support procedures, SLAs, product knowledge, and FAQ.

## Inputs/Outputs

**Inputs:**

- Customer messages via platform adapters (Discord, Telegram, web)
- Organization documentation in `docs/global/organization/`
- Escalation policies and procedures in `docs/project/`

**Outputs:**

- AI-handled customer conversations
- Extracted customer memories (identity-scoped)
- Business intelligence (project-scoped)
- Escalation relay threads for admin intervention

## Invariants

- The operator brain (`AGENTS.master.md`) is version-controlled.
- Runtime directories (`inbox/`, `logs/`, `outcomes/`) are gitignored.
- Organization docs are symlinked to `~/.teleclaude/docs/organization/` for cross-project visibility.

## Primary flows

Customer interaction, escalation, and idle compaction are the three primary flows. See the main help desk platform design doc for detailed sequence diagrams.

## Failure modes

| Scenario                     | Behavior                                    |
| ---------------------------- | ------------------------------------------- |
| Escalation with Discord down | Tool returns error; agent informs customer  |
| Missing organization docs    | Operator uses only project-scoped knowledge |
| Stale customer memories      | Most recent memories prioritized by recency |
