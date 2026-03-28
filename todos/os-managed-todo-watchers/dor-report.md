# DOR Gate Report — os-managed-todo-watchers

**Date:** 2026-03-27
**Score:** 9/10
**Verdict:** PASS

---

## Gate 1 — Intent & Success ✅

Problem statement is clear and grounded: daemon-owned `TodoWatcher` causes refresh amplification and thread pressure (API loop-lag hang dumps). The intended outcome — all filesystem observation moved to OS-managed watcher services — is explicit.

Five concrete, testable success criteria are provided. All are binary and verifiable by inspection or test. No fuzzy criteria ("works better," "more stable").

## Gate 2 — Scope & Size ✅

The work crosses multiple subsystems (watcher process, daemon route, auth, service installation, removal) but requirements explicitly justify not splitting: the pieces are not independently valuable and partial delivery leaves the architecture in a transitional state. The plan estimates ~500 lines of new code across 4 modules — fits one session.

The rollout sequence (additive before removal) provides internal structure without requiring multiple todos. The splitting rationale in requirements is documented and grounded.

## Gate 3 — Verification ✅

All 5 xfail test spec files are present and marked with the project's expected-failure convention:

| File                                                    | Requirements covered   |
| ------------------------------------------------------- | ---------------------- |
| `tests/unit/services/test_todo_watcher_filter.py`       | R1.2, R1.3, R1.4, R1.5 |
| `tests/unit/services/test_todo_watcher_process.py`      | R1.1, R1.6, R1.7       |
| `tests/unit/api/test_todo_watcher_route.py`             | R2.1–R2.7, R6.1        |
| `tests/unit/project_setup/test_todo_watcher_install.py` | R3.1–R3.4, R4.1–R4.6   |
| `tests/unit/core/test_todo_watcher_removal.py`          | R5.1–R5.2              |

R6.2 (migration path via idempotent re-run) is structurally covered by `TestIdempotentInstallation` in the installer specs. R7 is a non-functional rationale note — no test needed.

Task 6 (CLI help text) verification is observable (`telec init --help`) — not a test spec, which is correct per policy (prose-lock anti-pattern applies to string assertions on CLI help text).

## Gate 4 — Approach Known ✅

Technical path is fully specified and grounded against the codebase:

- **Filtering module:** Follows the pure-function pattern; shapes match what downstream tasks (route, process) need.
- **Route module:** References `teleclaude/api_server.py` lines 142–154 for the `include_router` pattern — verified to exist.
- **Watcher process:** References `teleclaude/cli/watch.py` watchdog pattern — module exists in codebase.
- **Service installer:** References `teleclaude/project_setup/sync.py:_install_launchd_watch` (confirmed at line 47) and integration point `teleclaude/project_setup/init_flow.py:install_docs_watch` (confirmed at line 196).
- **Daemon removal:** Pinpoints exact lines (36, 551–554, 595) — all verified present in `daemon.py`.

Three builder advisories (O1–O3) are documented:

- **O1:** Mock target names in route tests may need adjustment to match actual decomposition. Behavioral assertions must be preserved.
- **O2:** Installer test helpers read from real OS paths (`~/Library/LaunchAgents`, `~/.config/systemd/user`). Builder must implement output directory parameterization. Not a blocker; approach is prescribed.
- **O3:** Debounce tests use `asyncio.sleep(2.0)`. Make the debounce window configurable to avoid slow/flaky tests.

These advisories do not constitute unresolved unknowns — each has a clear prescribed resolution.

## Gate 5 — Research Complete ✅ (auto-satisfied)

No new third-party libraries are introduced. All dependencies are either standard library (`secrets`, `pathlib`, `asyncio`) or already established in the codebase (`watchdog` in `cli/watch.py`, `FastAPI APIRouter`, `launchd`/`systemd` via `project_setup/sync.py`). Gate is automatically satisfied.

## Gate 6 — Dependencies & Preconditions ✅

No prerequisite todos. The work is self-contained with an internal sequencing enforced by the plan's rollout sequence.

