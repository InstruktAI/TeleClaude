---
description: 'Per-test time budgets, suite wall-clock ceiling, zero-leak rule for subprocesses and async tasks, mandatory diagnostic on session-timeout. Doc-driven contract; every implementation choice must serve it.'
id: 'software-development/policy/test-resource-discipline'
scope: 'domain'
type: 'policy'
visibility: 'public'
---

# Test Resource Discipline — Policy

## Rules

### Time budgets

1. **Unit tests must complete in ≤1.0 second each.** Enforced by `pytest.mark.timeout(1)` assigned to every test carrying the `unit` marker via `pytest_collection_modifyitems` in the root conftest.
2. **Functional and integration tests must complete in ≤5.0 seconds each.** Enforced by `pytest.mark.timeout(5)` for `functional` and `integration` markers via the same hook.
3. **The full suite (`make test` / `telec code test --all`) must complete in <40 seconds wall-clock.** Enforced by `session_timeout = 40` in `pyproject.toml`.
4. **Per-test budgets and the suite ceiling are non-negotiable constants.** They do not get raised to make tests pass. A test that cannot fit its budget is one of: in the wrong tier (move it), doing too much (split it), or violating another rule in this policy (fix the violation).
5. **Per-test `timeout_method` is `signal`.** Tests that bypass signal-based interruption (async-only flows blocked inside C extensions, subprocess pipe reads that hold the GIL, hung greenlets) are responsible for surfacing their own hangs via fixture cleanup or explicit awaits with timeout.

### Zero-leak rule

6. **A test must leak no resource its body created.** No surviving subprocesses, no orphan `asyncio.Task` objects, no unclosed `aiosqlite` / `sqlalchemy` / `redis` connections, no open file descriptors, no `tempfile.TemporaryDirectory` left undeleted, no `monkeypatch` left unrestored, no listener / watcher / signal handler left registered.
7. **Every subprocess spawned by a test must be reaped by that test.** Either `proc.wait()` / `await proc.wait()` within the test body, or a fixture-scoped cleanup that runs in the test's teardown. The session-level subprocess reaper exists as a worker-stdout-unblocker, not as a substitute for per-test cleanup.
8. **Every `asyncio.Task` created by a test must terminate before the test ends.** Use `await task`, `task.cancel()` + `await task` (catching `CancelledError`), or `asyncio.wait_for(...)`. A test ending with a running task is a defect — the task continues consuming the event loop on the next test.
9. **No background thread, daemon thread, or signal handler may outlive the test that created it.** If production code installs one, the test must explicitly tear it down — or use a fixture that owns the lifetime.
10. **Temporary filesystem state must be deterministically cleaned.** Use `tmp_path` / `tmp_path_factory` (auto-cleanup) or `tempfile.TemporaryDirectory()` inside a `with` block. Never construct paths in module-scope state, never rely on GC for cleanup.

### Subprocess placement

11. **Unit tests must not spawn real subprocesses.** No `subprocess.run`, `subprocess.Popen`, `asyncio.create_subprocess_*`, `os.system`, `os.fork`, `os.exec*`, `os.spawn*`. If production code spawns, the unit test patches the spawn call at the boundary.
12. **Tests that require a real binary's behavior belong in `tests/functional/`** with explicit cleanup. Any test that touches `tmux`, `git`, `launchctl`, `ssh`, `redis-cli`, or any other external binary is functional by definition, regardless of how short it runs.
13. **Python self-spawn (`sys.executable`, `uv run`) in unit tests is the same defect** as external-binary spawn. If you need to exercise a CLI entry point, import the entry point and call it as a Python function with `monkeypatch` for `sys.argv` / `sys.exit`.

### Diagnostic visibility

