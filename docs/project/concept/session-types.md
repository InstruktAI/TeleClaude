---
id: concept/session-types
type: concept
scope: global
description: Classification of terminal sessions in TeleClaude.
---

# Session Types — Concept

## Purpose

Classify the session categories used in TeleClaude.

- **Human session**: initiated by a human via Telegram or `telec` CLI; direct input/output with cleanup.
- **AI-to-AI session**: initiated by MCP tools; programmatic messaging and stop summaries.
- **Worktree session**: initiated by agents in git worktrees; isolated `teleclaude.db`.

## Inputs/Outputs

- **Inputs**: session creation commands and launch intents.
- **Outputs**: human, AI-to-AI, or worktree session behavior.

## Invariants

- Session type is determined at creation and remains stable.
- Type controls UX cleanup and listener behavior.

## Primary flows

- Session create command includes type intent → launcher configures adapters accordingly.

## Failure modes

- Misclassified sessions cause incorrect UX cleanup and routing.
