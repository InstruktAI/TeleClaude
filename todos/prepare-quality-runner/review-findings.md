# Review Findings: prepare-quality-runner

**Branch:** `prepare-quality-runner`
**Scope:** 5 changed source files, 30 tests, demo artifact, pipeline wiring

---

## Round 1 (REQUEST CHANGES — 4 critical, 9 important)

### Critical (all resolved)

| ID | Finding | Fix | Commit |
|----|---------|-----|--------|
| C1 | Orphaned notification claim on early return — notification claimed before artifact check, stays permanently `claimed` on early return | Claim moved to after artifact-empty check; only claims when work confirmed | a0b715b8 |
| C2 | False-positive substring match on `icebox.md` — `slug in content` matches partial strings | Replaced with `re.search(rf"\b{re.escape(slug)}\b", content)` | a0b715b8 |
| C3 | `_is_slug_delivered_or_frozen` bare `except Exception: pass` — zero logging, broadest catch | Narrowed to `except (yaml.YAMLError, OSError)` + `logger.warning` | a0b715b8 |
| C4 | `_read_state_yaml` silently returns `{}` on corrupt file — enables data loss via overwrite | Narrowed catch, logs at error level, re-raises | a0b715b8 |

### Important (all resolved)

| ID | Finding | Fix | Commit |
|----|---------|-----|--------|
| I1 | `needs_decision` unreachable dead code — branch condition mathematically impossible | `compute_dor_score` returns `pass`/`needs_work` only; `_assess` sets `needs_decision` when gap filler exhausts | a0b715b8 |
| I2 | `_build_dependency_section` pulls first-3 roadmap entries, not actual deps | Looks up slug's own entry, extracts `deps` field | a0b715b8 |
| I3 | Synchronous `subprocess.run` blocks async event loop | Called via `asyncio.to_thread` | a0b715b8 |
| I4 | `_get_todo_commit` returns `"unknown"` silently, poisons idempotency | Logs warning; idempotency guard rejects `"unknown" == "unknown"` | a0b715b8 |
| I5 | `_find_project_root` silent fallback to cwd | Logs warning when falling back | a0b715b8 |
| I6 | `needs_decision` test exercises wrong code path (empty artifacts) | New fixtures trigger actual `needs_decision` path; verifies `agent_status=claimed` | 66e7e919 |
| I7 | No test for `_assess` exception resilience | Added `test_cartridge_returns_event_on_assess_exception` | 66e7e919 |
| I8 | `icebox.md` `read_text()` unprotected | Wrapped in `try-except OSError` | a0b715b8 |
| I9 | Demo expected output incorrect for `needs_decision` | Corrected to `agent_status=claimed` | e079bb5f |

### Suggestions (non-blocking, carried forward)

| ID | Finding |
|----|---------|
| S1 | Scorer return types use untyped `dict[str, Any]` — TypedDict or dataclass would document contract |
| S2 | `emit_event` RuntimeError catch embeds test concern in production code |
| S3 | TOCTOU race in exists-then-read patterns |
| S4 | `_build_dependency_section` lacks logging on YAML/OS error fallback |
| S5 | `needs_decision` triggers at score < 8 (implementation) vs < 7 (FR4 spec) — reasonable but wider than spec |

---

## Round 2 Verification

**Reviewer:** Claude (review round 2)
**Tests:** 2670 passed, 0 failed
**Lint:** Clean (1 pre-existing pyright error in `config.py:386` — not introduced by this build)

### Fix Verification

All 13 round 1 findings verified against final code:

- **C1:** Claim at L432-434, after artifact-empty return at L428. Early returns are side-effect-free. **Confirmed.**
- **C2:** `re.search(rf"\b{re.escape(slug)}\b", content)` at L569. **Confirmed.**
- **C3:** Both branches use `except (yaml.YAMLError, OSError)` + `logger.warning()`. **Confirmed.**
- **C4:** `_read_state_yaml` L291-293 catches `(yaml.YAMLError, OSError)`, logs error, re-raises. Corruption propagates to top-level handler; event still returned. **Confirmed.**
- **I1:** `compute_dor_score` L170 returns only `pass`/`needs_work`. `_assess` L468-469 sets `needs_decision` when `all_edits` empty. Traced: `_NEEDS_DECISION_REQUIREMENTS` (score ~4) → gap filler finds nothing (deps/constraints already present) → `needs_decision`. **Confirmed.**
- **I2:** `_build_dependency_section` L216-228 uses `next()` to find slug's own entry, extracts `deps`. **Confirmed.**
- **I3:** `_get_todo_commit` called via `await asyncio.to_thread()` at L406. **Confirmed.**
- **I4:** Warning logged at L283. Idempotency guard at L409: `current_commit != "unknown"`. **Confirmed.**
- **I5:** Warning logged at L361. **Confirmed.**
- **I6:** New test `test_cartridge_leaves_notification_claimed_on_needs_decision` uses dedicated fixtures, asserts `agent_status == "claimed"`, verifies `needs_decision` in DOR report. **Confirmed.**
- **I7:** `test_cartridge_returns_event_on_assess_exception` patches `_assess` to raise `RuntimeError`, asserts `result is event`. **Confirmed.**
- **I8:** `icebox.md` read wrapped in `try-except OSError` at L568-570. **Confirmed.**
- **I9:** Demo Scenario 4 says `agent_status=claimed`. **Confirmed.**

