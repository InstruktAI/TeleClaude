# DOR Report: history-search-upgrade

## Draft Assessment

### Gate 1: Intent & Success

**Status: Pass**

Problem statement is explicit: replace brute-force JSONL scanning with FTS5-backed conversation mirrors. Success criteria are concrete and testable (FTS5 search returns results, remote search works, mirrors auto-generate, existing flags preserved). The "what" (searchable recall layer) and "why" (transcript noise, cross-computer access) are captured in `input.md`.

### Gate 2: Scope & Size

**Status: Pass**

Work spans multiple files but follows a clear layered architecture (storage → generation → distribution → search). Each phase is independently testable. The scope is bounded: no transcript format changes, no TUI changes, no real-time streaming. Cross-cutting concerns are justified (daemon + CLI + channels).

**Size concern**: This is a substantial feature. The implementation plan has 7 phases and ~15 tasks. A single session may strain context. Consider: Phase 1-2 (storage + generation) could be a standalone increment. Distribution and remote search could follow.

### Gate 3: Verification

**Status: Pass**

Each phase has testable outcomes: migration creates tables, generation populates mirrors, FTS5 returns search results, channel publishes/consumes, `--computer` flag routes correctly. Demo script validates end-to-end.

### Gate 4: Approach Known

**Status: Pass**

Every technical component follows an existing pattern in the codebase:

- FTS5: `memory_observations_fts` in migration 005
- Channel fanout: `teleclaude/deployment/handler.py`
- Extraction: `extract_structured_messages()` in transcript.py
- Read-only DB: current `history.py` pattern (with upgrade to daemon DB path)
- Background worker: existing daemon task patterns

No novel architecture. No unresolved design decisions.

### Gate 5: Research Complete

**Status: Pass**

Infrastructure research completed across 4 parallel agents. Findings verified against actual codebase:

- DB schema confirmed (23 tables, FTS5 in use)
- Channel module confirmed (publisher, consumer, worker, API)
- Extraction function confirmed (filters work as needed)
- Session lifecycle events mapped (SESSION_CLOSED limitations documented)

No third-party dependencies introduced.

### Gate 6: Dependencies & Preconditions

**Status: Pass**

Prerequisites: daemon SQLite database (exists), Redis for distribution (existing infrastructure, graceful degradation), `extract_structured_messages()` (exists). No external system access needed. No blocking dependencies on other todos.

### Gate 7: Integration Safety

**Status: Pass**

- Migration is additive (new table, no schema changes to existing tables)
- `history.py` upgrade can be incremental (FTS5 path + fallback to brute-force)
- Distribution is best-effort (local operation continues without Redis)
- Daemon restart required after migration (brief, per daemon-availability policy)

### Gate 8: Tooling Impact

**Status: N/A**

No tooling or scaffolding changes. The history tool spec will need updating after delivery, but that's a post-delivery task.

## Open Questions

1. **Session phasing**: Should this be split into two delivery phases (local mirrors first, distribution second)? The implementation plan is designed to allow it, but the requirements treat it as one unit.
2. **Backfill timing**: The backfill job processes ~3,660 transcripts. Should this run as a daemon background task or a separate CLI invocation? The plan assumes CLI-invocable, but daemon-integrated would be more autonomous.
3. **History.py DB path discovery**: Currently `history.py` scans JSONL files directly. The upgrade needs the daemon DB path. Should it read `config.yml` or use the `TELECLAUDE_DB_PATH` env var? Both are available.

## Assumptions

- FTS5 is available in the system SQLite (confirmed: already in use via migration 005).
- Redis is available for distribution (existing infrastructure; graceful degradation if not).
- The daemon's session cleanup path is reliable for final mirror generation.
- ~3,660 existing transcripts can be processed in a single backfill run (batch, not streaming).
