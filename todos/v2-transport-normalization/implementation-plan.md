# Implementation Plan

## Group 1 — Normalize Inputs (Core Models + Mapper)
- [x] Add internal command model(s) that represent normalized intent (session create, agent start, send message/command, resume, close).
- [x] Create a command mapper module that converts REST/Redis/Telegram inputs into these models.
- [x] Add tests for the mapper covering at least REST + Telegram shapes.

## Group 2 — Transport Demotion (REST/Redis)
- [x] Refactor REST adapter/server entry to use the mapper and dispatch normalized commands.
- [x] Refactor Redis/MCP entry to use the mapper and dispatch normalized commands.
- [x] Remove transport-specific branching in core handlers for REST/Redis.

## Group 3 — Handler Signature Unification
- [x] Update handler entry points to accept normalized command models (or a single normalized request object) instead of loose payload/metadata.
- [x] Ensure ordering-sensitive paths (session creation welcome/output) are still awaited.

## Group 4 — Tests + Verification
- [x] Update existing tests that depended on legacy payload/metadata shapes.
- [x] Add regression tests for session creation and agent start to assert unchanged behavior.
- [x] Run format/lint/tests and commit per task.

## Group 5 — Review (Handled by next-review)

## Group 6 — Finalize (Handled by next-finalize)
