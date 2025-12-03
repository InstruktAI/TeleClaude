# AI Model Selection for AI-Spawned Sessions

> **Created**: 2025-12-03
> **Status**: 📝 Requirements

## Problem Statement

TeleClaude currently hits Claude API rate limits frequently, causing delays and failures when multiple sessions are active. All Claude Code sessions use the default model (Opus), regardless of whether they're initiated by a human or by another AI agent.

This creates unnecessary load on the Opus model, as AI-spawned sessions (which typically handle delegated tasks) could use the more cost-effective Sonnet model without impacting quality.

## Goals

**Primary Goals**:

- Automatically use Sonnet model for AI-initiated sessions to distribute load across Claude models
- Maintain Opus model for human-initiated sessions to preserve premium experience
- Persist AI session metadata in database for restart handling
- Support `--model` flag in both initial session creation and session restarts

**Secondary Goals**:

- None currently - keeping implementation minimal (KISS principle)

## Non-Goals

What is explicitly OUT of scope for this work? (KISS & YAGNI principles)

- Dynamic model selection based on load/availability (future enhancement)
- Model selection UI or user configuration
- Model fallback logic or retry mechanisms
- Cost tracking or billing integration
- Support for additional models beyond Opus/Sonnet

## User Stories / Use Cases

### Story 1: AI Master Spawning Worker Sessions

As a **Claude Code AI session (master)**, I want my spawned worker sessions to use Sonnet model automatically, so that I can delegate work without contributing to Opus rate limits.

**Acceptance Criteria**:

- [ ] Sessions created via `teleclaude__start_session` MCP tool are flagged as AI-initiated
- [ ] AI-initiated sessions receive `--model=sonnet` in their Claude Code command
- [ ] Human-initiated sessions continue using Opus (default behavior)
- [ ] Session restart preserves the model selection

### Story 2: Session Restart with Correct Model

As a **TeleClaude daemon**, I want to restart Claude Code sessions with the same model they originally used, so that AI-spawned sessions remain on Sonnet after daemon restarts.

**Acceptance Criteria**:

- [ ] Database stores `initiated_by_ai` boolean flag per session
- [ ] `restart_claude.py` checks the flag and appends `--model=sonnet` if true
- [ ] Restart command construction mirrors initial session creation

## Technical Constraints

- Must work with existing architecture patterns (async, database-first design)
- Must support multi-computer setup (flag transmitted via MCP/Redis)
- Must maintain backward compatibility with existing sessions (no breaking schema changes)
- Must follow TeleClaude coding directives (type hints, async/await, proper error handling)
- Model flag must be compatible with Claude Code CLI interface (`--model=sonnet`)

## Success Criteria

How will we know this is successful?

- [ ] AI-initiated sessions consistently use Sonnet model
- [ ] Human-initiated sessions consistently use Opus model
- [ ] Session restarts preserve original model selection
- [ ] All existing tests pass without modification
- [ ] New tests verify model flag is correctly applied
- [ ] Zero regressions in session creation or restart functionality
- [ ] Database schema migration runs cleanly on all machines

## Open Questions

- Does Claude Code support `--model=sonnet` flag? (Assumption: yes, based on roadmap)
- Should the model flag be configurable via config.yml? (Current answer: no, keep it hardcoded for simplicity)

## References

- Roadmap: `todos/roadmap.md` (AI Model Usage section, lines 8-23)
- Architecture: `docs/architecture.md`
- Project conventions: `CLAUDE.md`
- Session creation: `teleclaude/mcp_server.py:618` (`teleclaude__start_session`)
- Session restart: `teleclaude/restart_claude.py:30` (`restart_teleclaude_session`)
- Database models: `teleclaude/core/models.py`
- Command handlers: `teleclaude/core/command_handlers.py:950` (`start_claude`)
