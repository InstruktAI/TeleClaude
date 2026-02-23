# DOR Report: discord-adapter-integrity

## Gate Verdict: PASS (score 8/10)

Assessed by: gate (inline, separate from draft)
Date: 2026-02-23

---

### Gate 1: Intent & Success — PASS

Problem statement explicit in `input.md` (3 issues with root causes and evidence). Requirements capture 3 scoped deliverables with clear "in scope" / "out of scope" boundaries. Success criteria are concrete and testable: delete forum + restart → auto-reprovision, separate per-computer categories visible in guild sidebar, admin forum messages create sessions with correct role and project path.

### Gate 2: Scope & Size — PASS

All changes constrained to `discord_adapter.py` (per requirements constraint). Three logical changes are sequential and mechanical:

- Phase 1 (infra validation): extract `_validate_channel_id` helper, apply to 6 channel ID guards + `_ensure_project_forums` loop guard.
- Phase 2 (per-computer categories): one string interpolation change + key derivation fix in `_ensure_category`.
- Phase 3 (forum input routing): context-aware `_create_session_for_message` + entry logging.

Each phase is independently testable. Context exhaustion risk is low.

### Gate 3: Verification — PASS

Each success criterion has a verification path:

- Infra validation: delete a Discord forum, restart daemon, verify re-creation.
- Per-computer categories: inspect guild sidebar for "Projects - {computer}" categories.
- Forum routing: send admin message in project forum, verify session has correct role (not "customer") and correct project path (not help_desk_dir).
- Logging: verify DEBUG logs appear for all incoming messages in `_handle_on_message`.
- `demo.md` covers all verification steps with guided presentation.

### Gate 4: Approach Known — PASS

All approaches verified against the codebase:

- `_ensure_category` (line 323-345) already validates cached IDs: fetches, checks None, falls through to create. The helper extraction generalizes this proven pattern to the 6 `if self._xxx_channel_id is None:` guards (lines 264, 270, 279, 285, 293, 303) and the `_ensure_project_forums` guard (line 368).
- Identity resolution pattern exists in DM handler (line 896): `identity.person_role or "member"`. Plan correctly prescribes applying this to `_create_session_for_message` (currently hardcoded at line 1374).
- `_project_forum_map` (line 347-360) already maps `project_path → forum_id`. Reverse lookup (`forum_id → project_path`) is straightforward.
- Customer gate at line 1039 (`_is_customer_session && !_is_help_desk_thread`) explains the silent drop: sessions from project forums get "customer" role, then are blocked.
- Key derivation at line 331 (`name.lower().replace(" ", "_")`) produces `projects_-_mozbook` from `"Projects - MozBook"`. Plan correctly identifies and prescribes fix.

No architectural decisions remain unresolved.

### Gate 5: Research Complete — PASS (auto-satisfied)

All changes are internal. No third-party dependencies introduced. Discord.py API calls used are already in the codebase.

### Gate 6: Dependencies & Preconditions — PASS

No `after:` dependencies in `roadmap.yaml`. Config access is local. Discord bot token and guild ID are already configured. `config.computer.name` is reliably set (used across the codebase).

### Gate 7: Integration Safety — PASS

- Infra validation: additive — only changes behavior when IDs are stale (currently silent 404 failure path).
- Per-computer categories: creates new categories alongside old. Old "Projects" category remains but is no longer managed. Manual cleanup is cosmetic, not a code concern.
- Forum routing fix: changes session creation params for forum messages only. Help desk and DM flows are untouched.

Rollback: revert the commit. No data migration needed.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No tooling or scaffolding changes.

---

## Plan-to-Requirement Fidelity Check

| Requirement                         | Plan tasks             | Contradiction check                                                 |
| ----------------------------------- | ---------------------- | ------------------------------------------------------------------- |
| R1: Infrastructure validation       | T1.1                   | No contradictions. Extends `_ensure_category` pattern.              |
| R2: Per-computer project categories | T2.1, T2.2, T2.3       | No contradictions. `config.computer.name` interpolation.            |
| R3: Forum input routing             | T3.1, T3.2, T3.3, T3.4 | No contradictions. Resolves identity + path from existing patterns. |

No task contradicts any requirement. No task introduces scope beyond requirements.

Note: the previous dor-report referenced "text delivery between tool calls" — this is explicitly out of scope (requirements.md line 18-19, covered by `adapter-output-delivery` todo). Report replaced.

## Assumptions (verified)

- `config.computer.name` is reliably set — confirmed via codebase usage.
- `_project_forum_map` reverse lookup is feasible — map is built from `(td.path, td.discord_forum)` pairs (line 353-354).
- `_is_managed_message` already accepts project forum messages (line 1132-1157) — the bug is downstream in `_create_session_for_message`, not in the gate.

## Open Questions (non-blocking)

1. **Old "Projects" category cleanup**: after per-computer categories are live, the old category persists. One-time cosmetic cleanup, not a code concern.

## Unresolved Blockers

None.
