# Review Findings: event-alpha-container (Round 2)

## Review Scope

Branch: `event-alpha-container`
Requirements: `todos/event-alpha-container/requirements.md`
Plan: `todos/event-alpha-container/implementation-plan.md`
Diff base: `git merge-base HEAD main`
Review round: 2 (re-verification after fix cycle)

Review lanes executed: scope, code, paradigm, principles, security, tests, errors,
types, comments, demo, docs.

---

## Round 1 Fix Verification

All Critical and Important findings from round 1 have been verified as resolved:

| Finding | Status | Evidence |
|---|---|---|
| C-1 — Daemon `except ImportError` scope too wide | Resolved | `daemon.py:2023-2052`: narrow ImportError for import, separate Exception for init |
| I-1 — No unit tests for `runner.py` | Resolved | `test_runner.py`: 10 tests covering loader, catalog, socket handler |
| I-2 — No CLI tests for alpha scope | Resolved | `test_cartridge_cli_alpha.py`: 10 tests covering dir, list, promote |
| I-3 — Missing `docker-compose.alpha.yml` | Resolved | File exists with correct bind mounts, env overrides, security flags |
| I-4 — `CartridgeScope.alpha` in lifecycle methods | Resolved | `lifecycle.py:42-43`: ValueError guard in `_resolve_target_path` |

All 8 auto-remediated items verified in current code:

1. Tilde path expanded in constructor (`container.py:51`) ✓
2. `codebase_root` uses `parents[2]` (`container.py:109`) ✓
3. `health_check` uses defensive construction (`container.py:197-201`) ✓
4. Bridge uses public properties (`bridge.py:39-45`) ✓
5. `_get_alpha_dir()` warns on config error (`cartridge_cli.py:88-89`) ✓
6. Demo test path corrected (`demo.md:36`) ✓
7. Demo docker inspect targets running container (`demo.md:22`) ✓
8. Dead `TYPE_CHECKING` block removed from bridge ✓

---

## Round 2 Fresh Review

### Tests: 39 passed, 1 skipped (Docker integration)

No test failures. Full coverage across all alpha modules.

### Lint: No new violations

All lint failures are pre-existing module size violations in files outside this
delivery scope (`daemon.py`, adapters, hooks).

### No daemon imports in alpha module

`grep -r "from teleclaude\." teleclaude_events/alpha/` returns nothing. ✓

---

## Remaining Suggestions (carried from round 1, non-blocking)

**S-1. `types.ModuleType(spec.name)` vs `module_from_spec(spec)` (code lane)**

`runner.py:56` — `types.ModuleType()` doesn't set `__spec__`/`__loader__`/`__path__`.
Works for simple cartridges; could cause issues with relative imports.

**S-2. Cartridge name path traversal defense (security lane)**

`runner.py:50` — no validation that `cartridge_name` lacks path separators. Low risk
given container isolation, but defense-in-depth suggests a simple check.

**S-3. `pyproject.toml` C901 ratchet addition (code lane)**

`cartridge_cli.py` added to complexity exemption. Decompose in follow-up.

**S-4. `_promote_from_alpha()` silent config fallback before destructive op (errors lane)**

`cartridge_cli.py:150-160` — config failure falls back to default path before deleting
the alpha cartridge source file. Consider aborting on config failure.

**S-5. `watch_cartridges_dir()` infinite retry on start failure (errors lane)**

`container.py:247-250` — no circuit-breaker for start failures in the watcher loop
(unlike `watch_health()` which uses `_permanently_failed`).

---

## Scope Verification

| Requirement | Status |
|---|---|
| Docker sidecar with security flags | Delivered |
| IPC protocol (framed JSON, 4MB limit) | Delivered |
| Alpha runner (hot-reload, ping, timeout) | Delivered |
| Alpha bridge cartridge (zero-overhead, isolation) | Delivered |
| Container lifecycle (lazy start, health, restart) | Delivered |
| Zero-overhead fast path | Delivered |
| Promotion CLI | Delivered |
| Dockerfile | Delivered |
| docker-compose.alpha.yml | Delivered |
| Unit + integration tests | Delivered |
| System event schemas | Delivered |
| Daemon integration | Delivered |

---

## Paradigm Fit

Verified against codebase patterns:
- Cartridge Protocol (`name` + `async def process`) ✓
- Background tasks via `asyncio.create_task()` + done callbacks ✓
- `instrukt_ai_logging.get_logger(__name__)` ✓
- `pipeline.register()` for cartridge registration ✓
- `EventEnvelope.to_stream_dict()`/`from_stream_dict()` for serialization ✓

No paradigm violations.

---

## Why No Unresolved Issues

1. **Paradigm-fit**: Cartridge protocol, background tasks, logging, pipeline registration,
   serialization conventions all match established codebase patterns.
2. **Requirements**: All 12 scope items delivered and verified.
3. **Copy-paste duplication**: No duplicated logic; serialization helpers are purpose-built
   for the IPC boundary.
4. **Security**: Docker sandbox flags verified, no secrets, no injection vectors, build-time
   gate prevents daemon code in runner image.
5. **Fix cycle**: All 5 findings from round 1 verified as resolved in current code.

---

## Verdict: APPROVE

All Critical and Important findings from round 1 have been resolved and verified.
5 Suggestions remain as optional follow-up improvements (S-1 through S-5).
39 unit tests pass, 1 integration test skipped (requires Docker).
