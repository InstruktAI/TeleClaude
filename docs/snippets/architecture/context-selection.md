---
id: architecture/context-selection
description: Select and emit relevant snippets using local LLM ranking with session-level dedupe.
type: architecture
scope: project
requires:
  - context-index.md
---

# Context Selection

## Purpose
- Select relevant snippets for a request and emit only new snippets per session.

## Inputs/Outputs
- Inputs: user corpus, optional area filters, project root, session_id.
- Outputs: formatted payload with already-provided snippet IDs and new snippet contents.

## Invariants
- Snippets are loaded from global snippets and project `docs/snippets`.
- Selection uses a local LLM endpoint and returns a JSON list of snippet IDs.
- Session state is persisted in `logs/context_selector_state.json` to avoid repeats.

## Primary Flows
- Parse snippet metadata (id/description/type) and send to selector.
- Resolve dependencies via `requires`, filter already-sent IDs, and emit new snippet bodies.

## Failure Modes
- LLM failures or invalid JSON responses result in no new snippets.
- Unreadable snippet files are skipped with logged errors.
