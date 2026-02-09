# Roadmap

> **Last Updated**: 2026-02-09
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Rolling Session Titles

- [.] rolling-session-titles

Re-summarize session titles based on the last 3 user inputs instead of only the first. Use a dedicated rolling prompt that captures session direction. Reset the output message on any title change so the topic floats to the top in Telegram.

## Config Schema Validation

- [ ] config-schema-validation

Pydantic-based schema for teleclaude.yml across all three config levels (project, global, per-person). Enforce level constraints (only global can configure `people`), validate before interpreting/merging, fix interests schema mismatch (flat list vs nested dict in discovery.py).

## Eliminate Raw SQL from DB Layer

- [ ] db-raw-sql-cleanup

Convert inline SQL in db.py to SQLModel/SQLAlchemy ORM and enforce via pre-commit hook.

## Test Suite Quality Cleanup

- [ ] repo-cleanup

Refactor test suite to verify observable behavior, add docstrings, document system boundaries.

## Release Automation Pipeline

- [ ] release-automation

Automated AI-driven release pipeline with Claude Code and Codex CLI inspectors.

## Code Context Annotations (Phase 1)

- [ ] code-context-annotations

Self-documenting codebase via `@context` annotations in docstrings. A scraper extracts annotated docstrings into doc snippets that integrate with `teleclaude__get_context`, making code architecture discoverable through the existing two-phase context system. Foundation for the self-correcting feedback loop.

## Code Context Auditor (Phase 2)

- [ ] code-context-auditor

Consistency auditor that compares annotation claims against actual code behavior. Detects drift, scope creep, boundary violations, and naming inconsistencies. Produces structured audit reports. Creates the self-improvement feedback loop where the codebase's documentation continuously verifies and corrects itself. Depends on: code-context-annotations.

## Bidirectional Agent Links

- [ ] bidirectional-agent-links

Direct agent-to-agent communication via bidirectional links. When A sends a message to B, both agents' `agent_stop` output is injected into the other's session. System-enforced turn budgets prevent chattiness. Only distilled output crosses the link — thoughts and tool calls stay private.

## Idea Miner — Periodic Idea Box Processing

- [ ] idea-miner

Daily job that mines `ideas/` using multi-lens AI analysis (feasibility, impact, fit). Workers are fire-and-forget with structured output; orchestrator synthesizes into verdicts. Actionable ideas become todos, full report sent via Telegram. Establishes the "job dispatches AI sessions" pattern.

## Role-Based Notifications

- [ ] role-based-notifications

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.

## UI Experiment: Threaded Incremental Output

- [x] threaded-output-experiment

Deliver agent feedback as regular threaded messages instead of one editable pane.