The `TELECLAUDE_WATCHER_SECRET` environment variable is service-injected (not user-configurable), so no config wizard, `config.sample.yml`, or teleclaude-config spec update is required.

Integration points confirmed:

- `init_flow.py`: `install_docs_watch` at line 196 — the new call follows after.
- `api_server.py`: `include_router` pattern at lines 142–154 — new route follows the same pattern.

## Gate 7 — Integration Safety ✅

R6.1 (additive before removal) is encoded in the task sequence: Tasks 1–4 build the replacement infrastructure; Task 5 removes the old watcher only after all new paths are functional and tested. The sequencing is explicit in the plan.

The new route is isolated to `/internal/watcher-notification` on the Unix-socket router — no conflict with existing TCP/public routes.

Daemon modification is surgical: remove 3 lines of import and 4 lines of task creation. No behavioral change to other daemon functionality.

No database schema changes or protocol changes requiring coordinated deployment.

## Gate 8 — Tooling Impact ✅

`telec init` behavior changes are addressed by Task 6 (CLI help text update). The plan identifies the relevant file (`teleclaude/cli/telec/surface.py` or equivalent) and the verification (`telec init --help` mentions todo watcher).

No other tooling procedures are impacted.

---

## Cross-Artifact Validation

### Plan-to-requirement fidelity

Every requirement maps to at least one plan task:

| Requirement                                                                            | Task                |
| -------------------------------------------------------------------------------------- | ------------------- |
| R1.1–R1.5 (observation, normalization, moves, noise, allowlist)                        | Tasks 1, 3          |
| R1.6–R1.7 (debounce, no semantic processing)                                           | Task 3              |
| R2.1–R2.7 (route auth, trust, refilter, invalidation, recompute, digest, transport)    | Task 2              |
| R3.1–R3.3 (secret gen, storage, injection)                                             | Task 4              |
| R3.4 (rejection on bad secret)                                                         | Task 2              |
| R4.1–R4.6 (macOS, Linux, no coarse units, platform scope, idempotent, one per project) | Task 4              |
| R5.1–R5.2 (no daemon obs, retire in-process watcher)                                   | Task 5              |
| R6.1 (additive before removal)                                                         | Rollout sequence    |
| R6.2 (migration via re-run)                                                            | Task 4 (idempotent) |
| Review-awareness (CLI help text)                                                       | Task 6              |

No orphan requirements. No orphan tasks.

### Verification chain

The plan's verification steps taken together would satisfy the DoD gates:

- All xfail markers removed → Testing gate met.
- Pre-commit hooks pass after Task 5 removal → Linting/import gate met.
- `telec init --help` updated → Documentation gate met.
- Route on Unix-socket router only → Security/transport gate met.

---

## Review-Readiness Assessment

### Testing lane

The test specs are behaviorally focused — no implementation leakage. Mock targets use module-level private function names (`_get_watcher_secret`, `_recompute_todos`, etc.) which is appropriate for this integration style. The O2 advisory (output directory parameterization) must be resolved before install tests can run in isolation — the builder knows this.

### Security lane

Authentication (R2.1, R3.4) is tested: valid/invalid/missing secret, and leakage prevention. Project trust verification (R2.2) is tested. Server-side re-filtering (R2.3) provides defense-in-depth — tested. The secret is generated via `secrets.token_hex(32)` — cryptographically adequate.

### Documentation lane

Task 6 explicitly addresses CLI help text. No config surface changes. Comments and API contracts are the builder's responsibility per code quality policy.

### Observability lane (minor gap)

The plan does not explicitly call for logging in the new route module or watcher process. This is a minor gap — the builder should follow existing codebase logging conventions at key boundaries (route entry, auth failure, recomputation trigger, digest comparison result). Not a blocker; no builder advisory exists for this yet.

---

## Verdict

**PASS** — Score 9/10. All DOR gates satisfied. All requirements have plan coverage. All test specs are present and well-formed. Referenced source paths are grounded and verified. Builder advisories O1–O3 prescribe solutions to known implementation challenges. One minor gap (observability planning) is addressable via codebase conventions without explicit instruction.

This artifact set is ready for the build phase.
