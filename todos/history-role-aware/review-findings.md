# Review Findings: history-role-aware

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-03-27

## Scope Verification

All R1–R4 requirements are implemented:

- **R1 (history list):** `_handle_history_list` in `history.py` parses `--identity`, `--project`, `--limit` (default 20). Output is tabular with session_id, title, timestamps, origin channel, summary, message_count. Ordered by recency via `list_mirrors` in `store.py`.
- **R2 (channel metadata):** `_extract_channel_identifiers` in `processors.py` extracts platform-specific IDs for telegram/discord/whatsapp origins. Origin channel and identifiers stored in mirror metadata dict via `generate_mirror_sync`.
- **R3 (role-aware filtering):** `_apply_role_filter` in `store.py` applies consistent admin/member/customer/unauthenticated filtering across `list_mirrors`, `search_mirrors`, and `get_mirror`. Member sees own + shared (matching `_filter_sessions_by_role` in sessions API). Caller identity resolved via `resolve_cli_caller_role` in `history.py`.
- **R4 (session summary):** `_generate_session_summary` in `generator.py` calls `_call_summarizer` at mirror-creation time. Best-effort with broad catch per R4.3. Migration 033 documents the schema change; actual DDL in `_migrate_add_mirror_columns`.

No gold-plating or unrequested features within the history-role-aware scope.

## Completeness

- All 11 implementation-plan tasks checked `[x]`.
- No `deferrals.md` present.
- All xfail spec markers removed — 0 remaining xfail markers for HistoryRoleAware specs.

## Code Review

- SQL queries use parameterized `?` placeholders throughout — no injection vectors.
- `_apply_role_filter` is extracted as a reusable helper, ensuring consistent filtering across list/search/get.
- `list_mirrors` follows the same query pattern as `search_mirrors` and `get_mirror`.
- `generate_mirror_sync` orchestrates message extraction → normalization → metadata build → summary generation → upsert. Single responsibility for mirror generation.

No bugs or pattern violations found in the history-role-aware scope.

## Paradigm-Fit Assessment

1. **Data flow:** `list_mirrors` follows the same raw-sqlite3 pattern as `search_mirrors`/`get_mirror`. ✓
2. **Component reuse:** `_apply_role_filter` centralizes role filtering, mirroring the `_filter_sessions_by_role` pattern in `sessions_routes.py:81–103`. ✓
3. **Pattern consistency:** `_handle_history_list` follows the same arg-parsing and dispatch pattern as `_handle_history_search` and `_handle_history_show`. ✓

No paradigm violations.

## Principle Violation Hunt

### Fallback & Silent Degradation

All fallback paths in the history-role-aware scope are justified:

| Location              | Pattern                                                     | Justification                                                        |
| --------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- |
| `generator.py:86`     | `except Exception` in `_generate_session_summary`           | R4.3: summary generation is best-effort                              |
| `history.py:22-25`    | `except (...): return None` in `resolve_cli_caller_role`    | R3.5: unauthenticated caller preserves unfiltered behavior           |
| `processors.py:28-31` | `except (...): return {}` in `_extract_channel_identifiers` | R2.4: existing mirrors without channel metadata continue to function |
| `store.py:299,579`    | `except OperationalError "no such table": return []`        | Existing pattern: mirrors DB may not exist yet                       |

No unjustified fallbacks found.

### Other Principles

- **DIP:** No core→adapter imports. Channel identifier extraction happens in `processors.py` (part of the mirrors module), not in core. ✓
- **Coupling:** `_extract_channel_identifiers` accesses `adapter.get_ui().telegram` — 2-dot chain through stable adapter metadata types. Acceptable. ✓
- **SRP:** Functions have focused responsibilities. ✓
- **YAGNI/KISS:** No premature abstractions. Direct SQL queries without ORM overhead for the mirrors store. ✓
- **Encapsulation:** `MirrorRecord` is frozen. State mutations go through `upsert_mirror`. ✓
- **Immutability:** Metadata dicts are constructed at creation time, not mutated after. ✓

## Security Review

1. **Secrets:** No hardcoded credentials in the diff. ✓
2. **Sensitive data in logs:** Logger calls use debug level without PII. ✓
3. **Input validation:** CLI args validated; unknown flags produce error + usage. ✓
4. **Injection:** All SQL uses `?` parameter binding. `clauses` list contains only hardcoded SQL fragments; user input is always bound as parameters. ✓
5. **Authorization:** Role-based filtering applied at query time via `_apply_role_filter`. Admin bypasses filter, member sees own + shared, customer sees own only. ✓
6. **Error messages:** Error messages don't expose internals. ✓

No security findings.

## Test Coverage

