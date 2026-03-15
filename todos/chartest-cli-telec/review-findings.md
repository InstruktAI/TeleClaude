# Review Findings: chartest-cli-telec

## Scope

Reviewed characterization test delivery for 20 telec CLI source files. 99 tests across 23 new
files (~1860 lines). No production code modified. All implementation-plan tasks checked.

Review lanes executed: scope, code, paradigm, principles, security, tests, errors, comments,
logging, demo.

## Resolved During Review

### 1. String assertions on human-facing text (was Important, now Resolved)

~17 assertions across 7 test files violated the "no string assertions on human-facing text"
policy requirement. Replaced with data-value assertions, exit-code reliance, or non-empty output
checks.

Files modified:

- `tests/unit/cli/telec/handlers/test_config.py` — removed "Interactive config requires a terminal."
- `tests/unit/cli/telec/handlers/test_content.py` — removed "Only one text argument is allowed."
- `tests/unit/cli/telec/handlers/test_docs.py` — removed "At least one snippet ID is required."
- `tests/unit/cli/telec/handlers/test_demo.py` — replaced prose assertions with slug/token assertions
  (removed "Demo promoted:", category headers, "WARNING:", "Reviewer must verify", formatted SKIP/RUN lines)
- `tests/unit/cli/telec/handlers/test_events_signals.py` — replaced formatted label:value pairs with
  data-only assertions; removed "EVENT TYPE" header, "Signal Pipeline Status" heading, exact
  "Signal tables not initialized..." equality check
- `tests/unit/cli/telec/handlers/test_history.py` — removed "Search terms are required.",
  "Session ID is required."
- `tests/unit/cli/telec/handlers/test_memories.py` — removed "must be a number"

### 2. FakeMemoryClient class-level mutable state (was Important, now Resolved)

`FakeMemoryClient` stored call records on the class via `type(self).search_call = ...`, creating
shared state between tests. Added an `autouse` fixture to reset class attributes after each test.

File modified: `tests/unit/cli/telec/handlers/test_memories.py`

## Scope Lane

- 20/20 source files have corresponding test files. 1:1 mapping complete.
- All 20 implementation-plan tasks checked `[x]`.
- No production code modified.
- No deferrals.
- No gold-plating — delivery is strictly characterization tests.

No findings.

## Code Lane

- Test code is readable and consistently structured.
- `importlib.import_module()` pattern is appropriate for modules with heavy import-time dependencies.
- Test names are descriptive behavioral specifications.
- Mock counts within the 5-patch limit across all tests.

No findings.

## Paradigm Lane

- Tests follow pytest conventions with `monkeypatch`, `capsys`, `tmp_path`, and `patch.dict`.
- Existing codebase tests use class-based grouping and `@pytest.mark.unit` markers; new tests use
  flat functions without markers. This is a minor inconsistency but does not affect test discovery
  or execution.

No findings.

## Principles Lane

No production code changed. No architectural violations possible in test-only code.

No findings.

## Security Lane

- No secrets or credentials in test files.
- No injection vulnerabilities (tests do not execute user input).
- Test data uses safe example values (`person@example.com`, `/tmp/` paths, `sess-123`).

No findings.

## Tests Lane

Coverage is solid across the 20 source files. Some public functions lack dedicated tests
(covered indirectly through higher-level handler tests). These are noted as suggestions below.

No Important findings.

## Errors Lane

- No silent failures in the test code.
- Error paths are covered (invalid args, missing IDs, non-numeric inputs, event emit failures).
- The `_close_and_return` helper in test_bugs.py correctly handles coroutine cleanup when
  mocking `asyncio.run`.

No findings.

## Comments Lane

- Package `__init__.py` files have minimal docstrings. No stale or misleading comments.

No findings.

## Logging Lane

No production code changes. No logging concerns.

No findings.

## Demo Lane

- `no-demo` marker present: "internal characterization-test coverage only; no user-visible
  behavior change."
- Justification is valid: delivery adds only tests, touches no CLI/TUI/config/API surface.

Accepted.

## Suggestions

### S1. Remaining borderline string assertions

A few tests still assert on output text that mixes data with prose (e.g.,
`"Unknown events subcommand: unknown"`, `"does not take a slug"`, `"Delivered sample"`).
These are borderline — they contain the dynamic input value that proves data flow, making
them defensible as data assertions. Flagged for awareness, not action.

Locations: test_events_signals.py:65, test_events_signals.py:90, test_history.py:33,
test_history.py:74, test_history.py:113, test_history.py:152, test_demo.py:47,
test_roadmap.py:64, test_roadmap.py:93, test_todo.py:111, test_misc.py:67.

### S2. Coverage gaps for some public functions

Several source files have untested public functions. Key gaps:

- `auth_cmds._requires_tui_login()` — login gate logic
- `misc._handle_version()` — version composition
- `misc._handle_computers()`, `misc._handle_projects()` — delegation wiring
- `demo._extract_demo_blocks()`, `demo._check_no_demo_marker()` — parsing helpers
- `sessions.py` — 7 of 13 `__all__` functions uncovered (list, tail, run, restart, etc.)
- `infra.py` — `handle_agents_status`, `handle_channels_list` uncovered

These are acceptable for an initial characterization pass but noted for future coverage work.

### S3. Duplicated FakeConnection in test_events_signals.py

Two nearly-identical `FakeConnection` classes at lines 95 and 140. Could be extracted to a
shared fixture or module-level class.

### S4. `importlib.import_module("sys").modules` in test_misc.py

Line 23 uses `importlib.import_module("sys").modules` instead of the simpler `sys.modules`.
All other test files import `sys` directly for this pattern.

### S5. `test__shared.py` constant assertions are tautological

`test_shared_constants_match_tmux_and_tui_contract` asserts that string constants equal string
literals. Defensible for characterization (pins against accidental renames) but adds minimal
bug-catching value.

### S6. test_roadmap_deliver does not test conditional git logic

`test_handle_roadmap_deliver_runs_cleanup_and_git_steps` has subprocess mock return `returncode=1`
for all calls. A complementary test with `returncode=0` for `git diff --cached --quiet` would
verify the commit-skip logic.

## Verdict

**APPROVE**

All Important findings were resolved during review via auto-remediation. String assertion
violations (17 assertions across 7 files) were fixed. FakeMemoryClient test isolation issue
was fixed with an autouse reset fixture. 99 tests pass after remediation.
