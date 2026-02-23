# DOR Report: discord-adapter-integrity

## Gate Verdict: PASS (score 8/10)

Assessed by: gate worker (separate from draft worker)
Date: 2026-02-23

---

### Gate 1: Intent & Success — PASS

Problem statement is explicit across input.md (5 issues identified with root causes and evidence) and requirements.md (3 scoped deliverables). Success criteria are concrete and testable: text delivery latency (~2s), re-provisioning behavior (delete forum -> restart -> auto-recreate), per-computer category separation (visual inspection), routing correctness (session appears in correct forum).

### Gate 2: Scope & Size — PASS (borderline, acceptable)

Three distinct changes touching 4 files. Code verification confirms:

- Phase 1 (infra validation): `discord_adapter.py` only — extract `_validate_channel_id` helper, apply to 6 channel ID guards + `_ensure_project_forums` loop guard.
- Phase 2 (per-computer categories): `discord_adapter.py` only — one string interpolation + key derivation fix.
- Phase 3 (text delivery): `agent_coordinator.py` (new method), `adapter_client.py` (one attribute), `daemon.py` (one wiring line), `polling_coordinator.py` (one call site).

Changes are mechanical and sequential. Each phase is independently testable. Context exhaustion risk is low given the pattern-following nature of the work. If a builder hits capacity after Phase 2, Phase 3 can be completed in a follow-up session without rework.

The draft's split recommendation (Phase 1+2 vs Phase 3) remains valid as a fallback but is not required as a precondition.

### Gate 3: Verification — PASS

Each deliverable has a clear verification path:

- Text delivery: observe Discord thread during active session, compare with TUI. Automated test for `trigger_incremental_output` specified.
- Infra validation: delete a forum, restart daemon, verify re-creation. Automated test for stale ID clearing specified.
- Per-computer categories: inspect guild sidebar after multi-computer startup.
- Regression checks: non-threaded sessions, hook-triggered events, digest dedup.

### Gate 4: Approach Known — PASS

All three approaches verified against the codebase:

- `_ensure_category` (line 326-341) already validates cached IDs. The helper extraction generalizes this proven pattern.
- `_maybe_send_incremental_output` (line 620+) accepts `AgentOutputPayload` with defaults; `raw={}` safely falls back via `session.active_agent`.
- `adapter_client` is available in the poller's `OutputChanged` handler (line 759 context). Wiring at `daemon.py` line 251 is the correct injection point.
- `_ensure_category` key derivation (`name.lower().replace(" ", "_")`) produces `projects_-_mozbook` from `"Projects - MozBook"`. Plan correctly identifies this and prescribes a fix.

No architectural decisions remain unresolved.

### Gate 5: Research Complete — PASS (auto-satisfied)

All changes are internal. No third-party dependencies introduced. Discord.py API calls used (`_get_channel`, `_find_or_create_forum`, `_find_or_create_category`) are already in the codebase.

### Gate 6: Dependencies & Preconditions — PASS

No prerequisite todos. Config access is local. Discord bot token and guild ID are already configured. `config.computer.name` is used in 10+ locations across the codebase (verified via grep) and is reliably set.

Note: slug is not yet in `roadmap.yaml`. This is an operational scheduling step, not a readiness blocker. The todo directory and all artifacts exist.

### Gate 7: Integration Safety — PASS

- Infra validation: additive — only changes behavior when IDs are stale (currently a silent 404 failure path).
- Per-computer categories: creates new categories alongside old. Old "Projects" category remains but is no longer managed. Manual cleanup is cosmetic.
- Text delivery: additive — new trigger alongside existing hook triggers. Digest dedup in `_maybe_send_incremental_output` prevents double delivery. Non-threaded sessions rejected at fast-path (`is_threaded_output_enabled` check).

Rollback: revert the commit. No data migration needed.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No tooling or scaffolding changes.

---

## Actions Taken by Gate

1. **Tightened implementation plan Task 1.1**: made the `_ensure_project_forums` validation instruction more precise — specifies modifying the existing `if td.discord_forum is not None: continue` guard to validate via `_validate_channel_id` and clear stale IDs inline, rather than leaving the location ambiguous.

## Plan-to-Requirement Fidelity Check

| Requirement                          | Plan tasks       | Contradiction check                                                                  |
| ------------------------------------ | ---------------- | ------------------------------------------------------------------------------------ |
| R1: Text delivery between tool calls | T3.1, T3.2, T3.3 | No contradictions. Plan reuses existing `_maybe_send_incremental_output` with dedup. |
| R2: Infrastructure validation        | T1.1             | No contradictions. Plan extends `_ensure_category`'s existing pattern.               |
| R3: Per-computer project categories  | T2.1, T2.2, T2.3 | No contradictions. Plan uses `config.computer.name` interpolation.                   |

No task contradicts any requirement. No task introduces scope beyond requirements.

## Assumptions (verified)

- `config.computer.name` is reliably set — confirmed via 10+ usage sites in codebase.
- `AgentOutputPayload()` with defaults is sufficient — verified: `raw={}`, `raw.get("agent_name")` returns None, falls back to `session.active_agent`.
- Poller fires at ~1s granularity — this is the existing polling interval, acceptable for ~2s delivery target.

## Open Questions (non-blocking)

1. **Old "Projects" category cleanup**: after per-computer categories are live, the old category persists. Manual cleanup recommended — one-time cosmetic task, not a code concern.

## Unresolved Blockers

None.