14. **Every hang must be named in pytest output.** Per-test `pytest-timeout` flags the offending test by node id. The `session_timeout` backstop must additionally report each xdist worker's in-flight test node id at the moment of interrupt, via a `pytest_keyboard_interrupt` (or equivalent xdist hook) installed in the root conftest. A session-timeout fire that prints only `Interrupted` with no per-worker test id is itself a defect in the test infrastructure.
15. **Per-test infrastructure (autouse fixtures, `pytest_runtest_*` hookwrappers, collection modifiers) is the single highest-leverage source of suite regression.** Anything that runs on every test pays its cost × suite size; a 30 ms hookwrapper on 6,000 tests is 180 worker-seconds of waste invisible inside any individual test. Rule 3 (the 40 s ceiling) is the budget — collective, not per-piece. Two consequences:
    - **Code review of any change to `tests/conftest.py`, `tests/unit/conftest.py`, `tests/functional/conftest.py`, `tests/integration/conftest.py`, or `pyproject.toml` `[tool.pytest.ini_options]`** must include the before/after `make test` wall-clock in the PR description. The reviewer checks that the suite still fits under 40 s; if it doesn't, the change is reverted or the new hook is marker-scoped.
    - **No meta-tests pinning per-hook microbenchmarks.** The 40 s ceiling is the real assertion. The watchdog diagnostic names what runs when the ceiling fires. Together those catch the regression class without test-of-a-test machinery.
16. **Infrastructure for tests that spawn subprocesses must be marker-scoped, not global.** If a hook or fixture exists to clean up subprocess descendants, it lives behind the marker that identifies subprocess-spawning tests (`functional`, `integration`, or a dedicated `spawns_subprocess` marker) — not in the root conftest where it taxes every pure-Python unit test.

### Worker-bootstrap cost

17. **The root conftest must not import heavy modules at module scope.** Module-scope imports run once per xdist worker at startup; in a half-cores worker pool they multiply linearly. Modules that pull SQLAlchemy, greenlet, aiosqlite, psutil, or any other multi-hundred-millisecond import chain must be deferred to fixture scope or imported inside the function that needs them.
18. **The unit conftest (`tests/unit/conftest.py`) must override and no-op any global fixture that imports or initializes heavy state.** Unit tests run without database, transport, event-bus, or filesystem bootstrap unless they explicitly opt in via a fixture.

### What a test must do — and what is forbidden

The previous rules govern budget and infrastructure. These govern what makes a test legitimate at all. The test catalog is a shared resource; every test added pays a cost in wall-clock and in maintenance, and an illegitimate test pays that cost without returning any value.

19. **Every new test must add coverage of OUR logic or OUR code's behavior.** A test that does not exercise a branch, transformation, validation, decision, or side-effect that no other test already covers is rejected. Adding 10 tests in a PR that all hit the same branch is one test, not ten.

20. **`@pytest.mark.parametrize` is permitted only when each case hits a distinct branch or input-equivalence class.** Same-branch parametrize is the same-branch defect named in rule 19, just with less typing. If three parametrize cases all exercise the same `if` arm with cosmetically different inputs, collapse them to one case.

21. **Forbidden test shapes.** Each of the following is a tautology, an implementation snapshot, or testing the standard library / a dependency instead of our code. These cost wall-clock and maintenance without testing behavior:
    - `assert isinstance(x, T)` as the only assertion — testing Python's type system, not us.
    - `assert hasattr(obj, "field")` as the only assertion — testing dataclass / attrs machinery.
    - `assert MyClass(x=1).x == 1` — testing Python attribute assignment.
    - `assert MyClass().field == DEFAULT_VALUE` — testing pydantic/dataclass default-value handling; the library owns that contract.
    - `assert PALETTE["a"] == "#abc"`, `assert ENUM.A.value == "a"` — re-asserting a constant against itself.
    - Snapshot of a static string the production code returns verbatim (CLI help, error-message constants, format-string templates) — the literal either exists in the source or doesn't. Snapshot pinning the literal catches only typos that the source file already catches; it doesn't catch behavioral regressions because no behavior is being exercised.
    - `mock.method.return_value = X; assert wrapper(mock) == X` — testing the mock fixture, not our wrapper.
    - `import mymodule` with no further assertion — testing Python's import system.
    - Tautological round-trips through a library (`db.write(k, v); assert db.read(k) == v`) when the production code is a thin pass-through with no validation, transformation, or branching of its own — testing the library.

22. **The value gate.** Every test must be able to answer: *what regression in OUR code would this catch that no other test catches?* If the answer is "the constructor stores its argument" or "this enum has these values" or "this default value didn't change" — the test does not earn its place. Delete it.