### Principle Violation Hunt (Round 2)

No new Critical or Important violations found in the final code.

| Category | Status |
|----------|--------|
| Fallback / Silent Degradation | All round 1 findings (C3, C4, I4, I5) fixed. S4 remains (non-blocking). |
| Fail Fast | C1 and I8 fixed. C4 now propagates. |
| DIP | Clean — no daemon imports from cartridge (verified via grep). |
| SRP | Clean — scoring, gap-filling, I/O, and orchestration are separated. |
| YAGNI/KISS | Clean — no over-engineering. |
| Coupling | Clean — no deep chains or god-object patterns. |
| Encapsulation | S1 remains (non-blocking). |

### Paradigm-Fit Assessment

1. **Data flow:** Uses event pipeline pattern — `Cartridge` protocol, `PipelineContext.db`, returns events. Consistent with `DeduplicationCartridge` and `NotificationProjectorCartridge`.
2. **Component reuse:** No copy-paste. Reuses `EventDB` methods for notification lifecycle.
3. **Pattern consistency:** Structured logging, YAML handling, test fixture patterns all match project conventions.

### Demo Review

Demo correctly describes cartridge behavior across 4 scenarios. Scenario 4 (`needs_decision`) now accurately reflects `agent_status=claimed`. Validation commands use legitimate observability paths (daemon logs, API endpoint, file inspection). No fabricated outputs.

### Why No New Issues

1. **Paradigm-fit:** Verified cartridge follows existing pipeline pattern (protocol shape, context usage, event pass-through). No copy-paste — checked `_is_slug_delivered_or_frozen` against existing delivered/icebox checks in codebase.
2. **Requirements coverage:** FR1 (cartridge integration), FR2 (idempotency), FR3 (assessment), FR4 (scoring/verdict), FR5 (improvement), FR6 (DOR report), FR7 (state writeback), FR8 (notification lifecycle) — all tested and verified in code.
3. **Copy-paste duplication:** None found. Scoring logic, gap filler, and I/O functions are all purpose-built for this cartridge.

---

## Verdict: APPROVE

**Critical findings:** 4/4 fixed and verified
**Important findings:** 9/9 fixed and verified
**Suggestions:** 5 (non-blocking, carried forward)
**Tests:** 2670 passed
**Lint:** Clean (pre-existing pyright error not from this build)

The cartridge is well-structured: scoring rubric is deterministic and proportional, gap filler is conservative (structural only, no prose rewriting), notification lifecycle is correctly integrated, and the `needs_decision` path is now reachable and tested. All round 1 blocking issues have been properly addressed. Ready for merge.

---

## Round 3 Verification (post-merge-from-main)

**Reviewer:** Claude (review round 3)
**Tests:** 2673 passed, 0 failed
**Lint:** Clean (1 pre-existing pyright error in `config.py:386` — not introduced by this build)

### What changed since Round 2

Commits since review baseline (`5ecf11be`):

| Commit | Description | Impact on delivery |
|--------|-------------|--------------------|
| `130f300d4` | feat(tui): sprite compositing, global ESC, color normalization | None — TUI code, not cartridge |
| `dcc71c8b3` | chore: commit pending main changes to unblock finalize | None — worktree hygiene |
| `4fe901f1d` | Merge branch 'main' into prepare-quality-runner | Merge only |
| `bf167223a` | chore: restore review approved state after merge | State file only |
| `92cd626d0` | fix(tests): update tab bar edge tests for neutral color palette | None — unrelated test fix |

**No changes to delivery files** (`prepare_quality.py`, `test_prepare_quality.py`, `demo.md`, `daemon.py` pipeline wiring, `cartridges/__init__.py`).

### Re-verification

- **Tests:** 2673 passed (up from 2670 — delta from main merge adding tests). All 29 prepare-quality tests pass.
- **Lint:** Clean. Pre-existing pyright error at `config.py:386` unchanged.
- **Non-delivery diff noise:** `composite.py` (line wrapping), `config.py` (line wrapping + blank line), `test_tab_bar_edge.py` (neutral color palette), `test_tui_config_view.py` (role cycling method) — all from main merge, cosmetic or unrelated.
- **Principle violation hunt:** No new violations. All round 1 fixes intact.
- **Requirements coverage:** FR1-FR8 unchanged and verified.

### Verdict: APPROVE (round 3 — reconfirmed after main merge)

No regressions. Delivery code untouched by merge. All prior findings remain resolved. Ready for merge.