- **4346 tests pass**, 8 xfailed (pre-existing, unrelated).
- All 7 xfail spec tests from the implementation plan are satisfied and markers removed.
- New tests cover: `list_mirrors` with role filtering and identity matching, channel metadata extraction, summary generation, CLI handler arg parsing, caller context passthrough in search/show.
- Edge cases covered: unauthenticated caller (no filtering), member access pattern (own + shared), customer restriction, identity matching by both email and source_identity.

No missing test coverage for the history-role-aware requirements.

## Silent Failure Analysis

Broad exception handlers are documented above (all justified by requirements). No silent failures that hide actionable errors. The best-effort summary generation pattern is appropriate — mirror creation must not be blocked by summarizer failures.

## Comment Analysis

- Docstrings match function signatures and behavior.
- Migration 033 docstring accurately describes the split between this file (documentation) and store.py (actual DDL).
- No stale comments referencing removed behavior.

## Type Design

- `visibility: str` on MirrorRecord follows the existing pattern (Session.visibility is also str). A Literal type or enum would be more precise but is a pre-existing design choice — not a regression.
- Optional fields have correct nullability (`summary: str | None`, `human_email: str | None`).
- `SessionMirrorContext` fields use `str | None` consistently for nullable session data.

No type design issues.

## Demo Review

7 executable bash blocks verified:

1. `telec history list --limit 3` — command and flags exist ✓
2. `telec history list --project TeleClaude --limit 3` — filter exists ✓
3. `telec history list --identity maurice@instrukt.ai --limit 3` — email filter ✓
4. `telec history list --identity telegram:1285425702 --limit 3` — source_identity filter ✓
5. `telec history --help` — shows list subcommand ✓
6. `telec history search --limit 2 session` — existing command regression check ✓
7. `telec history list --limit 1 2>/dev/null | head -3` — pipe integration ✓

Guided presentation accurately describes member access as "own + shared" and identity filter as matching `human_email OR source_identity`.

## Documentation & Config Surface

- `list` subcommand registered in `surface.py` with correct flags and auth level. ✓
- `docs/global/general/spec/tools/telec-cli.md` uses `<!-- @exec: telec history -h -->` template — auto-updates from CLI surface. ✓
- No new config keys introduced. ✓

## Logging

- Mirror event processing uses debug-level logging at appropriate boundaries (skip reasons). ✓
- Summary generation failure logged at debug level (best-effort). ✓
- No ad-hoc debug probes in committed code. ✓

## Resolved During Review

1. **Formatting violations** in `teleclaude/utils/transcript/_tool_calls.py` and `tests/unit/utils/transcript/test__tool_calls.py` — missing blank lines between top-level definitions (introduced by the identity-origin-cleanup commit). Auto-remediated via `ruff format`.

## Why No Issues

The zero-finding result is supported by:

1. **Paradigm-fit verified:** Checked data flow pattern (raw sqlite3), component reuse (`_apply_role_filter`), CLI handler pattern consistency against existing `search`/`show` handlers.
2. **Requirements validated:** Every R1–R4 requirement traced to specific code locations. R1.1–R1.6, R2.1–R2.4, R3.1–R3.6, R4.1–R4.5 all satisfied. Success criteria checklist fully coverable.
3. **Copy-paste duplication checked:** `list_mirrors` builds its own SQL rather than duplicating `search_mirrors`. Role filtering centralized in `_apply_role_filter`.
4. **Security reviewed:** SQL parameterization verified in all 5 query functions (search_mirrors, get_mirror, list_mirrors, get_session_context, upsert_mirror). Role filtering logic verified against sessions API pattern.

## Observations (Non-Blocking)

1. **Co-delivered identity-origin-cleanup:** Commit `ebde3df96` delivers the `identity-origin-cleanup` todo on this branch (channel_metadata→origin_metadata rename, typed origin metadata). This is a separate todo with its own scope, demo, and cleanup. Review of identity-origin-cleanup changes is limited to verifying tests pass. Consider a separate review cycle for that scope.
2. **Pre-existing pyright error:** `teleclaude/utils/transcript/_tool_calls.py:467` has a pre-existing type error (`datetime < datetime | None`) that exists on main. Not a regression.
3. **resolve_cli_caller_role simplification:** The implementation plan described a `_resolve_history_caller_context()` that would also call `TelecAPIClient.get_auth_whoami()`. The builder simplified to `resolve_cli_caller_role()` without daemon whoami fallback. This is correct because R3.5 covers the unresolvable-identity case (preserves unfiltered behavior).

---

**Verdict: APPROVE**

- Critical findings: 0
- Important findings: 0 (1 auto-remediated)
- Suggestions: 0
- Observations: 3 (non-blocking)