## Rationale

- The 40-second ceiling exists so the suite stays inside a single working-memory window for the developer running it. A suite that overruns gets skipped, gets broken silently, and accumulates failures invisibly.
- The per-tier budgets exist because the tiers describe what a test is allowed to do. A unit test that needs >1s is doing more than a unit test should. The fix is structural (move it, split it, mock it), never to raise the budget.
- Resource leaks compound. One test leaking an `asyncio.Task` produces one warning; a hundred tests leaking tasks produces a worker that consumes 100% CPU on stale event-loop work and a developer machine that becomes unusable over time. The strict rule is the only rule that scales.
- The diagnostic requirement (rule 14) closes the loop on the session_timeout backstop. Without per-worker in-flight reporting, the backstop produces a silent kill with no actionable signal — the worst possible failure mode, since the offender is invisible and the suite still appears to "fail" the next run with no clue why.
- Marker-scoping infrastructure (rule 16) is the structural lesson from the subprocess-reaper hookwrapper incident: a global per-test hook with non-trivial cost is paid by every test in the suite, including the 95% that don't need it. The cost may be invisible in any single test but dominates the suite total. Scope by marker; benchmark; budget.

## Scope

- Applies to all tests in this repository under `tests/`.
- Applies to all conftest files (root and nested) and to every `pytest_*` hook, autouse fixture, and module-scope import they declare.
- Applies to all CI invocations of `make test` and `telec code test --all`.

## Enforcement

- `pytest_collection_modifyitems` in the root conftest assigns the per-tier `timeout` markers; the lint guard (`tools/lint/test_discipline.py`, runs as part of `make lint`) fails CI if the assigned values diverge from the documented budgets.
- `tools/lint/test_discipline.py` enforces the static rules of this policy: it AST-walks `tests/**/*.py` and `pyproject.toml` and fails with file:line for any per-test `timeout` override (rule 4), any `pytest.mark.expensive` decoration, any `pytest_runtest_protocol` hookwrapper in the root conftest (rule 16), any forbidden heavy module-scope import in the root conftest (rule 17), any real subprocess call in `tests/unit/**` (rules 11–13), and any drift of `session_timeout` from 40 s (rule 3).
- The 35 s suite ceiling itself is the overhead budget for all per-test infrastructure. No meta-test pins individual hook microbenchmarks; the collective wall-clock is the assertion. The watchdog diagnostic (rule 14) names whatever is running when the ceiling fires, which is how a per-test cost regression gets attributed to its source.
- Code review of any change to `tests/conftest.py`, `tests/unit/conftest.py`, `tests/functional/conftest.py`, `tests/integration/conftest.py`, or `pyproject.toml`'s `[tool.pytest.ini_options]` section requires a before/after `make test` wall-clock measurement in the PR description. A change that pushes the suite past 40 s is reverted or the new hook is marker-scoped.
- Code review of any new test (or PR adding tests) applies rules 19–22. A test that does not answer the value-gate question (rule 22) is rejected at review time. The lint guard does not (and cannot fully) detect forbidden test shapes at the AST level — code review is the enforcement mechanism for rules 19–22.

## Exceptions

- No exceptions to the per-tier budgets (rules 1-2) or the suite ceiling (rule 3). The "expensive" marker concept is forbidden — a test that doesn't run isn't a test, it's stale code pretending to be coverage. If a test cannot fit ≤5 s functional / ≤1 s unit, the test is wrong (misclassified, doing too much, or has a policy violation in rules 11-13).
- No exception exists for the zero-leak rule (rules 6–10). A leaking test is a defect regardless of tier.
- No exception exists for the no-real-subprocess-in-unit rule (rules 11–13). A unit test that needs a real subprocess is misclassified — move it, do not exempt it.
- No exception exists for per-test timeout overrides. The tier marker assigns the budget centrally in `pytest_collection_modifyitems`. No `@pytest.mark.timeout(N)` decoration or `pytestmark` containing a timeout marker is permitted anywhere in `tests/`. Enforced by `tools/lint/test_discipline.py`.
